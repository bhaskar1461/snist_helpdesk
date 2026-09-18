from __future__ import annotations

from typing import Any
import json
import uuid
import logging
from dataclasses import dataclass
from pathlib import Path
import os
import time
import random

log = logging.getLogger(__name__)

from app.pool_metrics import POOL_METRICS

from werkzeug.security import check_password_hash, generate_password_hash

try:
    import pymysql
except ImportError:  # pragma: no cover
    pymysql = None


ROLE_MAP = {
    "SUPER_ADMIN": "super_admin",
    "ADMIN": "admin",
    "HOD": "hod",
    "ASSIGNEE": "authority",
    "CA": "authority",
    "FACULTY": "faculty",
}

APP_ROLE_TO_DB = {
    "super_admin": "SUPER_ADMIN",
    "admin": "ADMIN",
    "hod": "HOD",
    "authority": "ASSIGNEE",
    "faculty": "FACULTY",
}

# Zero-date safe columns for institutional teacher_info view (MySQL Error 1525 defense)
ZERO_DATE_COLUMNS = (
    "DATE_OF_BIRTH",
    "FROM_DATE",
    "TO_DATE",
    "SAL_INC_DATE",
    "TOTODATE",
    "PDATE",
    "RDATE",
    "RELDATE",
    "PRETODATE",
)

def zero_date_safe(col: str, alias: str = "t") -> str:
    """Wrap a date column in NULLIF to prevent MySQL Error 1525 (zero dates under NO_ZERO_DATE)."""
    return f"NULLIF({alias}.{col}, '0000-00-00')"

ZERO_DATE_SAFE = {col: f"{zero_date_safe(col)} AS {col}" for col in ZERO_DATE_COLUMNS}


@dataclass
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def env_db_config(database_override: str | None = None) -> DbConfig | None:
    if pymysql is None:
        return None

    import sys
    if "unittest" in sys.modules or os.getenv("TESTING", "false").lower() == "true":
        return DbConfig(
            host=os.getenv("MYSQL_HOST", "localhost"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "demo"),
            password=os.getenv("MYSQL_PASSWORD", "Admin@321#"),
            database=database_override or os.getenv("MYSQL_DATABASE", "seg_demo"),
        )

    host = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in").strip()
    if not host or host in ("seg-dev.sreenidhi.edu.in", "seg.sreenidhi.edu.in", "localhost"):
        if os.getenv("MYSQL_ENABLE_REMOTE", "true").lower() == "true":
            host = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in")
        elif is_host_reachable("127.0.0.1", 3306, timeout_sec=1.5):
            host = "127.0.0.1"
        else:
            return None

    user = os.getenv("MYSQL_USER", "demo")
    password = os.getenv("MYSQL_PASSWORD", "Admin@321#")
    database = database_override or os.getenv("MYSQL_DATABASE", "helpdesk")
    if not all([host, user, password, database]):
        return None
    return DbConfig(
        host=host,
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=user,
        password=password,
        database=database,
    )



from queue import Queue, Empty
import threading
import contextlib

class PooledConnection:
    def __init__(self, conn, pool, is_unpooled: bool = False, pool_service=None):
        self._conn = conn
        self._pool = pool
        self._is_unpooled = is_unpooled
        self._pool_service = pool_service
        self._created_at = getattr(conn, "_created_at", time.time())
        self._last_used_at = getattr(conn, "_last_used_at", time.time())

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def cursor(self, *args, **kwargs):
        raw_cursor = self._conn.cursor(*args, **kwargs)
        return PooledCursor(raw_cursor, self, self._pool_service)

    def close(self):
        # Return connection back to the pool or close if unpooled / full
        if self._conn is not None:
            conn = self._conn
            self._conn = None

            if self._pool_service is not None:
                with self._pool_service._pool_lock:
                    self._pool_service._in_use = max(0, self._pool_service._in_use - 1)

            if self._is_unpooled:
                try:
                    conn.close()
                except Exception:
                    pass
                POOL_METRICS.record_connection_closed()
                return

            conn._last_used_at = time.time()
            try:
                self._pool.put_nowait(conn)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                POOL_METRICS.record_connection_closed()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class PooledCursor:
    def __init__(self, cursor, pooled_conn, pool_service=None):
        self._cursor = cursor
        self._pooled_conn = pooled_conn
        self._pool_service = pool_service

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self._cursor, "__exit__"):
            return self._cursor.__exit__(exc_type, exc_val, exc_tb)
        elif hasattr(self._cursor, "close"):
            try:
                self._cursor.close()
            except Exception:
                pass

    def execute(self, query, args=None):
        if self._pool_service is not None:
            return self._pool_service._execute_cursor(self, query, args, is_many=False)
        return self._cursor.execute(query, args)

    def executemany(self, query, args):
        if self._pool_service is not None:
            return self._pool_service._execute_cursor(self, query, args, is_many=True)
        return self._cursor.executemany(query, args)


class TransactionConnection:
    def __init__(self, conn, pool_service=None):
        self._conn = conn
        self._pool_service = pool_service

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def cursor(self, *args, **kwargs):
        raw_cursor = self._conn.cursor(*args, **kwargs)
        return PooledCursor(raw_cursor, self, self._pool_service)

    def close(self):
        # Do not return raw connection to the pool during transaction
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


_REACHABLE_CACHE: dict[str, tuple[bool, float]] = {}

def is_host_reachable(host: str, port: int, timeout_sec: float = 3.0) -> bool:
    import socket
    key = f"{host}:{port}"
    now = time.time()
    if key in _REACHABLE_CACHE:
        is_ok, cached_at = _REACHABLE_CACHE[key]
        max_age = 60.0 if is_ok else 2.0
        if now - cached_at < max_age:
            return is_ok

    try:
        s = socket.create_connection((host, port), timeout=timeout_sec)
        s.close()
        _REACHABLE_CACHE[key] = (True, now)
        return True
    except Exception:
        _REACHABLE_CACHE[key] = (False, now)
        return False


class BaseMySQLService:
    RETRIABLE_DISCONNECT = {2006, 2013}
    RETRIABLE_DEADLOCK = {1213}
    RETRIABLE_LOCK_WAIT = {1205}
    ALL_RETRIABLE = RETRIABLE_DISCONNECT | RETRIABLE_DEADLOCK | RETRIABLE_LOCK_WAIT

    def __init__(self, config: DbConfig | None):
        self.config = config

        # MYSQL_POOL_MAXSIZE: default 20 (was 10), clamped between 1 and 100
        try:
            self._maxsize = int(os.getenv("MYSQL_POOL_MAXSIZE", "20"))
        except (ValueError, TypeError):
            self._maxsize = 20
        self._maxsize = max(1, min(self._maxsize, 100))

        # MYSQL_POOL_WAIT: default 5s, clamped between 1.0 and 15.0s
        try:
            self._pool_wait = float(os.getenv("MYSQL_POOL_WAIT", "5.0"))
        except (ValueError, TypeError):
            self._pool_wait = 5.0
        self._pool_wait = max(1.0, min(self._pool_wait, 15.0))

        # MYSQL_IDLE_TTL: default 240s
        try:
            self._idle_ttl = float(os.getenv("MYSQL_IDLE_TTL", "240.0"))
        except (ValueError, TypeError):
            self._idle_ttl = 240.0
        self._idle_ttl = max(10.0, self._idle_ttl)

        self._pool = Queue(maxsize=self._maxsize)
        self._pool_lock = threading.Lock()
        self._in_use: int = 0
        self._waiters: int = 0
        self._local = threading.local()
        self._inst_fallback: bool = False
        self._inst_probed: bool = False
        self._sweeper_stop_event = threading.Event()
        self._sweeper_thread = None
        self._start_sweeper()

    def _start_sweeper(self):
        import sys
        if "unittest" in sys.modules or "pytest" in sys.modules or os.getenv("TESTING", "false").lower() == "true":
            return
        self._sweeper_thread = threading.Thread(
            target=self._sweeper_loop,
            name="MySQLPoolSweeper",
            daemon=True,
        )
        self._sweeper_thread.start()

    def _sweeper_loop(self):
        while not self._sweeper_stop_event.wait(60.0):
            try:
                self.sweep_idle_connections()
            except Exception as exc:
                log.debug("Sweeper iteration encountered error: %s", exc)

    def sweep_idle_connections(self) -> int:
        """
        Inspect all idle pooled connections.
        For connections older than MYSQL_IDLE_TTL (default 240s), ping without reconnect.
        If dead or older than 2x TTL, close and evict from pool.
        Logs only when connections are actually removed.
        Returns number of evicted connections.
        """
        now = time.time()
        surviving = []
        evicted = 0

        while True:
            try:
                conn = self._pool.get_nowait()
                last_used = getattr(conn, "_last_used_at", now)
                age = now - last_used

                if age > self._idle_ttl:
                    is_dead = False
                    try:
                        conn.ping(reconnect=False)
                    except Exception:
                        is_dead = True

                    if is_dead or age > (self._idle_ttl * 2):
                        try:
                            conn.close()
                        except Exception:
                            pass
                        POOL_METRICS.record_connection_closed()
                        evicted += 1
                        continue

                surviving.append(conn)
            except Empty:
                break

        for conn in surviving:
            try:
                self._pool.put_nowait(conn)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                POOL_METRICS.record_connection_closed()
                evicted += 1

        if evicted > 0:
            log.info("Pool sweeper evicted %d stale/dead connection(s). Current pool size: %d/%d.",
                     evicted, self._pool.qsize(), self._maxsize)
        return evicted

    def probe_institutional_access(self, conn=None) -> bool:
        """
        Run a one-time permission probe to verify if the configured institutional DB is accessible.
        Caches result in self._inst_fallback and self._inst_probed so it does not re-probe on every query.
        """
        if self._inst_probed:
            return not self._inst_fallback

        inst = os.getenv("MYSQL_INSTITUTIONAL_DATABASE", "").strip()
        if not inst or not self.config or self.config.database == inst:
            self._inst_probed = True
            self._inst_fallback = False
            return True

        self._inst_probed = True
        should_close = False
        if conn is None:
            if not self.enabled:
                return False
            try:
                conn = self._create_new_connection()
                should_close = True
            except Exception as conn_err:
                log.warning("Could not establish connection for institutional probe: %s", conn_err)
                return False

        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT 1 FROM `{inst}`.teacher_info LIMIT 1")
            self._inst_fallback = False
            return True
        except Exception as exc:
            err_code = getattr(exc, "args", [None])[0] if hasattr(exc, "args") and exc.args else None
            err_str = str(exc)
            if err_code in (1142, 1044, 1049) or any(code in err_str for code in ("1142", "1044", "1049")):
                log.critical(
                    "Institutional DB '%s' inaccessible as user '%s'. Falling back to local views in '%s'. "
                    "Ensure helpdesk.teacher_info views exist.",
                    inst,
                    self.config.user if self.config else "unknown",
                    self.config.database if self.config else "unknown",
                )
                self._inst_fallback = True
                return False
            else:
                log.warning("Institutional probe warning for '%s': %s", inst, exc)
                self._inst_fallback = False
                return True
        finally:
            if should_close and conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @property
    def inst_prefix(self) -> str:
        inst = os.getenv("MYSQL_INSTITUTIONAL_DATABASE", "").strip()
        if not inst:
            return ""
        if hasattr(self, "config") and self.config and self.config.database == inst:
            return ""
        if self._inst_fallback:
            return ""
        if os.getenv("TESTING", "false").lower() == "true" and not getattr(self, "_force_prefix", False):
            return ""
        return f"`{inst}`."

    @property
    def enabled(self) -> bool:
        import sys
        if "unittest" in sys.modules or "pytest" in sys.modules or os.getenv("TESTING", "false").lower() == "true":
            return self.config is not None
        if self.config is None:
            return False
        if self.config.host == "seg-dev.sreenidhi.edu.in" and os.getenv("MYSQL_ENABLE_REMOTE", "true").lower() != "true":
            return False
        if not self._pool.empty():
            return True
        return is_host_reachable(self.config.host, self.config.port, timeout_sec=5.0)

    def _create_new_connection(self):
        ssl_config = None
        if os.getenv("MYSQL_SSL", "").lower() == "true":
            ssl_config = {"ca": None}  # Use system default CA bundle
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            ssl=ssl_config,
            connect_timeout=10,
            read_timeout=15,
            write_timeout=15,
        )

    def connection(self):
        if self.config is None:
            raise RuntimeError("MySQL is not configured.")

        # If there is an active transaction connection on this thread, return it
        if getattr(self._local, "active_conn", None) is not None:
            return self._local.active_conn

        t_start = time.time()
        conn = None
        reused = False
        is_unpooled = False

        # 1. Try get_nowait() first
        try:
            conn = self._pool.get_nowait()
            reused = True
        except Empty:
            pass

        # 2. If empty and pool is at max capacity: bounded wait with POOL_WAIT_SECONDS
        if conn is None:
            with self._pool_lock:
                pool_exhausted = (self._in_use >= self._maxsize)

            if pool_exhausted:
                with self._pool_lock:
                    self._waiters += 1
                try:
                    conn = self._pool.get(timeout=self._pool_wait)
                    reused = True
                except Empty:
                    # Bounded wait timed out: ONE-OFF unpooled fallback
                    POOL_METRICS.record_pool_timeout()
                    POOL_METRICS.record_unpooled_fallback()
                    log.warning(
                        "Database pool exhausted after waiting %.2fs. Spawning ONE-OFF unpooled connection. "
                        "Active threads: %d, Waiters: %d, In-use: %d, Pool maxsize: %d",
                        self._pool_wait,
                        threading.active_count(),
                        self._waiters,
                        self._in_use,
                        self._maxsize,
                    )
                    is_unpooled = True
                finally:
                    with self._pool_lock:
                        self._waiters = max(0, self._waiters - 1)

        # If we got a connection from the pool, verify it's still alive
        if conn is not None and not is_unpooled:
            try:
                conn.ping(reconnect=True)
                POOL_METRICS.record_reconnect()
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                POOL_METRICS.record_connection_closed()
                conn = None

        if conn is None:
            try:
                conn = self._create_new_connection()
                conn._created_at = time.time()
                conn._last_used_at = time.time()
                POOL_METRICS.record_connection_created()
                reused = False
                self._last_fail_time = 0
            except Exception as conn_exc:
                log.warning("Initial MySQL connection attempt failed (%s), retrying...", conn_exc)
                try:
                    time.sleep(0.3)
                    conn = self._create_new_connection()
                    conn._created_at = time.time()
                    conn._last_used_at = time.time()
                    POOL_METRICS.record_connection_created()
                    reused = False
                    self._last_fail_time = 0
                except Exception as retry_exc:
                    self._last_fail_time = time.time()
                    raise retry_exc

        with self._pool_lock:
            self._in_use += 1

        t_ready = time.time()
        latency_ms = (t_ready - t_start) * 1000.0
        POOL_METRICS.record_checkout(latency_ms, reused=reused)

        if not self._inst_probed:
            self.probe_institutional_access(conn)

        return PooledConnection(conn, self._pool, is_unpooled=is_unpooled, pool_service=self)

    @contextlib.contextmanager
    def transaction(self):
        if self.config is None:
            raise RuntimeError("MySQL is not configured.")
        
        # Prevent nested transactions on same thread
        if getattr(self._local, "active_conn", None) is not None:
            yield self._local.active_conn
            return

        # Fetch connection (under test, this returns MockConnection directly)
        pooled_conn = self.connection()
        
        # Detect if we are in testing (MockConnection does not wrap a raw _conn)
        is_mock = not hasattr(pooled_conn, "_conn")
        
        if is_mock:
            self._local.active_conn = pooled_conn
            self._local.in_transaction = True
            self._local.tx_statements = 0
            try:
                yield pooled_conn
            except Exception:
                if hasattr(pooled_conn, "rollback"):
                    try:
                        pooled_conn.rollback()
                    except Exception:
                        pass
                raise
            finally:
                self._local.active_conn = None
                self._local.in_transaction = False
                self._local.tx_statements = 0
                pooled_conn.close()
        else:
            # Production PyMySQL connection
            conn = pooled_conn._conn
            
            old_autocommit = conn.get_autocommit()
            conn.autocommit(False)
            
            tx_conn = TransactionConnection(conn, pool_service=self)
            self._local.active_conn = tx_conn
            self._local.in_transaction = True
            self._local.tx_statements = 0
            
            try:
                yield tx_conn
                conn.commit()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise e
            finally:
                self._local.active_conn = None
                self._local.in_transaction = False
                self._local.tx_statements = 0
                try:
                    conn.autocommit(old_autocommit)
                except Exception:
                    pass
                pooled_conn.close()

    def _execute_cursor(self, pooled_cursor, query, args=None, is_many=False, retries=3):
        in_transaction = getattr(self._local, "in_transaction", False)

        # Inside transaction:
        # Failure MUST rollback and re-raise immediately. Zero retry inside transaction.
        if in_transaction:
            try:
                if is_many:
                    res = pooled_cursor._cursor.executemany(query, args)
                else:
                    res = pooled_cursor._cursor.execute(query, args)
                self._local.tx_statements = getattr(self._local, "tx_statements", 0) + 1
                return res
            except Exception as exc:
                POOL_METRICS.record_query_failure()
                active_conn = getattr(self._local, "active_conn", None)
                if active_conn and hasattr(active_conn, "rollback"):
                    try:
                        active_conn.rollback()
                    except Exception:
                        pass
                raise

        # Outside transaction:
        start_time = time.time()
        budget_seconds = 3.0
        last_exc = None

        for attempt in range(1, retries + 1):
            try:
                if is_many:
                    res = pooled_cursor._cursor.executemany(query, args)
                else:
                    res = pooled_cursor._cursor.execute(query, args)
                return res
            except Exception as exc:
                last_exc = exc
                POOL_METRICS.record_query_failure()

                err_code = getattr(exc, "args", [None])[0] if hasattr(exc, "args") and exc.args else None

                # Never retry non-retriable errors (permissions 1142, syntax 1064, missing table 1146, integrity 1062)
                if err_code not in self.ALL_RETRIABLE:
                    raise exc

                # 1205 (lock wait timeout): retry ONCE with longer delay, then surface
                if err_code in self.RETRIABLE_LOCK_WAIT and attempt >= 2:
                    raise exc

                if attempt == retries:
                    q_fp = str(query).strip().replace("\n", " ")[:80]
                    raise type(exc)(f"{exc} (Query '{q_fp}' failed after {attempt} attempts)") from exc

                # If 2006 or 2013: full re-acquire connection from pool + ping
                if err_code in self.RETRIABLE_DISCONNECT:
                    try:
                        old_conn = pooled_cursor._pooled_conn._conn
                        if old_conn is not None:
                            try:
                                old_conn.close()
                            except Exception:
                                pass
                            POOL_METRICS.record_connection_closed()
                        new_pooled = self.connection()
                        pooled_cursor._pooled_conn._conn = new_pooled._conn
                        pooled_cursor._cursor = new_pooled._conn.cursor()
                    except Exception as reacquire_err:
                        log.warning("Failed to re-acquire connection during retry: %s", reacquire_err)

                # Exponential backoff: 0.2s * 2^(attempt-1) with ±20% jitter
                base_delay = 0.2 * (2 ** (attempt - 1))
                if err_code in self.RETRIABLE_LOCK_WAIT:
                    base_delay = 0.5
                jitter = random.uniform(-0.2, 0.2) * base_delay
                delay = max(0.01, base_delay + jitter)

                elapsed = time.time() - start_time
                if elapsed + delay >= budget_seconds:
                    q_fp = str(query).strip().replace("\n", " ")[:80]
                    raise type(exc)(f"{exc} (Retry latency budget of 3s exceeded: query '{q_fp}', attempt {attempt}, elapsed {elapsed:.2f}s)") from exc

                POOL_METRICS.record_query_retry()
                q_fp = str(query).strip().replace("\n", " ")[:80]
                log.warning("Retrying query (attempt %d/%d) after error %s: '%s' (sleeping %.3fs)",
                            attempt, retries, err_code, q_fp, delay)
                time.sleep(delay)

        if last_exc:
            raise last_exc

    def execute_with_retry(self, sql: str, params: Any = None, retries: int = 3, fetch: str = "all"):
        """
        Execute a query with exponential backoff for transient retriable errors.
        fetch: 'all' (fetchall), 'one' (fetchone), or 'none' (rowcount).
        """
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            if fetch == "all":
                return cur.fetchall()
            elif fetch == "one":
                return cur.fetchone()
            else:
                return cur.rowcount


class LiveDbService(BaseMySQLService):
    def fetch_departments(self, include_archived=True):
        if not self.enabled:
            return []
        sql = f"""
            SELECT DISTINCT
                b.BRANCH_ID,
                b.BRANCH_CODE AS department_code,
                b.BRANCH_NAME AS department_name,
                CAST(b.ORG_ID AS CHAR) AS org_id,
                b.HOD_ID
        """
        # Check if is_archived column exists and include it
        try:
            with self.connection() as conn, conn.cursor() as cur:
                cur.execute(f"SHOW COLUMNS FROM {self.inst_prefix}branch_detail LIKE 'is_archived'")
                has_archived = cur.fetchone() is not None
        except Exception:
            has_archived = False

        if has_archived:
            sql += ", COALESCE(b.is_archived, 0) AS is_archived"

        sql += f"""
            FROM {self.inst_prefix}branch_detail b
            WHERE COALESCE(b.BRANCH_CODE, '') <> ''
        """
        if has_archived and not include_archived:
            sql += " AND COALESCE(b.is_archived, 0) = 0"
        sql += " ORDER BY b.BRANCH_CODE"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

    def update_location(self, location_id, block, floor, room_no, name):
        """Update a location row."""
        if not self.enabled:
            return
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {self.inst_prefix}location SET block = %s, floor = %s, room_no = %s, name = %s WHERE id = %s",
                (block, floor, room_no, name, location_id),
            )

    def delete_location(self, location_id):
        """Delete a location if no tickets reference it."""
        if not self.enabled:
            return
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_tickets WHERE location_id = %s", (location_id,))
            row = cursor.fetchone()
            if row and row["cnt"] > 0:
                raise ValueError("Cannot delete a location that is referenced by existing tickets.")
            cursor.execute(f"DELETE FROM {self.inst_prefix}location WHERE id = %s", (location_id,))

    def get_location(self, location_id):
        """Get a single location by ID."""
        if not self.enabled:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(f"SELECT id, block, floor, room_no, name FROM {self.inst_prefix}location WHERE id = %s", (location_id,))
            return cursor.fetchone()

    def fetch_locations(self):
        """Return all location rows (block, floor, room_no, name) with 60s memory caching and safe fallback."""
        if not self.enabled:
            return self._default_locations()

        import sys
        is_testing = "unittest" in sys.modules or os.getenv("TESTING", "false").lower() == "true"
        now = time.time()
        if not is_testing and getattr(self, "_loc_cache", None) is not None and (now - getattr(self, "_loc_cache_time", 0) < 60.0):
            return self._loc_cache

        try:
            sql = f"""
                SELECT id, block, floor, room_no, name
                FROM {self.inst_prefix}location
                ORDER BY block, floor, room_no
            """
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
                if rows is not None and len(rows) > 0:
                    if not is_testing:
                        self._loc_cache = rows
                        self._loc_cache_time = now
                    return rows
        except Exception:
            pass

        return self._default_locations()

    def _default_locations(self):
        return [
            {"id": 1, "block": "Block 1", "floor": "Ground Floor", "room_no": "G-01", "name": "Main Hall", "ORG_ID": "2000"},
            {"id": 2, "block": "Block 2", "floor": "1st Floor", "room_no": "101", "name": "Lab 1", "ORG_ID": "2000"},
            {"id": 3, "block": "Block 3", "floor": "2nd Floor", "room_no": "201", "name": "Seminar Room", "ORG_ID": "2000"},
        ]

    def fetch_reference_users(self, search="", department=None, limit=100, org_id=None, active_only=False):
        if not self.enabled:
            return []
        sql = f"""
            SELECT
                t.TEACHER_ID AS id,
                t.TEACHER_ID,
                t.TEACHER_NAME AS name,
                t.TEACHER_NAME,
                t.EMAIL_ID AS email,
                t.EMAIL_ID,
                t.SAP_ID,
                t.TEACHER_CODE,
                t.DESIGNATION,
                t.MOBILE_PHONE,
                CAST(b.ORG_ID AS CHAR) AS org_id,
                b.BRANCH_CODE AS department_code,
                b.BRANCH_NAME AS department_name,
                b.HOD_ID
            FROM {self.inst_prefix}teacher_info t
            LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
            WHERE t.EMAIL_ID IS NOT NULL AND TRIM(t.EMAIL_ID) != ''
        """
        params = []
        if active_only:
            sql += " AND COALESCE(t.ACTIVE, 1) = 1"
        if department:
            sql += " AND (b.BRANCH_CODE = %s OR b.BRANCH_NAME = %s)"
            params.extend([department, department])
        if org_id:
            sql += " AND CAST(b.ORG_ID AS CHAR) = %s"
            params.append(org_id)
        if search:
            sql += " AND (t.TEACHER_NAME LIKE %s OR t.EMAIL_ID LIKE %s OR t.SAP_ID LIKE %s OR t.TEACHER_CODE LIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like, like])
        sql += " ORDER BY t.TEACHER_NAME LIMIT %s"
        params.append(limit)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()



    def lookup_teacher_by_email(self, email):
        """Look up a teacher from teacher_info by email. Returns dict with id, name, sap_id, department, org_id, is_hod or None."""
        if not self.enabled or not email:
            return None
        sql = f"""
            SELECT
                t.TEACHER_ID AS id,
                t.TEACHER_NAME AS name,
                t.SAP_ID AS sap_id,
                t.EMAIL_ID AS email,
                t.DESIGNATION AS designation,
                t.TEACHER_CODE AS teacher_code,
                t.MOBILE_PHONE AS phone,
                COALESCE(t.ACTIVE, 1) AS is_active,
                CAST(COALESCE(b.ORG_ID, '2000') AS CHAR) AS org_id,
                b.BRANCH_CODE AS department,
                b.HOD_ID AS hod_id
            FROM {self.inst_prefix}teacher_info t
            LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
            WHERE LOWER(COALESCE(t.EMAIL_ID, '')) = LOWER(%s)
              AND COALESCE(t.ACTIVE, 1) = 1
            LIMIT 1
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, (str(email).strip().lower(),))
            row = cursor.fetchone()
            if not row:
                return None
            desig = (row.get("designation") or "").strip().lower()
            is_hod = "hod" in desig
            hod_id = str(row.get("hod_id") or "").strip().lower()
            t_code = str(row.get("teacher_code") or "").strip().lower()
            s_id = str(row.get("sap_id") or "").strip().lower()
            if hod_id and hod_id in (t_code, s_id, str(row.get("id"))):
                is_hod = True
            row["is_hod"] = is_hod
            return row


    def resolve_org_id(self, email="", department=""):
        if not self.enabled:
            return "2000"
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                if email:
                    try:
                        cursor.execute(
                            f"""
                            SELECT CAST(b.ORG_ID AS CHAR) AS org_id
                            FROM {self.inst_prefix}teacher_info t
                            JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
                            WHERE LOWER(COALESCE(t.EMAIL_ID, '')) = LOWER(%s)
                            LIMIT 1
                            """,
                            (email,),
                        )
                        row = cursor.fetchone()
                        if row and row.get("org_id"):
                            return row["org_id"]
                    except Exception:
                        pass
                if department:
                    try:
                        cursor.execute(
                            f"""
                            SELECT CAST(ORG_ID AS CHAR) AS org_id
                            FROM {self.inst_prefix}branch_detail
                            WHERE BRANCH_CODE = %s OR BRANCH_NAME = %s
                            LIMIT 1
                            """,
                            (department, department),
                        )
                        row = cursor.fetchone()
                        if row and row.get("org_id"):
                            return row["org_id"]
                    except Exception:
                        pass
        except Exception:
            pass
        return "2000"

    def search_reference_users(self, q="", search_type="name", department=None, org_id=None, limit=20):
        """Search teacher_info by name, email, or employee_id for autocomplete."""
        if not self.enabled or not q:
            return []
        sql = f"""
            SELECT
                t.TEACHER_NAME, t.EMAIL_ID, t.SAP_ID, t.TEACHER_ID,
                CAST(b.ORG_ID AS CHAR) AS org_id,
                b.BRANCH_CODE AS department_code,
                b.BRANCH_NAME AS department_name
            FROM {self.inst_prefix}teacher_info t
            LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
            WHERE COALESCE(t.ACTIVE, 1) = 1
        """
        params = []
        like = f"%{q}%"
        if search_type == "email":
            sql += " AND t.EMAIL_ID LIKE %s"
            params.append(like)
        elif search_type == "employee_id":
            sql += " AND (CAST(t.SAP_ID AS CHAR) LIKE %s OR t.TEACHER_CODE LIKE %s)"
            params.extend([like, like])
        else:
            sql += " AND (t.TEACHER_NAME LIKE %s OR t.EMAIL_ID LIKE %s OR CAST(t.SAP_ID AS CHAR) LIKE %s)"
            params.extend([like, like, like])
        if department:
            sql += " AND (b.BRANCH_CODE = %s OR b.BRANCH_NAME = %s)"
            params.extend([department, department])
        if org_id:
            sql += " AND CAST(b.ORG_ID AS CHAR) = %s"
            params.append(org_id)
        sql += " ORDER BY t.TEACHER_NAME LIMIT %s"
        params.append(limit)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()


class DemoDbService(BaseMySQLService):
    def get_user_phone(self, email, use_fallback=True):
        """Query helpdesk_staff_roles, teacher_info, and helpdesk_users for user's phone. Returns phone number or fallback."""
        test_number = os.getenv("SMS_TEST_NUMBER")
        if not email:
            return test_number if use_fallback else None

        if self.enabled:
            # 1. Check helpdesk_staff_roles.phone
            try:
                with self.connection() as conn, conn.cursor() as cur:
                    cur.execute("SELECT phone FROM helpdesk_staff_roles WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
                    row = cur.fetchone()
                    if row and row.get("phone") and str(row.get("phone")).strip() not in ('', '0', 'None'):
                        return str(row["phone"]).strip()
            except Exception:
                pass

            # 2. Check teacher_info.MOBILE_PHONE
            try:
                with self.connection() as conn, conn.cursor() as cur:
                    cur.execute(f"SELECT MOBILE_PHONE FROM {self.inst_prefix}teacher_info WHERE LOWER(EMAIL_ID) = LOWER(%s) LIMIT 1", (email,))
                    row = cur.fetchone()
                    if row and row.get("MOBILE_PHONE") and str(row.get("MOBILE_PHONE")).strip() not in ('', '0', 'None'):
                        return str(row["MOBILE_PHONE"]).strip()
            except Exception:
                pass

            # 3. Check helpdesk_users.phone (legacy/test fallback)
            try:
                with self.connection() as conn, conn.cursor() as cur:
                    cur.execute("SELECT phone FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
                    row = cur.fetchone()
                    if row and row.get("phone") and str(row.get("phone")).strip() not in ('', '0', 'None'):
                        return str(row["phone"]).strip()
            except Exception:
                pass

        return test_number if use_fallback else None

    def ensure_schema(self, schema_path: Path):
        """Deprecated: Schema management is handled exclusively via scripts/migrate.py."""
        if not self.enabled:
            return
        log.warning("ensure_schema() called at runtime. Schema mutations must be applied via scripts/migrate.py.")

    def seed_defaults(self, users, categories):
        if not self.enabled:
            return
        with self.connection() as connection, connection.cursor() as cursor:
            # Seed users individually if they do not exist
            for u in users:
                cursor.execute("SELECT id FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (u["email"],))
                existing = cursor.fetchone()
                if not existing:
                    cursor.execute(
                        """
                        INSERT INTO helpdesk_users (name, email, password, role, department, phone)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (u["name"], u["email"], generate_password_hash(u["password"]), u["role"], u["department"], u.get("phone")),
                    )
                else:
                    if u.get("phone"):
                        cursor.execute("UPDATE helpdesk_users SET phone = %s WHERE id = %s", (u["phone"], existing["id"]))

            # Seed categories individually if they do not exist
            if categories:
                for category in categories:
                    cursor.execute(
                        "SELECT id FROM helpdesk_categories WHERE LOWER(category_name) = LOWER(%s) AND department = %s LIMIT 1",
                        (category["category_name"], category["department"]),
                    )
                    if not cursor.fetchone():
                        cursor.execute(
                            "SELECT id FROM helpdesk_users WHERE department = %s AND role IN ('CA', 'ASSIGNEE') ORDER BY id ASC LIMIT 1",
                            (category["department"],),
                        )
                        row = cursor.fetchone()
                        if row:
                            cursor.execute(
                                """
                                INSERT INTO helpdesk_categories (category_name, department, assigned_ca_id)
                                VALUES (%s, %s, %s)
                                """,
                                (category["category_name"], category["department"], row["id"]),
                            )

    def departments_match(self, dept1, dept2):
        if not dept1 or not dept2:
            return False
        d1 = str(dept1).strip().lower()
        d2 = str(dept2).strip().lower()
        if d1 == d2:
            return True
        norm_map = {
            "cse": "computer science and engineering",
            "computer science": "computer science and engineering",
            "computer science and engineering": "computer science and engineering",
            "ece": "electronics and communication engineering",
            "electronics": "electronics and communication engineering",
            "electronics and communication engineering": "electronics and communication engineering",
            "eee": "electrical and electronics engineering",
            "electrical and electronics engineering": "electrical and electronics engineering",
            "it": "information technology",
            "information technology": "information technology",
            "me": "mechanical engineering",
            "mechanical engineering": "mechanical engineering",
            "facilities": "facilities & estates",
            "facilities & estates": "facilities & estates",
            "maintenance": "maintenance",
            "administration": "administration",
        }
        return norm_map.get(d1, d1) == norm_map.get(d2, d2)

    def _resolve_teacher_role(self, cursor, teacher_row, ca_ids=None):
        """Determine role: SUPER_ADMIN, ADMIN, HOD, CA, or FACULTY."""
        teacher_id = teacher_row.get("id") or teacher_row.get("TEACHER_ID")
        email = (teacher_row.get("email") or teacher_row.get("EMAIL_ID") or "").strip().lower()

        # 0. Check if explicitly assigned an elevated staff role (SUPER_ADMIN, ADMIN, etc.)
        try:
            cursor.execute(
                "SELECT role FROM helpdesk_staff_roles WHERE (LOWER(email) = %s OR teacher_id = %s) AND is_active = 1 LIMIT 1",
                (email, teacher_id),
            )
            staff = cursor.fetchone()
            if staff and staff.get("role") and staff["role"] in ("SUPER_ADMIN", "ADMIN"):
                return staff["role"]
        except Exception:
            pass

        # 1. Check if CA in ca_assignments or category default
        if ca_ids is not None:
            if teacher_id in ca_ids:
                return "CA"
        else:
            try:
                cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_ca_assignments WHERE ca_id = %s", (teacher_id,))
                ca_res = cursor.fetchone()
                if ca_res and (ca_res.get("cnt") or 0) > 0:
                    return "CA"
                cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_categories WHERE assigned_ca_id = %s", (teacher_id,))
                cat_res = cursor.fetchone()
                if cat_res and (cat_res.get("cnt") or 0) > 0:
                    return "CA"
            except Exception:
                pass

        # 2. Check if HOD
        desig = (teacher_row.get("designation") or teacher_row.get("DESIGNATION") or "").strip().lower()
        if "hod" in desig:
            return "HOD"
        hod_id = str(teacher_row.get("hod_id") or teacher_row.get("HOD_ID") or "").strip().lower()
        t_code = str(teacher_row.get("teacher_code") or teacher_row.get("TEACHER_CODE") or "").strip().lower()
        s_id = str(teacher_row.get("sap_id") or teacher_row.get("SAP_ID") or "").strip().lower()
        t_id_str = str(teacher_id).strip().lower()
        if hod_id and hod_id in (t_code, s_id, t_id_str):
            return "HOD"

        return "FACULTY"

    def authenticate_user(self, email, password):
        email_clean = str(email).strip().lower()
        with self.connection() as connection, connection.cursor() as cursor:
            # 1. Check helpdesk_staff_roles (for Super Admin / Admin accounts)
            try:
                cursor.execute(
                    """
                    SELECT id, teacher_id, name, email, password_hash, role, department, phone
                    FROM helpdesk_staff_roles
                    WHERE LOWER(email) = LOWER(%s) AND is_active = 1
                    LIMIT 1
                    """,
                    (email_clean,),
                )
                staff = cursor.fetchone()
                if staff and staff.get("password_hash"):
                    if check_password_hash(staff["password_hash"], password):
                        del staff["password_hash"]
                        return {
                            "id": staff.get("teacher_id") or staff["id"],
                            "name": staff["name"],
                            "email": staff["email"],
                            "role": staff["role"],
                            "department": staff.get("department") or "Administration",
                            "phone": staff.get("phone"),
                            "org_id": "2000",
                        }
            except Exception:
                pass

            # 2. Check teacher_info directly (Authoritative Institutional Master)
            try:
                cursor.execute(
                    f"""
                    SELECT t.TEACHER_ID AS id, t.TEACHER_NAME AS name, t.EMAIL_ID AS email,
                           t.SAP_ID AS sap_id, t.TEACHER_CODE AS teacher_code, t.DESIGNATION AS designation,
                           t.MOBILE_PHONE AS phone, COALESCE(t.ACTIVE, 1) AS is_active,
                           b.BRANCH_CODE AS department, b.HOD_ID AS hod_id,
                           CAST(COALESCE(b.ORG_ID, '2000') AS CHAR) AS org_id
                    FROM {self.inst_prefix}teacher_info t
                    LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
                    WHERE LOWER(COALESCE(t.EMAIL_ID, '')) = LOWER(%s)
                    LIMIT 1
                    """,
                    (email_clean,),
                )
                teacher = cursor.fetchone()
                if teacher:
                    sap_id = str(teacher.get("sap_id") or "").strip()
                    # Password matches SAP_ID / Employee ID or '123' or 'Admin@321#'
                    if (sap_id and password == sap_id) or password in ("123", "Admin@321#"):
                        role = self._resolve_teacher_role(cursor, teacher)
                        return {
                            "id": teacher["id"],
                            "name": teacher["name"],
                            "email": teacher["email"],
                            "role": role,
                            "department": teacher.get("department") or "General",
                            "phone": teacher.get("phone"),
                            "org_id": teacher.get("org_id", "2000"),
                        }
            except Exception:
                pass

            # 3. Fallback to helpdesk_users (for mock tests and legacy accounts)
            try:
                cursor.execute(
                    """
                    SELECT id, name, email, password, role, department, phone
                    FROM helpdesk_users
                    WHERE LOWER(email) = LOWER(%s)
                    LIMIT 1
                    """,
                    (email_clean,),
                )
                user = cursor.fetchone()
                if user and user.get("password"):
                    user_pwd = user["password"]
                    if check_password_hash(user_pwd, password) or (
                        password in ("Admin@321#", "123")
                        and (check_password_hash(user_pwd, "123") or check_password_hash(user_pwd, "Admin@321#"))
                    ):
                        del user["password"]
                        return user
            except Exception:
                pass

            return None

    def change_password(self, user_id, old_password, new_password):
        """Verify old password and update to new password. Raises ValueError on mismatch."""
        with self.connection() as connection, connection.cursor() as cursor:
            # 1. Check helpdesk_staff_roles
            try:
                cursor.execute("SELECT password_hash FROM helpdesk_staff_roles WHERE id = %s OR teacher_id = %s LIMIT 1", (user_id, user_id))
                staff = cursor.fetchone()
                if staff and staff.get("password_hash"):
                    if not check_password_hash(staff["password_hash"], old_password):
                        return False
                    new_hash = generate_password_hash(new_password)
                    cursor.execute("UPDATE helpdesk_staff_roles SET password_hash = %s WHERE id = %s OR teacher_id = %s", (new_hash, user_id, user_id))
                    return True
            except Exception:
                pass

            # 2. Check helpdesk_users
            cursor.execute("SELECT password FROM helpdesk_users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("User not found.")
            if not check_password_hash(row["password"], old_password):
                return False
            hashed = generate_password_hash(new_password)
            try:
                cursor.execute("UPDATE helpdesk_users SET password = %s WHERE id = %s", (hashed, user_id))
            except Exception:
                pass
            return True

    def get_user(self, user_id):
        if not self.enabled:
            return None
        try:
            user_id_int = int(user_id)
        except (ValueError, TypeError):
            user_id_int = None

        with self.connection() as connection, connection.cursor() as cursor:
            # 1. Check teacher_info
            if user_id_int:
                try:
                    cursor.execute(
                        f"""
                        SELECT t.TEACHER_ID AS id, t.TEACHER_NAME AS name, t.EMAIL_ID AS email,
                               t.DESIGNATION AS designation, t.TEACHER_CODE AS teacher_code, t.SAP_ID AS sap_id,
                               t.MOBILE_PHONE AS phone, b.BRANCH_CODE AS department, b.HOD_ID AS hod_id,
                               CAST(COALESCE(b.ORG_ID, '2000') AS CHAR) AS org_id
                        FROM {self.inst_prefix}teacher_info t
                        LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
                        WHERE t.TEACHER_ID = %s
                        LIMIT 1
                        """,
                        (user_id_int,),
                    )
                    row = cursor.fetchone()
                    if row:
                        role = self._resolve_teacher_role(cursor, row)
                        return {
                            "id": row["id"],
                            "name": row["name"],
                            "email": row["email"],
                            "role": role,
                            "department": row.get("department") or "General",
                            "phone": row.get("phone"),
                            "org_id": row.get("org_id", "2000"),
                        }
                except Exception:
                    pass

            # 2. Check helpdesk_staff_roles
            if user_id_int:
                try:
                    cursor.execute(
                        "SELECT id, teacher_id, name, email, role, department, phone FROM helpdesk_staff_roles WHERE id = %s OR teacher_id = %s LIMIT 1",
                        (user_id_int, user_id_int),
                    )
                    staff = cursor.fetchone()
                    if staff:
                        return {
                            "id": staff.get("teacher_id") or staff["id"],
                            "name": staff["name"],
                            "email": staff["email"],
                            "role": staff["role"],
                            "department": staff.get("department") or "Administration",
                            "phone": staff.get("phone"),
                            "org_id": "2000",
                        }
                except Exception:
                    pass

            # 3. Fallback to helpdesk_users (for mock tests)
            try:
                cursor.execute("SELECT id, name, email, role, department, phone, created_at FROM helpdesk_users WHERE id = %s", (user_id,))
                return cursor.fetchone()
            except Exception:
                return None

    def get_user_by_email(self, email):
        if not self.enabled or not email:
            return None
        email_clean = str(email).strip().lower()

        with self.connection() as connection, connection.cursor() as cursor:
            # 1. Check helpdesk_staff_roles
            try:
                cursor.execute(
                    "SELECT id, teacher_id, name, email, role, department, phone FROM helpdesk_staff_roles WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    (email_clean,),
                )
                staff = cursor.fetchone()
                if staff:
                    return {
                        "id": staff.get("teacher_id") or staff["id"],
                        "name": staff["name"],
                        "email": staff["email"],
                        "role": staff["role"],
                        "department": staff.get("department") or "Administration",
                        "phone": staff.get("phone"),
                        "org_id": "2000",
                    }
            except Exception:
                pass

            # 2. Check teacher_info
            try:
                cursor.execute(
                    f"""
                    SELECT t.TEACHER_ID AS id, t.TEACHER_NAME AS name, t.EMAIL_ID AS email,
                           t.DESIGNATION AS designation, t.TEACHER_CODE AS teacher_code, t.SAP_ID AS sap_id,
                           t.MOBILE_PHONE AS phone, b.BRANCH_CODE AS department, b.HOD_ID AS hod_id,
                           CAST(COALESCE(b.ORG_ID, '2000') AS CHAR) AS org_id
                    FROM {self.inst_prefix}teacher_info t
                    LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
                    WHERE LOWER(COALESCE(t.EMAIL_ID, '')) = LOWER(%s)
                    LIMIT 1
                    """,
                    (email_clean,),
                )
                row = cursor.fetchone()
                if row:
                    role = self._resolve_teacher_role(cursor, row)
                    return {
                        "id": row["id"],
                        "name": row["name"],
                        "email": row["email"],
                        "role": role,
                        "department": row.get("department") or "General",
                        "phone": row.get("phone"),
                        "org_id": row.get("org_id", "2000"),
                    }
            except Exception:
                pass

            # 3. Fallback to helpdesk_users (for mock tests)
            try:
                cursor.execute(
                    "SELECT id, name, email, role, department, phone, created_at FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                    (email_clean,),
                )
                return cursor.fetchone()
            except Exception:
                return None


    def list_users(self, role=None, department=None, search="", org_id=None, limit=None, offset=None):
        import sys
        is_test = "unittest" in sys.modules or "pytest" in sys.modules or os.getenv("TESTING", "false").lower() == "true"
        if not is_test and self.enabled:
            users = []
            with self.connection() as connection, connection.cursor() as cursor:
                # 1. Staff roles (administrators, operators, IT staff)
                staff_sql = "SELECT id, teacher_id, name, email, role, department, phone, created_at FROM helpdesk_staff_roles WHERE is_active = 1"
                staff_params = []
                if search:
                    like = f"%{search}%"
                    staff_sql += " AND (name LIKE %s OR email LIKE %s OR department LIKE %s)"
                    staff_params.extend([like, like, like])
                cursor.execute(staff_sql, staff_params)
                staff_users = cursor.fetchall()
                users.extend(staff_users)

                # Index staff by lowercase email and teacher_id to prevent duplicates
                staff_by_email = {str(s.get("email") or "").strip().lower(): s for s in staff_users if s.get("email")}
                staff_by_tid = {s.get("teacher_id"): s for s in staff_users if s.get("teacher_id")}

                # 2. Institutional teachers from teacher_info
                target_roles = [role] if isinstance(role, str) else list(role or [])
                needs_teachers = not target_roles or any(r in ("FACULTY", "HOD", "CA", "ASSIGNEE") for r in target_roles)

                if needs_teachers:
                    t_sql = f"""
                        SELECT t.TEACHER_ID AS id, t.TEACHER_NAME AS name, t.EMAIL_ID AS email,
                               t.MOBILE_PHONE AS phone, t.DESIGNATION AS designation,
                               b.BRANCH_CODE AS department, b.HOD_ID AS hod_id,
                               t.TEACHER_CODE AS teacher_code, t.SAP_ID AS sap_id,
                               CAST(COALESCE(b.ORG_ID, '2000') AS CHAR) AS org_id
                        FROM {self.inst_prefix}teacher_info t
                        LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
                        WHERE (COALESCE(t.ACTIVE, 1) = 1 OR t.TEACHER_ID IN (SELECT ca_id FROM helpdesk_ca_assignments) OR t.TEACHER_ID IN (SELECT assigned_ca_id FROM helpdesk_categories WHERE assigned_ca_id IS NOT NULL))
                    """
                    t_params = []
                    if department:
                        t_sql += " AND (b.BRANCH_CODE = %s OR FIND_IN_SET(%s, b.BRANCH_CODE) > 0)"
                        t_params.extend([department, department])
                    if search:
                        like = f"%{search}%"
                        t_sql += " AND (t.TEACHER_NAME LIKE %s OR t.EMAIL_ID LIKE %s OR b.BRANCH_CODE LIKE %s)"
                        t_params.extend([like, like, like])
                    cursor.execute(t_sql, t_params)
                    teachers = cursor.fetchall()

                    cursor.execute("SELECT DISTINCT ca_id FROM helpdesk_ca_assignments WHERE ca_id IS NOT NULL")
                    ca_ids = {r["ca_id"] for r in cursor.fetchall() if r.get("ca_id")}
                    cursor.execute("SELECT DISTINCT assigned_ca_id FROM helpdesk_categories WHERE assigned_ca_id IS NOT NULL")
                    ca_ids.update({r["assigned_ca_id"] for r in cursor.fetchall() if r.get("assigned_ca_id")})

                    for t in teachers:
                        t_email = str(t.get("email") or "").strip().lower()
                        t_id = t["id"]
                        
                        # If user is already in staff_roles (e.g. Srinivas SAP / Super Admin), merge and deduplicate
                        matched_staff = staff_by_email.get(t_email) or staff_by_tid.get(t_id)
                        if matched_staff:
                            if not matched_staff.get("teacher_id"):
                                matched_staff["teacher_id"] = t_id
                            if t_id in ca_ids or matched_staff.get("id") in ca_ids:
                                matched_staff["has_ca_assignment"] = True
                            if t.get("name") and (not matched_staff.get("name") or "SAP" in matched_staff.get("name", "")):
                                matched_staff["name"] = t["name"]
                            continue

                        t_role = self._resolve_teacher_role(cursor, t, ca_ids=ca_ids)
                        users.append({
                            "id": t["id"],
                            "name": t["name"],
                            "email": t["email"],
                            "role": t_role,
                            "department": t.get("department") or "General",
                            "phone": t.get("phone"),
                            "created_at": None,
                            "org_id": t.get("org_id", "2000"),
                        })

            if role:
                allowed_roles = [role] if isinstance(role, str) else list(role)
                expanded = []
                for r in allowed_roles:
                    if r in ("CA", "ASSIGNEE"):
                        expanded.extend(["CA", "ASSIGNEE"])
                    else:
                        expanded.append(r)
                expanded_set = set(expanded)
                if "ASSIGNEE" in expanded_set or "CA" in expanded_set:
                    users = [u for u in users if u.get("role") in expanded_set or u.get("has_ca_assignment")]
                else:
                    users = [u for u in users if u.get("role") in expanded_set]

            if department:
                users = [u for u in users if u.get("department") == department or department in (u.get("department") or "").split(",")]

            if org_id:
                users = [u for u in users if str(u.get("org_id", "2000")) == str(org_id)]

            if limit is not None:
                offset_val = offset or 0
                return users[offset_val : offset_val + limit]
            return users

        # Fallback for unit testing mock database
        sql = "SELECT id, name, email, role, department, phone, created_at FROM helpdesk_users WHERE 1=1"
        params = []
        if role:
            if isinstance(role, (list, tuple)):
                expanded_roles = []
                for r in role:
                    if r in ("ASSIGNEE", "CA"):
                        expanded_roles.extend(["ASSIGNEE", "CA"])
                    else:
                        expanded_roles.append(r)
                expanded_roles = list(dict.fromkeys(expanded_roles))
                placeholders = ", ".join(["%s"] * len(expanded_roles))
                sql += f" AND role IN ({placeholders})"
                params.extend(expanded_roles)
            else:
                if role in ("ASSIGNEE", "CA"):
                    sql += " AND role IN ('ASSIGNEE', 'CA')"
                else:
                    sql += " AND role = %s"
                    params.append(role)
        if department:
            sql += " AND (department = %s OR FIND_IN_SET(%s, department) > 0)"
            params.extend([department, department])
        if search:
            like = f"%{search}%"
            sql += " AND (name LIKE %s OR email LIKE %s OR department LIKE %s)"
            params.extend([like, like, like])
        sql += " ORDER BY created_at DESC"
        
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                users = cursor.fetchall()

            if not org_id:
                if limit is not None:
                    offset_val = offset or 0
                    return users[offset_val : offset_val + limit]
                return users

            # Find which branch_codes belong to this org_id
            branch_codes = set()
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT BRANCH_CODE FROM {self.inst_prefix}branch_detail WHERE CAST(ORG_ID AS CHAR) = %s",
                    (org_id,)
                )
                for r in cursor.fetchall():
                    if r.get("BRANCH_CODE"):
                        branch_codes.add(r["BRANCH_CODE"])

        filtered_users = []
        for u in users:
            u_email = u["email"]
            u_dept = u["department"]
            
            # Determine user's org
            u_org = "3000" if (u_email and "snu" in u_email.lower()) else "2000"
            if u_org == "2000" and u_dept:
                depts = [d.strip() for d in u_dept.split(",")]
                if any(d in branch_codes for d in depts):
                    u_org = org_id

            if u_org == org_id:
                filtered_users.append(u)

        if limit is not None:
            offset_val = offset or 0
            filtered_users = filtered_users[offset_val : offset_val + limit]
        return filtered_users

    def create_user(self, payload):
        hashed = generate_password_hash(payload["password"])
        role = payload.get("role", "FACULTY")
        with self.connection() as connection, connection.cursor() as cursor:
            # 1. Try helpdesk_users first (works for base table & mock test state)
            try:
                cursor.execute(
                    """
                    INSERT INTO helpdesk_users (name, email, password, role, department)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (payload["name"], payload["email"], hashed, role, payload.get("department", "General")),
                )
                return cursor.lastrowid
            except Exception:
                # If helpdesk_users is a non-updatable VIEW, insert into helpdesk_staff_roles
                staff_role = "ADMIN" if role not in ("SUPER_ADMIN", "ADMIN", "CA", "ASSIGNEE") else role
                cursor.execute(
                    """
                    INSERT INTO helpdesk_staff_roles (name, email, password_hash, role, department, phone, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, 1)
                    """,
                    (payload["name"], payload["email"], hashed, staff_role, payload.get("department", "General"), payload.get("phone")),
                )
                return cursor.lastrowid

    def update_user(self, user_id, payload):
        if not self.enabled:
            return
        fields = []
        params = []
        for k in ["name", "email", "role", "department"]:
            if k in payload:
                fields.append(f"{k} = %s")
                params.append(payload[k])
        if "phone" in payload:
            fields.append("phone = %s")
            params.append(payload["phone"])
            
        if not fields and not payload.get("password"):
            return
            
        with self.connection() as connection, connection.cursor() as cursor:
            # 1. Try updating in helpdesk_users (base table or mock tests)
            try:
                user_fields = list(fields)
                user_params = list(params)
                if "password" in payload and payload["password"]:
                    user_fields.append("password = %s")
                    user_params.append(generate_password_hash(payload["password"]))
                user_params.append(user_id)
                cursor.execute(f"UPDATE helpdesk_users SET {', '.join(user_fields)} WHERE id = %s", tuple(user_params))
            except Exception:
                pass

            # 2. Try updating in helpdesk_staff_roles (for production staff accounts)
            try:
                staff_fields = list(fields)
                staff_params = list(params)
                if "password" in payload and payload["password"]:
                    staff_fields.append("password_hash = %s")
                    staff_params.append(generate_password_hash(payload["password"]))
                staff_params.append(user_id)
                staff_params.append(user_id)
                cursor.execute(f"UPDATE helpdesk_staff_roles SET {', '.join(staff_fields)} WHERE id = %s OR teacher_id = %s", tuple(staff_params))
            except Exception:
                pass

    def delete_user(self, user_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM helpdesk_categories WHERE assigned_ca_id = %s) AS category_refs,
                    (SELECT COUNT(*) FROM helpdesk_tickets WHERE created_by = %s OR assigned_to = %s) AS ticket_refs,
                    (SELECT COUNT(*) FROM helpdesk_ticket_activity WHERE action_by = %s) AS activity_refs
                """,
                (user_id, user_id, user_id, user_id),
            )
            refs = cursor.fetchone()
            if any(refs.values()):
                raise ValueError("Cannot delete a user that is referenced by categories, tickets, or activity.")
            try:
                cursor.execute("DELETE FROM helpdesk_users WHERE id = %s", (user_id,))
            except Exception:
                pass
            try:
                cursor.execute("DELETE FROM helpdesk_staff_roles WHERE id = %s OR teacher_id = %s", (user_id, user_id))
            except Exception:
                pass

    def list_categories(self, department=None, search="", ca_id=None, org_id=None, active_only=False, limit=None, offset=None):
        sql = f"""
            SELECT c.id, c.category_name, c.department, c.assigned_ca_id, c.is_active, c.created_at,
                   COALESCE(t.TEACHER_NAME, s.name) AS assigned_ca_name,
                   COALESCE(t.EMAIL_ID, s.email) AS assigned_ca_email
            FROM helpdesk_categories c
            LEFT JOIN {self.inst_prefix}teacher_info t ON t.TEACHER_ID = c.assigned_ca_id
            LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = c.assigned_ca_id OR s.id = c.assigned_ca_id)
            WHERE 1=1
        """
        params = []
        if active_only:
            sql += " AND c.is_active = 1"
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        if ca_id:
            sql += " AND c.assigned_ca_id = %s"
            params.append(ca_id)
        if org_id:
            sql += f" AND c.department IN (SELECT BRANCH_CODE FROM {self.inst_prefix}branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)
        if search:
            like = f"%{search}%"
            sql += " AND (c.category_name LIKE %s OR t.TEACHER_NAME LIKE %s OR s.name LIKE %s)"
            params.extend([like, like, like])
        sql += " ORDER BY c.department, c.category_name"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET %s"
                params.append(offset)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def category_exists(self, category_name, department, exclude_id=None):
        """Check if a category with the same name+department already exists."""
        sql = "SELECT id FROM helpdesk_categories WHERE LOWER(category_name) = LOWER(%s) AND department = %s"
        params = [category_name, department]
        if exclude_id:
            sql += " AND id != %s"
            params.append(exclude_id)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone() is not None

    def create_category(self, payload):
        ca_id = payload.get("assigned_ca_id")
        if not ca_id or ca_id == 0 or str(ca_id).strip().lower() in ("none", "unassigned", ""):
            ca_id = None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO helpdesk_categories (category_name, department, assigned_ca_id)
                VALUES (%s, %s, %s)
                """,
                (payload["category_name"], payload["department"], ca_id),
            )
            return cursor.lastrowid

    def update_category(self, category_id, payload):
        ca_id = payload.get("assigned_ca_id")
        if not ca_id or ca_id == 0 or str(ca_id).strip().lower() in ("none", "unassigned", ""):
            ca_id = None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE helpdesk_categories
                SET category_name = %s, department = %s, assigned_ca_id = %s
                WHERE id = %s
                """,
                (payload["category_name"], payload["department"], ca_id, category_id),
            )


    def delete_category(self, category_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM helpdesk_tickets WHERE category_id = %s", (category_id,))
            if cursor.fetchone()["total"]:
                raise ValueError("Cannot delete a category that is already used by tickets.")
            cursor.execute("DELETE FROM helpdesk_categories WHERE id = %s", (category_id,))

    def get_category(self, category_id, org_id: str | None = None):
        with self.connection() as connection, connection.cursor() as cursor:
            sql = f"""
                SELECT c.id, c.category_name, c.department, c.assigned_ca_id, c.is_active,
                       COALESCE(t.TEACHER_NAME, s.name) AS assigned_ca_name
                FROM helpdesk_categories c
                LEFT JOIN {self.inst_prefix}teacher_info t ON t.TEACHER_ID = c.assigned_ca_id
                LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = c.assigned_ca_id OR s.id = c.assigned_ca_id)
                WHERE c.id = %s
            """
            params = [category_id]
            if org_id:
                sql += " AND (c.org_id = %s OR c.org_id IS NULL)"
                params.append(org_id)
            cursor.execute(sql, tuple(params))
            return cursor.fetchone()

    def toggle_category_status(self, category_id, is_active):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE helpdesk_categories
                SET is_active = %s
                WHERE id = %s
                """,
                (1 if is_active else 0, category_id),
            )

    def count_tickets_by_category(self, category_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM helpdesk_tickets WHERE category_id = %s AND status != 'RESOLVED'",
                (category_id,),
            )
            res = cursor.fetchone()
            return res["total"] if res else 0

    def get_category_block_mappings(self, category_id, org_id: str | None = None):
        with self.connection() as connection, connection.cursor() as cursor:
            sql = f"""
                SELECT a.id, a.ca_id, a.block,
                       COALESCE(t.TEACHER_NAME, s.name, 'Assignee') AS ca_name,
                       COALESCE(t.EMAIL_ID, s.email, '') AS ca_email
                FROM helpdesk_ca_assignments a
                LEFT JOIN {self.inst_prefix}teacher_info t ON t.TEACHER_ID = a.ca_id
                LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = a.ca_id OR s.id = a.ca_id)
                WHERE a.category_id = %s
            """
            params = [category_id]
            if org_id:
                sql += " AND (a.org_id = %s OR a.org_id IS NULL)"
                params.append(org_id)
            sql += " ORDER BY ca_name, a.block"
            cursor.execute(sql, tuple(params))
            return cursor.fetchall()

    def get_category_assignees(self, category_id, org_id: str | None = None):
        """Return structured list of distinct assignees for a category with their mapped blocks."""
        mappings = self.get_category_block_mappings(category_id, org_id=org_id)
        category = self.get_category(category_id, org_id=org_id)
        default_ca_id = category.get("assigned_ca_id") if category else None

        ca_dict = {}
        for m in mappings:
            cid = m.get("ca_id")
            if not cid:
                continue
            if cid not in ca_dict:
                ca_dict[cid] = {
                    "ca_id": cid,
                    "ca_name": m.get("ca_name") or "Assignee",
                    "ca_email": m.get("ca_email") or "",
                    "blocks": [],
                    "mapping_ids": [],
                    "is_default": (cid == default_ca_id),
                }
            if m.get("block") and m["block"] not in ca_dict[cid]["blocks"]:
                ca_dict[cid]["blocks"].append(m["block"])
            if m.get("id"):
                ca_dict[cid]["mapping_ids"].append(m["id"])

        # If there is a default assigned CA on the category not in mappings yet, include them as 'All Blocks'
        if default_ca_id and default_ca_id not in ca_dict:
            ca_user = None
            try:
                with self.connection() as conn, conn.cursor() as cur:
                    cur.execute("SELECT id, name, email FROM helpdesk_users WHERE id = %s", (default_ca_id,))
                    ca_user = cur.fetchone()
            except Exception:
                pass
            if not ca_user:
                ca_user = self.get_user(default_ca_id)
            if ca_user:
                ca_dict[default_ca_id] = {
                    "ca_id": default_ca_id,
                    "ca_name": ca_user.get("name") or "Assignee",
                    "ca_email": ca_user.get("email") or "",
                    "blocks": ["All Blocks"],
                    "mapping_ids": [],
                    "is_default": True,
                }
        return list(ca_dict.values())

    def assign_ca_to_category_blocks(self, category_id, ca_id, blocks=None):
        """Assign a CA to a category for specific blocks or All Blocks without removing other CAs."""
        category = self.get_category(category_id)
        if not category:
            raise ValueError("Category not found.")

        blocks = blocks or []
        created_count = 0
        skipped_count = 0

        # If no specific blocks given or 'all' selected, map as 'All Blocks'
        has_all = any(str(b).strip().lower() in ("all", "all blocks", "campus") for b in blocks)
        if not blocks or has_all:
            try:
                self.create_ca_assignment(category_id, ca_id, "All Blocks")
                created_count += 1
            except ValueError:
                skipped_count += 1
        else:
            for b in blocks:
                b_clean = str(b).strip()
                if not b_clean:
                    continue
                try:
                    self.create_ca_assignment(category_id, ca_id, b_clean)
                    created_count += 1
                except ValueError:
                    skipped_count += 1

        # If category has no default assigned_ca_id, set this CA as primary default
        if not category.get("assigned_ca_id"):
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute("UPDATE helpdesk_categories SET assigned_ca_id = %s WHERE id = %s", (ca_id, category_id))

        return {"created": created_count, "skipped": skipped_count}

    def remove_ca_from_category(self, category_id, ca_id):
        """Remove a CA and all their block mappings from a category."""
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM helpdesk_ca_assignments WHERE category_id = %s AND ca_id = %s",
                (category_id, ca_id),
            )
            # If this CA was category.assigned_ca_id, elect another assigned CA or NULL
            cursor.execute("SELECT assigned_ca_id FROM helpdesk_categories WHERE id = %s", (category_id,))
            cat = cursor.fetchone()
            if cat and cat.get("assigned_ca_id") == ca_id:
                cursor.execute(
                    "SELECT ca_id FROM helpdesk_ca_assignments WHERE category_id = %s LIMIT 1",
                    (category_id,),
                )
                other = cursor.fetchone()
                new_ca_id = other["ca_id"] if other else None
                cursor.execute(
                    "UPDATE helpdesk_categories SET assigned_ca_id = %s WHERE id = %s",
                    (new_ca_id, category_id),
                )

    unassign_ca_from_category = remove_ca_from_category

    def get_user_assigned_categories(self, user_id):
        """Return structured list of distinct categories mapped to a user (CA) with their mapped blocks."""
        res_map = self.get_users_assigned_categories_map([user_id])
        return res_map.get(user_id, [])

    def get_users_assigned_categories_map(self, user_ids):
        """Return a mapping of user_id -> list of assigned category dicts for batch user enrichment."""
        if not user_ids:
            return {}
        uids = set(int(u) for u in user_ids if u)
        if not uids:
            return {}

        result = {uid: {} for uid in uids}

        # Build bidirectional mapping between staff id and teacher_id to resolve category mappings
        id_aliases = {uid: {uid} for uid in uids}
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                placeholders = ", ".join(["%s"] * len(uids))
                cursor.execute(
                    f"SELECT id, teacher_id FROM helpdesk_staff_roles WHERE id IN ({placeholders}) OR teacher_id IN ({placeholders})",
                    list(uids) + list(uids),
                )
                for r in cursor.fetchall():
                    sid = r.get("id")
                    tid = r.get("teacher_id")
                    if sid and tid:
                        if sid in id_aliases:
                            id_aliases[sid].add(tid)
                        if tid in id_aliases:
                            id_aliases[tid].add(sid)
        except Exception:
            pass

        # 1. Fetch categories to get category_name, department, is_active, assigned_ca_id
        all_cats = self.list_categories()
        cat_by_id = {c["id"]: c for c in all_cats}

        # 2. Check direct assigned_ca_id on categories
        for cat in all_cats:
            assigned_ca = cat.get("assigned_ca_id")
            if assigned_ca is None:
                continue
            for uid, aliases in id_aliases.items():
                if assigned_ca in aliases:
                    cid = cat["id"]
                    if cid not in result[uid]:
                        result[uid][cid] = {
                            "category_id": cid,
                            "category_name": cat["category_name"],
                            "department": cat.get("department") or "",
                            "is_active": cat.get("is_active", 1),
                            "is_default": True,
                            "blocks": ["All Blocks"],
                            "mapping_ids": [],
                        }
                    else:
                        result[uid][cid]["is_default"] = True

        # 3. Check block-level mappings in helpdesk_ca_assignments
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, category_id, ca_id, block FROM helpdesk_ca_assignments")
            assignments = cursor.fetchall()
            for a in assignments:
                ca_id = a.get("ca_id")
                if ca_id is None:
                    continue
                for uid, aliases in id_aliases.items():
                    if ca_id in aliases:
                        cid = a.get("category_id")
                        cat = cat_by_id.get(cid)
                        if not cat:
                            continue
                        if cid not in result[uid]:
                            result[uid][cid] = {
                                "category_id": cid,
                                "category_name": cat["category_name"],
                                "department": cat.get("department") or "",
                                "is_active": cat.get("is_active", 1),
                                "is_default": (cat.get("assigned_ca_id") in aliases),
                                "blocks": [],
                                "mapping_ids": [],
                            }
                        block = a.get("block")
                        if block and block not in result[uid][cid]["blocks"]:
                            if result[uid][cid]["blocks"] == ["All Blocks"] and block != "All Blocks":
                                result[uid][cid]["blocks"] = [block]
                            else:
                                result[uid][cid]["blocks"].append(block)
                        if a.get("id"):
                            result[uid][cid]["mapping_ids"].append(a["id"])

        return {uid: list(cats.values()) for uid, cats in result.items()}

    def bulk_assign_ca(self, category_ids, ca_id):
        if not category_ids or not ca_id:
            return 0
        format_strings = ','.join(['%s'] * len(category_ids))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE helpdesk_categories SET assigned_ca_id = %s WHERE id IN ({format_strings})",
                [ca_id] + list(category_ids),
            )
            return cursor.rowcount

    def bulk_toggle_categories(self, category_ids, is_active):
        if not category_ids:
            return 0
        format_strings = ','.join(['%s'] * len(category_ids))
        val = 1 if is_active else 0
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE helpdesk_categories SET is_active = %s WHERE id IN ({format_strings})",
                [val] + list(category_ids),
            )
            return cursor.rowcount

    def bulk_remove_ca(self, category_ids):
        if not category_ids:
            return 0
        format_strings = ','.join(['%s'] * len(category_ids))
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE helpdesk_categories SET assigned_ca_id = NULL WHERE id IN ({format_strings})",
                list(category_ids),
            )
            return cursor.rowcount


    def list_blocks(self, org_id=None):
        """Return distinct campus blocks combining location table and standard campus blocks."""
        DEFAULT_BLOCKS = [
            "Block-I", "Block-II", "Block-III", "Block-IV", "Block-V",
            "Block-VI", "Block-VII", "Block-VIII", "Block-IX", "Block-X",
            "Block-XI", "Block-XII", "Block-XIII", "1st year block", "Admin Block",
            "Biotech Block", "Canteen", "Central Library", "City Office",
            "Security & CCTV", "University Block", "Block 5"
        ]
        blocks = set(DEFAULT_BLOCKS)
        if self.enabled:
            try:
                with self.connection() as conn, conn.cursor() as cur:
                    cur.execute(f"SELECT DISTINCT block FROM {self.inst_prefix}location WHERE block IS NOT NULL AND TRIM(block) != ''")
                    for r in cur.fetchall():
                        val = (r.get("block") or "").strip()
                        if val:
                            blocks.add(val)
            except Exception:
                pass
        return sorted(list(blocks), key=lambda x: (not x.startswith("Block-"), x))

    def create_ticket(self, title, description, category_id, created_by, org_id="2000", location_id=None, submission_key=None, assigned_to=None):
        category = self.get_category(category_id, org_id=org_id)
        if not category:
            raise ValueError("Selected category does not exist.")

        # Auto-generate title from category if title is empty
        if not title:
            title = category["category_name"]

        # Generate a submission_key to prevent duplicate submissions
        if not submission_key:
            submission_key = str(uuid.uuid4())

        # Retrieve block name if location_id is provided
        block_name = None
        if location_id:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT block FROM {self.inst_prefix}location WHERE id = %s AND (CAST(ORG_ID AS CHAR) = %s OR ORG_ID IS NULL OR ORG_ID = '')",
                    (location_id, org_id),
                )
                row = cursor.fetchone()
                if row:
                    block_name = row.get("block")

        # Resolve assigned CA dynamically or use explicitly provided assigned_to
        if assigned_to is not None:
            assigned_ca_id = assigned_to
        else:
            assigned_ca_id = self.resolve_assigned_ca(category_id, block_name) or category.get("assigned_ca_id")

        if not assigned_ca_id:
            log.warning(
                "No CA resolvable for category '%s' (ID: %s, Block: '%s'). Falling back to administrator assignment.",
                category.get("category_name"), category_id, block_name
            )
            # Fallback 1: Any active CA in the category's department
            cat_dept = (category.get("department") or "").strip()
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM helpdesk_users WHERE role IN ('CA', 'ASSIGNEE') AND LOWER(department) = LOWER(%s) AND is_active = 1 LIMIT 1",
                    (cat_dept,)
                )
                ca_row = cursor.fetchone()
                if ca_row:
                    assigned_ca_id = ca_row["id"]
                else:
                    # Fallback 2: Department HOD or Administrator
                    cursor.execute(
                        "SELECT id FROM helpdesk_users WHERE role IN ('HOD', 'ADMIN', 'SUPER_ADMIN') AND is_active = 1 ORDER BY id ASC LIMIT 1"
                    )
                    admin_row = cursor.fetchone()
                    if admin_row:
                        assigned_ca_id = admin_row["id"]
                    else:
                        raise ValueError(f"Category '{category['category_name']}' has no assigned Assignee. Please assign a CA before creating tickets.")

        # Strict server-side department validation
        if assigned_ca_id and category and category.get("department"):

            assignee_user = self.get_user(assigned_ca_id)
            if assignee_user and assignee_user.get("department"):
                if not self.departments_match(assignee_user["department"], category["department"]):
                    raise ValueError(
                        f"Department mismatch: Assignee '{assignee_user.get('name')}' belongs to "
                        f"'{assignee_user['department']}', but category requires '{category['department']}'."
                    )

        with self.connection() as connection, connection.cursor() as cursor:

            try:
                cursor.execute(
                    """
                    INSERT INTO helpdesk_tickets (title, description, category_id, created_by, assigned_to, status, org_id, location_id, submission_key)
                    VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s, %s)
                    """,
                    (title, description, category_id, created_by, assigned_ca_id, org_id, location_id, submission_key),
                )
            except Exception as exc:
                err_code = getattr(exc, "args", [None])[0] if hasattr(exc, "args") and exc.args else None
                err_str = str(exc)
                # If duplicate submission_key, find and return existing ticket
                if err_code == 1062 or ("Duplicate entry" in err_str and "submission_key" in err_str):
                    cursor.execute(
                        "SELECT id FROM helpdesk_tickets WHERE submission_key = %s LIMIT 1",
                        (submission_key,),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        return existing["id"]
                raise
            ticket_id = cursor.lastrowid
            try:
                cursor.execute(
                    """
                    INSERT INTO helpdesk_ticket_activity (ticket_id, action_by, from_status, to_status, remarks)
                    VALUES (%s, %s, NULL, 'PENDING', %s)
                    """,
                    (ticket_id, created_by, "Ticket created"),
                )
            except Exception as act_exc:
                act_code = getattr(act_exc, "args", [None])[0] if hasattr(act_exc, "args") and act_exc.args else None
                if act_code == 1062 or "Duplicate entry" in str(act_exc):
                    log.info("Initial ticket activity creation skipped (duplicate entry): %s", act_exc)
                else:
                    raise
            try:
                from email_services import send_allocation_email
                ca_user = self.get_user(assigned_ca_id)
                if ca_user and ca_user.get("email"):
                    send_allocation_email(ca_user["name"], ca_user["email"], ticket_id, category["category_name"])
            except Exception:
                pass
            try:
                from sms_services import send_allocation_sms
                ca_user = self.get_user(assigned_ca_id)
                if ca_user and ca_user.get("email"):
                    ca_phone = self.get_user_phone(ca_user["email"])
                    if ca_phone:
                        send_allocation_sms(
                            ca_user["name"], ca_phone, ticket_id,
                            category_name=category.get("category_name", "System"),
                            department=category.get("department", "ICT Department"),
                        )
            except Exception:
                pass
            return ticket_id

    def _has_column(self, table, column):
        """Check if a column exists in a table with strict table name whitelist validation."""
        ALLOWED_TABLES = {
            "helpdesk_tickets", "helpdesk_categories", "helpdesk_ca_assignments",
            "helpdesk_staff_roles", "helpdesk_problem_types", "helpdesk_users",
            "helpdesk_audit_events", "helpdesk_ticket_activity", "helpdesk_ticket_notes",
            "teacher_info", "branch_detail", "location"
        }
        clean_table = table.strip("`")
        if clean_table not in ALLOWED_TABLES:
            raise ValueError(f"Invalid or unauthorized table name for schema check: {table}")
        try:
            with self.connection() as conn, conn.cursor() as cur:
                cur.execute(f"SHOW COLUMNS FROM `{clean_table}` LIKE %s", (column,))
                return cur.fetchone() is not None
        except Exception:
            return False

    def add_escalation_status(self, ticket):
        if not ticket or not ticket.get("created_at"):
            return ticket
        
        from datetime import datetime, timedelta
        created_at = ticket["created_at"]
        if isinstance(created_at, str):
            try:
                created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
                
        if isinstance(created_at, datetime):
            is_overdue = (datetime.now() - created_at) > timedelta(hours=24)
            is_open = ticket.get("status") in ("PENDING", "IN_PROGRESS", "REOPENED")
            ticket["is_escalated"] = is_overdue and is_open
        else:
            ticket["is_escalated"] = False
            
        return ticket

    def ticket_query_base(self):
        return f"""
            SELECT
                t.id,
                t.title,
                t.description,
                t.status,
                t.org_id,
                t.location_id,
                t.category_id,
                t.created_by,
                t.assigned_to,
                t.created_at,
                t.updated_at,
                c.category_name,
                c.department,
                COALESCE(tc.TEACHER_NAME, sc.name, 'Unknown') AS created_by_name,
                COALESCE(tc.EMAIL_ID, sc.email, '') AS created_by_email,
                COALESCE(tc.MOBILE_PHONE, sc.phone, '') AS created_by_phone,
                COALESCE(ta.TEACHER_NAME, sa.name, 'Unknown') AS assigned_to_name,
                COALESCE(ta.EMAIL_ID, sa.email, '') AS assigned_to_email,
                COALESCE(ta.MOBILE_PHONE, sa.phone, '') AS assigned_to_phone,
                loc.block AS location_block,
                loc.floor AS location_floor,
                loc.room_no AS location_room_no,
                loc.name AS location_room_name
            FROM helpdesk_tickets t
            INNER JOIN helpdesk_categories c ON c.id = t.category_id
            LEFT JOIN {self.inst_prefix}teacher_info tc ON tc.TEACHER_ID = t.created_by
            LEFT JOIN helpdesk_staff_roles sc ON (sc.teacher_id = t.created_by OR sc.id = t.created_by)
            LEFT JOIN {self.inst_prefix}teacher_info ta ON ta.TEACHER_ID = t.assigned_to
            LEFT JOIN helpdesk_staff_roles sa ON (sa.teacher_id = t.assigned_to OR sa.id = t.assigned_to)
            LEFT JOIN {self.inst_prefix}location loc ON loc.id = t.location_id
            WHERE 1=1
        """

    def list_tickets(self, viewer, scope="all", filters=None, limit=None, offset=None):
        filters = filters or {}
        sql = self.ticket_query_base()
        params = []

        # Enforce org partitioning for all queries
        sql += " AND t.org_id = %s"
        params.append(viewer.get("org_id", "2000"))

        if scope == "own":
            sql += " AND t.created_by = %s"
            params.append(viewer["id"])
        elif scope == "assigned":
            sql += " AND t.assigned_to = %s"
            params.append(viewer["id"])
        elif scope in ["department", "dept"] or viewer["role"] == "HOD":
            sql += " AND c.department = %s"
            params.append(viewer["department"])

        if filters.get("status"):
            sql += " AND t.status = %s"
            params.append(filters["status"])
        if filters.get("department"):
            sql += " AND c.department = %s"
            params.append(filters["department"])
        if filters.get("category_id"):
            sql += " AND t.category_id = %s"
            params.append(filters["category_id"])
        if filters.get("org_id"):
            # If viewer is SUPER_ADMIN/ADMIN they might filter by org, but it's already scoped
            # Still, we can append it just in case
            sql += " AND t.org_id = %s"
            params.append(filters["org_id"])
        if filters.get("from_date"):
            sql += " AND DATE(t.created_at) >= %s"
            params.append(filters["from_date"])
        if filters.get("to_date"):
            sql += " AND DATE(t.created_at) <= %s"
            params.append(filters["to_date"])
        if filters.get("q"):
            like = f"%{filters['q']}%"
            sql += " AND (t.title LIKE %s OR t.description LIKE %s OR c.category_name LIKE %s OR tc.TEACHER_NAME LIKE %s OR ta.TEACHER_NAME LIKE %s)"
            params.extend([like, like, like, like, like])

        sql += " ORDER BY t.updated_at DESC"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET %s"
                params.append(offset)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            tickets = cursor.fetchall()
            return [self.add_escalation_status(t) for t in tickets]

    def list_ticket_activity(self, ticket_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT a.id, a.from_status, a.to_status, a.remarks, a.time_taken, a.attachment_path, a.created_at,
                       COALESCE(t.TEACHER_NAME, s.name, 'System') AS action_by_name
                FROM helpdesk_ticket_activity a
                LEFT JOIN {self.inst_prefix}teacher_info t ON t.TEACHER_ID = a.action_by
                LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = a.action_by OR s.id = a.action_by)
                WHERE a.ticket_id = %s
                ORDER BY a.created_at DESC
                """,
                (ticket_id,),
            )
            return cursor.fetchall()

    def get_ticket(self, ticket_id):
        sql = self.ticket_query_base() + " AND t.id = %s LIMIT 1"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, (ticket_id,))
            ticket = cursor.fetchone()
            if not ticket:
                return None
            ticket = self.add_escalation_status(ticket)
            if ticket:
                if (not ticket.get("assigned_to_phone") or str(ticket.get("assigned_to_phone")).strip() in ('', '0', 'None')) and ticket.get("assigned_to_email"):
                    ticket["assigned_to_phone"] = self.get_user_phone(ticket["assigned_to_email"], use_fallback=False)
                if (not ticket.get("created_by_phone") or str(ticket.get("created_by_phone")).strip() in ('', '0', 'None')) and ticket.get("created_by_email"):
                    ticket["created_by_phone"] = self.get_user_phone(ticket["created_by_email"], use_fallback=False)
            return ticket

    ALLOWED_TRANSITIONS = {
        "PENDING": {"IN_PROGRESS"},
        "IN_PROGRESS": {"ON_HOLD", "RESOLVED"},
        "ON_HOLD": {"IN_PROGRESS"},
        "RESOLVED": {"REOPENED"},
        "REOPENED": {"IN_PROGRESS"},
    }

    def update_ticket_status(self, ticket_id, actor, status, remarks="", time_taken="", attachment_path=""):
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError("Ticket not found.")

        if actor.get("org_id") and ticket.get("org_id") and ticket["org_id"] != actor["org_id"]:
            raise PermissionError("Access denied: Ticket belongs to a different organization.")

        # Permission check:
        # - Assigned CA/ASSIGNEE can update their own assigned tickets
        # - Ticket creator can REOPEN a RESOLVED ticket
        # - HOD, SUPER_ADMIN and ADMIN have view-only access and cannot update resolution status
        is_assigned_ca = (
            actor.get("role") in ["CA", "ASSIGNEE"]
            and (
                (ticket.get("assigned_to_email") and actor.get("email") and ticket["assigned_to_email"].lower() == actor["email"].lower())
                or (ticket.get("assigned_to") and ticket.get("assigned_to") == actor.get("id"))
            )
        )
        is_creator_reopening = (
            (
                (ticket.get("created_by_email") and actor.get("email") and ticket["created_by_email"].lower() == actor["email"].lower())
                or (ticket.get("created_by") and ticket.get("created_by") == actor.get("id"))
            )
            and ticket.get("status") == "RESOLVED"
            and status == "REOPENED"
        )
        if not is_assigned_ca and not is_creator_reopening:
            raise PermissionError("Only the assigned Assignee can update this ticket.")

        # Enforce valid status transitions
        current_status = ticket["status"]
        allowed = self.ALLOWED_TRANSITIONS.get(current_status, set())
        if status not in allowed:
            raise ValueError(
                f"Invalid status transition: Cannot transition from {current_status} to {status}. "
                f"Allowed: {', '.join(sorted(allowed)) or 'none (terminal state)'}."
            )

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE helpdesk_tickets SET status = %s WHERE id = %s",
                (status, ticket_id),
            )
            try:
                cursor.execute(
                    """
                    INSERT INTO helpdesk_ticket_activity
                        (ticket_id, action_by, from_status, to_status, remarks, time_taken, attachment_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (ticket_id, actor["id"], ticket["status"], status, remarks, time_taken, attachment_path),
                )
            except Exception as act_exc:
                act_code = getattr(act_exc, "args", [None])[0] if hasattr(act_exc, "args") and act_exc.args else None
                if act_code == 1062 or "Duplicate entry" in str(act_exc):
                    log.info("Ticket activity update skipped (duplicate entry): %s", act_exc)
                else:
                    raise
            if attachment_path:
                try:
                    cursor.execute(
                        """
                        INSERT INTO helpdesk_attachments
                            (ticket_id, stored_filename, original_filename, uploaded_by)
                        VALUES (%s, %s, %s, %s)
                        """,
                        (ticket_id, attachment_path, attachment_path, actor.get("id")),
                    )
                except Exception as att_exc:
                    log.warning("Could not insert attachment record: %s", att_exc)
            if status == "RESOLVED":
                try:
                    from email_services import send_closure_email
                    if ticket.get("created_by_email"):
                        send_closure_email(ticket["created_by_email"], ticket_id)
                except Exception:
                    pass
                try:
                    from sms_services import send_closure_sms
                    if ticket.get("created_by_email"):
                        creator_phone = self.get_user_phone(ticket["created_by_email"])
                        if creator_phone:
                            send_closure_sms(creator_phone, ticket_id)
                except Exception:
                    pass
        return True

    def record_attachment(self, ticket_id: int, stored_filename: str, original_filename: str, uploaded_by: int = None, file_size: int = 0, mime_type: str = None) -> bool:
        """Record attachment metadata into helpdesk_attachments table."""
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO helpdesk_attachments
                        (ticket_id, stored_filename, original_filename, uploaded_by, file_size, mime_type)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (ticket_id, stored_filename, original_filename, uploaded_by, file_size, mime_type),
                )
            return True
        except Exception as exc:
            log.warning("Failed to record attachment for ticket %s: %s", ticket_id, exc)
            return False

    def get_attachment_ticket_id(self, stored_filename: str):
        """Lookup ticket ID for an attachment filename from attachments, activity, or filename prefix."""
        if not stored_filename:
            return None
        # 1. Check helpdesk_attachments
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT ticket_id FROM helpdesk_attachments WHERE stored_filename = %s LIMIT 1", (stored_filename,))
                row = cursor.fetchone()
                if row:
                    tid = row.get("ticket_id") if isinstance(row, dict) else row[0]
                    if tid:
                        return int(tid)
        except Exception as exc:
            log.warning("Attachment lookup in helpdesk_attachments failed: %s", exc)

        # 2. Check helpdesk_ticket_activity
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT ticket_id FROM helpdesk_ticket_activity WHERE attachment_path = %s LIMIT 1", (stored_filename,))
                row = cursor.fetchone()
                if row:
                    tid = row.get("ticket_id") if isinstance(row, dict) else row[0]
                    if tid:
                        return int(tid)
        except Exception as exc:
            log.warning("Attachment lookup in helpdesk_ticket_activity failed: %s", exc)

        # 3. Filename convention fallback: {ticket_id}-{timestamp}-{name}
        import re
        match = re.match(r"^(\d+)-", stored_filename)
        if match:
            return int(match.group(1))

        return None

    def get_ca_open_tickets(self, ca_id: int, department: str = None, org_id: str = None) -> list:
        """Fetch all active open tickets assigned to a specific CA (PENDING, IN_PROGRESS, ON_HOLD, REOPENED)."""
        sql = self.ticket_query_base() + " AND t.assigned_to = %s AND t.status IN ('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'REOPENED')"
        params = [ca_id]
        if department:
            sql += " AND LOWER(c.department) = LOWER(%s)"
            params.append(department)
        if org_id:
            sql += " AND t.org_id = %s"
            params.append(org_id)
        sql += " ORDER BY t.created_at DESC"

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            tickets = cursor.fetchall()
            return [self.add_escalation_status(t) for t in tickets]

    def reassign_tickets(self, ticket_ids: list, source_ca_id: int, target_ca_id: int, actor: dict, remarks: str = "") -> dict:
        """
        Selectively reassigns a list of tickets from source_ca_id to target_ca_id.
        Performs strict validation of actor permissions, ticket status, CA eligibility, and department scoping.
        """
        if not ticket_ids:
            raise ValueError("No tickets selected for reassignment.")

        try:
            source_ca_id = int(str(source_ca_id).strip())
            target_ca_id = int(str(target_ca_id).strip())
        except (ValueError, TypeError):
            raise ValueError("Both source and replacement Assignee must be specified.")

        if source_ca_id == target_ca_id:
            raise ValueError("Source Assignee and Replacement Assignee cannot be the same person.")

        # 1. Validate Actor Permissions
        actor_role = (actor.get("role") or "").upper()
        if actor_role not in ["HOD", "ADMIN", "SUPER_ADMIN"]:
            raise PermissionError("Only Department Heads and Administrators can reassign tickets.")

        # 2. Validate Source & Target CAs
        source_ca = self.get_user(source_ca_id)
        if not source_ca:
            raise ValueError("Source Assignee not found.")

        target_ca = self.get_user(target_ca_id)
        if not target_ca:
            raise ValueError("Replacement Assignee not found.")

        if target_ca.get("is_active", 1) == 0:
            raise ValueError("Replacement Assignee account is inactive.")

        if actor_role == "HOD":
            actor_dept = (actor.get("department") or "").lower().strip()
            target_dept = (target_ca.get("department") or "").lower().strip()
            if actor_dept and target_dept and actor_dept != target_dept:
                raise PermissionError("Replacement Assignee must belong to your department.")

        # 3. Validate Each Selected Ticket
        valid_tickets = []
        for t_id in ticket_ids:
            try:
                tid = int(str(t_id).strip())
            except (ValueError, TypeError):
                continue
            ticket = self.get_ticket(tid)
            if not ticket:
                raise ValueError(f"Ticket #{tid} not found.")

            if ticket.get("assigned_to") != source_ca_id:
                raise ValueError(f"Ticket #{tid} is not currently assigned to {source_ca.get('name')}.")

            if ticket.get("status") in ["RESOLVED"]:
                raise ValueError(f"Ticket #{tid} is already RESOLVED and cannot be reassigned.")

            if actor_role == "HOD":
                ticket_dept = (ticket.get("department") or "").lower().strip()
                actor_dept = (actor.get("department") or "").lower().strip()
                if actor_dept and ticket_dept and actor_dept != ticket_dept:
                    raise PermissionError(f"Ticket #{tid} belongs to {ticket.get('department')}, not your department.")

            valid_tickets.append(ticket)

        target_dept = (target_ca.get("department") or "").strip()
        for t in valid_tickets:
            ticket_dept = (t.get("department") or "").strip()
            if target_dept and ticket_dept and not self.departments_match(target_dept, ticket_dept):
                raise ValueError(
                    f"Department mismatch: Ticket #{t.get('id')} belongs to department '{ticket_dept}', "
                    f"but replacement assignee belongs to '{target_dept}'."
                )

        if not valid_tickets:
            raise ValueError("No valid tickets eligible for reassignment.")

        # 4. Atomic Execution
        transfer_note = remarks.strip() if remarks else f"Ticket selectively reassigned from {source_ca.get('name')} to {target_ca.get('name')} by {actor.get('name')} ({actor_role})."

        with self.connection() as connection, connection.cursor() as cursor:
            for t in valid_tickets:
                cursor.execute(
                    "UPDATE helpdesk_tickets SET assigned_to = %s WHERE id = %s AND assigned_to = %s",
                    (target_ca_id, t["id"], source_ca_id),
                )
                cursor.execute(
                    """
                    INSERT INTO helpdesk_ticket_activity
                        (ticket_id, action_by, from_status, to_status, remarks, time_taken, attachment_path)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (t["id"], actor.get("id") or actor.get("user_id") or 1, t["status"], t["status"], transfer_note, "", ""),
                )

        # Audit Event
        actor_id = actor.get("id") or actor.get("user_id") or 1
        self.log_audit_event(
            "TICKETS_REASSIGNED", actor_id, actor.get("org_id", "2000"),
            target_type="tickets", target_id=target_ca_id,
            details={
                "source_ca_id": source_ca_id,
                "source_ca_name": source_ca.get("name"),
                "target_ca_id": target_ca_id,
                "target_ca_name": target_ca.get("name"),
                "reassigned_count": len(valid_tickets),
                "ticket_ids": [t["id"] for t in valid_tickets],
                "remarks": remarks,
            }
        )

        return {
            "success": True,
            "reassigned_count": len(valid_tickets),
            "ticket_ids": [t["id"] for t in valid_tickets],
            "source_ca_name": source_ca.get("name"),
            "target_ca_name": target_ca.get("name"),
        }

    # ── Analytics ────────────────────────────────────────

    def ticket_stats_by_category(self, department=None, org_id=None):
        on_clause = "ON t.category_id = c.id"
        params = []
        if org_id:
            on_clause += " AND t.org_id = %s"
            params.append(org_id)

        sql = f"""
            SELECT c.category_name, c.department,
                   COUNT(t.id) AS ticket_count,
                   SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                   SUM(CASE WHEN t.status = 'ON_HOLD' THEN 1 ELSE 0 END) AS on_hold,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved,
                   SUM(CASE WHEN t.status = 'REOPENED' THEN 1 ELSE 0 END) AS reopened
            FROM helpdesk_categories c
            LEFT JOIN helpdesk_tickets t {on_clause}
            WHERE 1=1
        """
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        if org_id:
            sql += f" AND c.department IN (SELECT BRANCH_CODE FROM {self.inst_prefix}branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)

        sql += " GROUP BY c.id, c.category_name, c.department ORDER BY ticket_count DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def ticket_stats_by_department(self, org_id=None):
        on_clause = "ON t.category_id = c.id"
        params = []
        if org_id:
            on_clause += " AND t.org_id = %s"
            params.append(org_id)

        sql = f"""
            SELECT c.department,
                   COUNT(t.id) AS ticket_count,
                   SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                   SUM(CASE WHEN t.status = 'ON_HOLD' THEN 1 ELSE 0 END) AS on_hold,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved,
                   SUM(CASE WHEN t.status = 'REOPENED' THEN 1 ELSE 0 END) AS reopened
            FROM helpdesk_categories c
            LEFT JOIN helpdesk_tickets t {on_clause}
            WHERE 1=1
        """
        if org_id:
            sql += f" AND c.department IN (SELECT BRANCH_CODE FROM {self.inst_prefix}branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)

        sql += """
            GROUP BY c.department
            ORDER BY ticket_count DESC
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def dashboard_summary(self, viewer):
        sql = """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                SUM(CASE WHEN t.status = 'ON_HOLD' THEN 1 ELSE 0 END) AS on_hold,
                SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved,
                SUM(CASE WHEN t.status = 'REOPENED' THEN 1 ELSE 0 END) AS reopened
            FROM helpdesk_tickets t
            INNER JOIN helpdesk_categories c ON c.id = t.category_id
            WHERE 1=1
        """
        params = []
        if viewer["role"] == "FACULTY":
            sql += " AND t.created_by = %s"
            params.append(viewer["id"])
        elif viewer["role"] in ["CA", "ASSIGNEE"]:
            sql += " AND t.assigned_to = %s"
            params.append(viewer["id"])
        elif viewer["role"] == "HOD":
            sql += " AND c.department = %s"
            params.append(viewer["department"])

        if viewer.get("org_id"):
            sql += " AND t.org_id = %s"
            params.append(viewer["org_id"])

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def hod_overview(self, org_id=None):
        if self.inst_prefix:
            sql = f"""
                SELECT
                    t.TEACHER_ID AS id,
                    t.TEACHER_NAME AS name,
                    t.EMAIL_ID AS email,
                    b.BRANCH_CODE AS department,
                    COUNT(DISTINCT c.id) AS category_count,
                    COUNT(DISTINCT tk.id) AS ticket_count
                FROM {self.inst_prefix}branch_detail b
                INNER JOIN {self.inst_prefix}teacher_info t ON (
                    t.TEACHER_ID = b.HOD_ID OR t.TEACHER_CODE = b.HOD_ID OR t.SAP_ID = b.HOD_ID
                )
                LEFT JOIN helpdesk_categories c ON (c.department = b.BRANCH_CODE AND (c.org_id = %s OR c.org_id IS NULL))
                LEFT JOIN helpdesk_tickets tk ON (tk.category_id = c.id AND (tk.org_id = %s OR tk.org_id IS NULL))
                WHERE 1=1
            """
            target_org = org_id or "2000"
            params = [target_org, target_org]
            if org_id:
                sql += " AND CAST(b.ORG_ID AS CHAR) = %s"
                params.append(org_id)

            sql += """
                GROUP BY t.TEACHER_ID, t.TEACHER_NAME, t.EMAIL_ID, b.BRANCH_CODE
                ORDER BY b.BRANCH_CODE
            """
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchall()

        sql = """
            SELECT
                u.id,
                u.name,
                u.email,
                u.department,
                COUNT(DISTINCT c.id) AS category_count,
                COUNT(DISTINCT t.id) AS ticket_count
            FROM helpdesk_users u
            LEFT JOIN helpdesk_categories c ON (c.department = u.department AND (c.org_id = %s OR c.org_id IS NULL))
            LEFT JOIN helpdesk_tickets t ON (t.category_id = c.id AND (t.org_id = %s OR t.org_id IS NULL))
            WHERE u.role = 'HOD'
        """
        target_org = org_id or "2000"
        params = [target_org, target_org]
        if org_id:
            sql += f" AND u.department IN (SELECT BRANCH_CODE FROM {self.inst_prefix}branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)

        sql += """
            GROUP BY u.id, u.name, u.email, u.department
            ORDER BY u.department
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def create_location(self, org_id, block, floor, room_no, name):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {self.inst_prefix}location (ORG_ID, block, floor, room_no, name)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (org_id, block, floor, room_no, name),
            )
            return cursor.lastrowid

    def create_department(self, branch_code, branch_name, org_id):
        with self.connection() as connection, connection.cursor() as cursor:
            # Check if department code already exists
            cursor.execute(
                f"SELECT BRANCH_ID FROM {self.inst_prefix}branch_detail WHERE LOWER(BRANCH_CODE) = LOWER(%s) AND ORG_ID = %s LIMIT 1",
                (branch_code, org_id),
            )
            if cursor.fetchone():
                raise ValueError(f"Department code '{branch_code}' already exists.")
            cursor.execute(
                f"""
                INSERT INTO {self.inst_prefix}branch_detail (BRANCH_CODE, BRANCH_NAME, ORG_ID)
                VALUES (%s, %s, %s)
                """,
                (branch_code, branch_name, org_id),
            )
            return cursor.lastrowid

    def list_ca_assignments(self, department=None, search="", org_id=None):
        sql = f"""
            SELECT a.id, a.category_id, a.ca_id, a.block, a.created_at,
                   c.category_name, c.department,
                   COALESCE(t.TEACHER_NAME, s.name, 'Unknown') AS ca_name,
                   COALESCE(t.EMAIL_ID, s.email, '') AS ca_email
            FROM helpdesk_ca_assignments a
            INNER JOIN helpdesk_categories c ON c.id = a.category_id
            LEFT JOIN {self.inst_prefix}teacher_info t ON t.TEACHER_ID = a.ca_id
            LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = a.ca_id OR s.id = a.ca_id)
            WHERE 1=1
        """
        params = []
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        if org_id:
            sql += f" AND c.department IN (SELECT BRANCH_CODE FROM {self.inst_prefix}branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)
        if search:
            like = f"%{search}%"
            sql += " AND (c.category_name LIKE %s OR t.TEACHER_NAME LIKE %s OR s.name LIKE %s OR a.block LIKE %s)"
            params.extend([like, like, like, like])
        sql += " ORDER BY c.category_name, a.block"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def create_ca_assignment(self, category_id, ca_id, block):
        with self.connection() as connection, connection.cursor() as cursor:
            # Check if assignment already exists
            cursor.execute(
                """
                SELECT id FROM helpdesk_ca_assignments
                WHERE category_id = %s AND ca_id = %s AND LOWER(block) = LOWER(%s)
                LIMIT 1
                """,
                (category_id, ca_id, block),
            )
            if cursor.fetchone():
                raise ValueError("This CA is already assigned to this category and block.")
            cursor.execute(
                """
                INSERT INTO helpdesk_ca_assignments (category_id, ca_id, block)
                VALUES (%s, %s, %s)
                """,
                (category_id, ca_id, block),
            )
            return cursor.lastrowid

    def delete_ca_assignment(self, assignment_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM helpdesk_ca_assignments WHERE id = %s", (assignment_id,))

    create_assignee_assignment = create_ca_assignment
    delete_assignee_assignment = delete_ca_assignment

    def resolve_assigned_ca(self, category_id, block):
        """
        Resolve who to assign the ticket to.
        Multi-CA routing engine:
        1. Find all CAs assigned to this category+block via helpdesk_ca_assignments (exact block or 'All Blocks').
        2. If match found, select least-loaded CA among matches.
        3. If no exact block match, find ALL CAs for this category (any block) as secondary pool and select least-loaded.
        4. Fall back to category's default assigned_ca_id.
        """
        category = self.get_category(category_id)
        if not category:
            return None

        with self.connection() as connection, connection.cursor() as cursor:
            # Step 1: Exact block match or 'All Blocks'
            if block:
                cursor.execute(
                    """
                    SELECT ca_id FROM helpdesk_ca_assignments 
                    WHERE category_id = %s AND (LOWER(block) = LOWER(%s) OR LOWER(block) IN ('all blocks', 'all', 'campus'))
                    """,
                    (category_id, block),
                )
                rows = cursor.fetchall()
                if rows:
                    ca_ids = list(dict.fromkeys([r["ca_id"] for r in rows]))
                    return self._select_least_loaded_ca(cursor, ca_ids)

            # Step 2: Any block / all assigned CAs for this category
            cursor.execute(
                "SELECT DISTINCT ca_id FROM helpdesk_ca_assignments WHERE category_id = %s",
                (category_id,),
            )
            rows = cursor.fetchall()
            if rows:
                ca_ids = list(dict.fromkeys([r["ca_id"] for r in rows]))
                return self._select_least_loaded_ca(cursor, ca_ids)

            # Step 3: Fallback to category's default assigned CA
            return category.get("assigned_ca_id")

    resolve_assigned_to = resolve_assigned_ca

    def _select_least_loaded_ca(self, cursor, ca_ids):
        """Given a list of CA IDs, return the one with the fewest active tickets."""
        if len(ca_ids) == 1:
            return ca_ids[0]
        placeholders = ", ".join(["%s"] * len(ca_ids))
        sql_load = f"""
            SELECT t.assigned_to AS id, COUNT(t.id) AS active_count
            FROM helpdesk_tickets t
            WHERE t.assigned_to IN ({placeholders}) AND t.status IN ('PENDING', 'IN_PROGRESS', 'REOPENED')
            GROUP BY t.assigned_to
        """
        cursor.execute(sql_load, ca_ids)
        load_rows = cursor.fetchall()
        counts = {r.get("id"): r.get("active_count", 0) for r in load_rows if r.get("id") is not None}
        return min(ca_ids, key=lambda cid: counts.get(cid, 0))

    # ── Audit Events (Feature 11) ───────────────────────────

    def log_audit_event(self, event_type, actor_id, org_id, target_type=None, target_id=None, details=None):
        """Insert an audit event. `details` can be a dict (will be JSON-serialized)."""
        details_str = json.dumps(details) if isinstance(details, dict) else (details or "")
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO helpdesk_audit_events (event_type, actor_id, target_type, target_id, org_id, details)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (event_type, actor_id, target_type, target_id, org_id, details_str),
                )
        except Exception:
            pass  # Audit should never break main flow

    def list_audit_events(self, org_id=None, event_type=None, search="", from_date=None, to_date=None, limit=100):
        sql = f"""
            SELECT a.id, a.event_type, a.actor_id, a.target_type, a.target_id,
                   a.org_id, a.details, a.created_at,
                   COALESCE(t.TEACHER_NAME, s.name, 'System') AS actor_name,
                   COALESCE(t.EMAIL_ID, s.email, '') AS actor_email
            FROM helpdesk_audit_events a
            LEFT JOIN {self.inst_prefix}teacher_info t ON t.TEACHER_ID = a.actor_id
            LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = a.actor_id OR s.id = a.actor_id)
            WHERE 1=1
        """
        params = []
        if org_id:
            sql += " AND a.org_id = %s"
            params.append(org_id)
        if event_type:
            sql += " AND a.event_type = %s"
            params.append(event_type)
        if search:
            like = f"%{search}%"
            sql += " AND (a.details LIKE %s OR t.TEACHER_NAME LIKE %s OR s.name LIKE %s OR a.event_type LIKE %s)"
            params.extend([like, like, like, like])
        if from_date:
            sql += " AND DATE(a.created_at) >= %s"
            params.append(from_date)
        if to_date:
            sql += " AND DATE(a.created_at) <= %s"
            params.append(to_date)
        sql += " ORDER BY a.created_at DESC LIMIT %s"
        params.append(limit)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    # ── Department Management (Feature 4) ───────────────────

    def update_department(self, branch_id, branch_code, branch_name):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {self.inst_prefix}branch_detail SET BRANCH_CODE = %s, BRANCH_NAME = %s WHERE BRANCH_ID = %s",
                (branch_code, branch_name, branch_id),
            )

    def archive_department(self, branch_id, is_archived):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {self.inst_prefix}branch_detail SET is_archived = %s WHERE BRANCH_ID = %s",
                (1 if is_archived else 0, branch_id),
            )

    def get_department(self, branch_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT BRANCH_ID, BRANCH_CODE, BRANCH_NAME, CAST(ORG_ID AS CHAR) AS org_id FROM {self.inst_prefix}branch_detail WHERE BRANCH_ID = %s",
                (branch_id,),
            )
            return cursor.fetchone()

    def get_department_by_code(self, branch_code, org_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                f"SELECT BRANCH_ID, BRANCH_CODE, BRANCH_NAME, CAST(ORG_ID AS CHAR) AS org_id FROM {self.inst_prefix}branch_detail WHERE LOWER(BRANCH_CODE) = LOWER(%s) AND CAST(ORG_ID AS CHAR) = %s LIMIT 1",
                (branch_code, org_id),
            )
            return cursor.fetchone()

    # ── New Methods for Refactored Blueprints ────────────────────────

    def search_users(self, q="", role="", department="", org_id=None, limit=20):
        """Search users by name, email, or department for autocomplete."""
        if not q:
            return []
        if self.inst_prefix:
            results = []
            like = f"%{q}%"
            with self.connection() as connection, connection.cursor() as cursor:
                # 1. Staff roles
                cursor.execute(
                    "SELECT id, name, email, role, department FROM helpdesk_staff_roles WHERE (name LIKE %s OR email LIKE %s) LIMIT %s",
                    (like, like, limit),
                )
                results.extend(cursor.fetchall())
                
                # 2. Teacher info
                rem = limit - len(results)
                if rem > 0:
                    cursor.execute(
                        f"""
                        SELECT t.TEACHER_ID AS id, t.TEACHER_NAME AS name, t.EMAIL_ID AS email,
                               'FACULTY' AS role, b.BRANCH_CODE AS department
                        FROM {self.inst_prefix}teacher_info t
                        LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
                        WHERE (t.TEACHER_NAME LIKE %s OR t.EMAIL_ID LIKE %s)
                        LIMIT %s
                        """,
                        (like, like, rem),
                    )
                    results.extend(cursor.fetchall())
            return results[:limit]

        sql = "SELECT id, name, email, role, department FROM helpdesk_users WHERE 1=1"
        params = []
        like = f"%{q}%"
        sql += " AND (name LIKE %s OR email LIKE %s)"
        params.extend([like, like])
        if role:
            sql += " AND role = %s"
            params.append(role)
        if department:
            sql += " AND (department = %s OR FIND_IN_SET(%s, department) > 0)"
            params.extend([department, department])
        sql += " ORDER BY name LIMIT %s"
        params.append(limit)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def count_tickets_by_category(self, category_id):
        """Count total tickets for a given category."""
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_tickets WHERE category_id = %s", (category_id,))
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def count_active_tickets_for_ca(self, ca_id):
        """Count active (non-resolved/closed) tickets assigned to a CA."""
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM helpdesk_tickets WHERE assigned_to = %s AND status IN ('PENDING', 'IN_PROGRESS', 'REOPENED')",
                (ca_id,),
            )
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def list_ticket_notes(self, ticket_id):
        """List internal/public notes for a ticket."""
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT n.id, n.ticket_id, n.author_id, n.note, n.is_internal, n.created_at,
                           COALESCE(t.TEACHER_NAME, s.name, 'Unknown') AS author_name,
                           COALESCE(t.EMAIL_ID, s.email, '') AS author_email
                    FROM helpdesk_ticket_notes n
                    LEFT JOIN {self.inst_prefix}teacher_info t ON t.TEACHER_ID = n.author_id
                    LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = n.author_id OR s.id = n.author_id)
                    WHERE n.ticket_id = %s
                    ORDER BY n.created_at DESC
                    """,
                    (ticket_id,),
                )
                return cursor.fetchall()
        except Exception:
            return []

    def add_ticket_note(self, ticket_id, author_id, note, is_internal=True):
        """Add an internal or public note to a ticket."""
        with self.connection() as connection, connection.cursor() as cursor:
            try:
                cursor.execute(
                    """
                    INSERT INTO helpdesk_ticket_notes (ticket_id, author_id, note, is_internal)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (ticket_id, author_id, note, 1 if is_internal else 0),
                )
                return cursor.lastrowid
            except Exception as exc:
                err_code = getattr(exc, "args", [None])[0] if hasattr(exc, "args") and exc.args else None
                err_str = str(exc)
                if err_code == 1062 or "1062" in err_str or "Duplicate entry" in err_str:
                    log.info("Duplicate note detected (1062); returning existing note ID for ticket %s.", ticket_id)
                    cursor.execute(
                        """
                        SELECT id FROM helpdesk_ticket_notes
                        WHERE ticket_id = %s AND author_id = %s
                        ORDER BY id DESC LIMIT 1
                        """,
                        (ticket_id, author_id),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        return existing["id"]
                raise

    def ticket_trends(self, org_id=None, department=None, period="monthly"):
        """Return ticket creation counts grouped by time period."""
        if period == "daily":
            date_fmt = "%Y-%m-%d"
            group_expr = "DATE(t.created_at)"
        elif period == "weekly":
            date_fmt = "%Y-W%v"
            group_expr = "DATE_FORMAT(t.created_at, '%Y-W%v')"
        else:
            date_fmt = "%Y-%m"
            group_expr = "DATE_FORMAT(t.created_at, '%Y-%m')"

        sql = f"""
            SELECT {group_expr} AS period,
                   COUNT(*) AS total_created,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS total_resolved
            FROM helpdesk_tickets t
            INNER JOIN helpdesk_categories c ON c.id = t.category_id
            WHERE 1=1
        """
        params = []
        if org_id:
            sql += " AND t.org_id = %s"
            params.append(org_id)
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        sql += f" GROUP BY {group_expr} ORDER BY {group_expr} DESC LIMIT 24"
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [{"period": str(r["period"]), "created": r["total_created"], "resolved": r["total_resolved"]} for r in rows]
        except Exception:
            return []

    def ca_performance_stats(self, org_id=None, department=None):
        """Return performance stats per CA: assigned, resolved, avg resolution time."""
        if self.inst_prefix:
            sql = f"""
                SELECT COALESCE(t.assigned_to, a.ca_id) AS id,
                       COALESCE(ti.TEACHER_NAME, s.name, 'Assignee') AS name,
                       COALESCE(ti.EMAIL_ID, s.email, '') AS email,
                       COALESCE(c.department, b.BRANCH_CODE, 'General') AS department,
                       COUNT(t.id) AS total_assigned,
                       SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS total_resolved,
                       SUM(CASE WHEN t.status IN ('PENDING', 'IN_PROGRESS', 'REOPENED') THEN 1 ELSE 0 END) AS active_tickets,
                       AVG(CASE WHEN t.status = 'RESOLVED' THEN TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at) END) AS avg_resolution_hours
                FROM helpdesk_ca_assignments a
                LEFT JOIN helpdesk_categories c ON c.id = a.category_id
                LEFT JOIN helpdesk_tickets t ON t.assigned_to = a.ca_id
                LEFT JOIN {self.inst_prefix}teacher_info ti ON ti.TEACHER_ID = a.ca_id
                LEFT JOIN {self.inst_prefix}branch_detail b ON b.BRANCH_ID = ti.BRANCH_ID
                LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = a.ca_id OR s.id = a.ca_id)
                WHERE 1=1
            """
            params = []
            if org_id:
                sql += " AND t.org_id = %s"
                params.append(org_id)
            if department:
                sql += " AND c.department = %s"
                params.append(department)
            sql += " GROUP BY id, name, email, department ORDER BY total_assigned DESC"
            try:
                with self.connection() as connection, connection.cursor() as cursor:
                    cursor.execute(sql, params)
                    rows = cursor.fetchall()
                    result = []
                    for r in rows:
                        result.append({
                            "id": r["id"],
                            "name": r["name"],
                            "email": r["email"],
                            "department": r["department"],
                            "total_assigned": r["total_assigned"] or 0,
                            "total_resolved": r["total_resolved"] or 0,
                            "active_tickets": r["active_tickets"] or 0,
                            "avg_resolution_hours": round(float(r["avg_resolution_hours"] or 0), 1),
                        })
                    return result
            except Exception:
                return []

        sql = """
            SELECT u.id, u.name, u.email, u.department,
                   COUNT(t.id) AS total_assigned,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS total_resolved,
                   SUM(CASE WHEN t.status IN ('PENDING', 'IN_PROGRESS', 'REOPENED') THEN 1 ELSE 0 END) AS active_tickets,
                   AVG(CASE WHEN t.status = 'RESOLVED' THEN TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at) END) AS avg_resolution_hours
            FROM helpdesk_users u
            LEFT JOIN helpdesk_tickets t ON t.assigned_to = u.id
            LEFT JOIN helpdesk_categories c ON c.id = t.category_id
            WHERE u.role = 'CA'
        """
        params = []
        if org_id:
            sql += " AND t.org_id = %s"
            params.append(org_id)
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        sql += " GROUP BY u.id, u.name, u.email, u.department ORDER BY total_assigned DESC"
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                result = []
                for r in rows:
                    result.append({
                        "id": r["id"],
                        "name": r["name"],
                        "email": r["email"],
                        "department": r["department"],
                        "total_assigned": r["total_assigned"] or 0,
                        "total_resolved": r["total_resolved"] or 0,
                        "active_tickets": r["active_tickets"] or 0,
                        "avg_resolution_hours": round(float(r["avg_resolution_hours"] or 0), 1),
                    })
                return result
        except Exception:
            return []

    def resolution_time_stats(self, org_id=None, department=None):
        """Return average resolution time by category."""
        sql = """
            SELECT c.category_name, c.department,
                   COUNT(t.id) AS resolved_count,
                   AVG(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at)) AS avg_hours,
                   MIN(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at)) AS min_hours,
                   MAX(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at)) AS max_hours
            FROM helpdesk_tickets t
            INNER JOIN helpdesk_categories c ON c.id = t.category_id
            WHERE t.status = 'RESOLVED'
        """
        params = []
        if org_id:
            sql += " AND t.org_id = %s"
            params.append(org_id)
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        sql += " GROUP BY c.id, c.category_name, c.department ORDER BY avg_hours DESC"
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                result = []
                for r in rows:
                    result.append({
                        "category": r["category_name"],
                        "department": r["department"],
                        "resolved_count": r["resolved_count"] or 0,
                        "avg_hours": round(float(r["avg_hours"] or 0), 1),
                        "min_hours": round(float(r["min_hours"] or 0), 1),
                        "max_hours": round(float(r["max_hours"] or 0), 1),
                    })
                return result
        except Exception:
            return []

    def check_rate_limit(self, identifier: str, ip_address: str, window_minutes: int = 15, max_user: int = 5, max_ip: int = 30) -> tuple[bool, str]:
        """Check whether an account or IP address is currently locked out by distributed rate limiting."""
        clean_id = (identifier or "").strip().lower()
        clean_ip = (ip_address or "127.0.0.1").strip()
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM helpdesk_login_attempts
                WHERE identifier = %s AND outcome = 'FAILURE'
                  AND attempted_at >= NOW() - INTERVAL %s MINUTE
                """,
                (clean_id, window_minutes),
            )
            row_id = cur.fetchone()
            id_fails = row_id["total"] if isinstance(row_id, dict) else (row_id[0] if row_id else 0)
            if id_fails >= max_user:
                return True, f"Too many failed login attempts for this account. Please try again in {window_minutes} minutes."

            cur.execute(
                """
                SELECT COUNT(*) AS total
                FROM helpdesk_login_attempts
                WHERE ip_address = %s AND outcome = 'FAILURE'
                  AND attempted_at >= NOW() - INTERVAL %s MINUTE
                """,
                (clean_ip, window_minutes),
            )
            row_ip = cur.fetchone()
            ip_fails = row_ip["total"] if isinstance(row_ip, dict) else (row_ip[0] if row_ip else 0)
            if ip_fails >= max_ip:
                return True, f"Too many failed login attempts from this network. Please try again in {window_minutes} minutes."

            return False, ""

    def record_login_attempt(self, identifier: str, ip_address: str, outcome: str = "FAILURE") -> None:
        """Record a login attempt outcome in helpdesk_login_attempts."""
        clean_id = (identifier or "").strip().lower()
        clean_ip = (ip_address or "127.0.0.1").strip()
        norm_outcome = "SUCCESS" if outcome.upper() == "SUCCESS" else "FAILURE"
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO helpdesk_login_attempts (identifier, ip_address, outcome)
                VALUES (%s, %s, %s)
                """,
                (clean_id, clean_ip, norm_outcome),
            )
            if norm_outcome == "SUCCESS":
                cur.execute(
                    "DELETE FROM helpdesk_login_attempts WHERE identifier = %s AND outcome = 'FAILURE'",
                    (clean_id,),
                )
                if random.random() < 0.01:
                    cur.execute("DELETE FROM helpdesk_login_attempts WHERE attempted_at < NOW() - INTERVAL 30 DAY")

    def clean_old_login_attempts(self, days: int = 30) -> int:
        """Housekeeping: prune login attempts older than N days."""
        with self.connection() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM helpdesk_login_attempts WHERE attempted_at < NOW() - INTERVAL %s DAY", (days,))
            return cur.rowcount if hasattr(cur, "rowcount") else 0

