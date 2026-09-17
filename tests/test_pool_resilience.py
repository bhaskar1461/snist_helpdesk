"""Unit & Regression Tests for Connection Pool & Resilience (Phase 5).

Tests:
1. Pool empty -> bounded wait succeeds when a connection is returned within window.
2. Pool empty + wait timeout -> one unpooled connection created + metric incremented.
3. Returning connection to full pool -> connection closed, no leak, metric incremented.
4. Query fails with 2006 -> retried, succeeds on attempt 2, query_retries == 1.
5. Query fails with 1142 -> NO retry, exception raised immediately.
6. Failure inside transaction() -> rollback happens, no retry, exception propagates.
7. IntegrityError 1062 on duplicate note dedup key -> returns existing record, not 500.
8. Sweeper removes a dead idle connection and does not touch a fresh one.
"""
import time
import threading
from unittest.mock import patch, MagicMock
import pytest

try:
    import pymysql
except ImportError:
    pymysql = MagicMock()

from db_services import (
    BaseMySQLService,
    DemoDbService,
    DbConfig,
    PooledConnection,
    PooledCursor,
)
from app.pool_metrics import POOL_METRICS


class MockRawCursor:
    def __init__(self, conn):
        self.conn = conn
        self.closed = False
        self.execute_calls = []
        self.results = []
        self.exceptions_sequence = []
        self.exception_to_raise = None
        self.lastrowid = 1
        self.rowcount = 1

    def execute(self, query, args=None):
        self.execute_calls.append((query, args))
        if self.exceptions_sequence:
            exc = self.exceptions_sequence.pop(0)
            if exc is not None:
                raise exc
        if self.exception_to_raise:
            raise self.exception_to_raise
        return 1

    def executemany(self, query, args):
        return self.execute(query, args)

    def fetchall(self):
        return self.results

    def fetchone(self):
        return self.results[0] if self.results else None

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class MockRawConn:
    def __init__(self, alive=True):
        self.alive = alive
        self.closed = False
        self._autocommit = True
        self.rollback_called = False
        self.commit_called = False
        self._created_at = time.time()
        self._last_used_at = time.time()
        self.cursor_instance = MockRawCursor(self)

    def ping(self, reconnect=True):
        if not self.alive:
            raise pymysql.err.OperationalError(2006, "MySQL server has gone away")

    def close(self):
        self.closed = True

    def get_autocommit(self):
        return self._autocommit

    def autocommit(self, val):
        self._autocommit = val

    def rollback(self):
        self.rollback_called = True

    def commit(self):
        self.commit_called = True

    def cursor(self, *args, **kwargs):
        return self.cursor_instance


@pytest.fixture(autouse=True)
def reset_pool_metrics():
    POOL_METRICS.reset()
    yield
    POOL_METRICS.reset()


def test_1_pool_empty_bounded_wait_succeeds():
    """1. Pool empty -> bounded wait succeeds when a connection is returned within the window (no unpooled connection)."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = BaseMySQLService(cfg)
    service._maxsize = 1
    service._pool_wait = 2.0

    raw_conn = MockRawConn(alive=True)
    with patch.object(service, "_create_new_connection", return_value=raw_conn):
        # Checkout connection 1 (pool capacity reached)
        conn1 = service.connection()
        assert service._in_use == 1
        assert service._pool.empty()

        # Thread 2 attempts checkout; will enter bounded wait
        result_holder = []

        def worker():
            conn2 = service.connection()
            result_holder.append(conn2)

        t = threading.Thread(target=worker)
        t.start()

        # Give worker a moment to enter bounded wait
        time.sleep(0.05)
        assert service._waiters == 1

        # Return connection 1 to pool
        conn1.close()

        t.join(timeout=1.0)
        assert len(result_holder) == 1
        conn2 = result_holder[0]

        # Verify conn2 was reused from pool, not an unpooled fallback
        assert conn2._is_unpooled is False
        assert POOL_METRICS.get_metrics()["unpooled_fallbacks"] == 0
        conn2.close()


def test_2_pool_empty_wait_timeout_spawns_unpooled():
    """2. Pool empty + wait timeout -> one unpooled connection created + metric incremented."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = BaseMySQLService(cfg)
    service._maxsize = 1
    service._pool_wait = 0.05  # Short wait for testing

    raw_conn1 = MockRawConn(alive=True)
    raw_conn2 = MockRawConn(alive=True)
    conns_to_return = [raw_conn1, raw_conn2]

    with patch.object(service, "_create_new_connection", side_effect=conns_to_return):
        # Checkout connection 1
        conn1 = service.connection()
        assert service._in_use == 1

        # Second checkout should time out on bounded wait and spawn ONE-OFF unpooled
        conn2 = service.connection()
        assert conn2._is_unpooled is True

        metrics = POOL_METRICS.get_metrics()
        assert metrics["unpooled_fallbacks"] == 1
        assert metrics["pool_timeout_errors"] == 1

        conn1.close()
        conn2.close()


def test_3_returning_connection_to_full_pool_closes_it():
    """3. Returning connection to a full pool -> connection closed, no leak, metric incremented."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = BaseMySQLService(cfg)
    from queue import Queue
    service._maxsize = 1
    service._pool = Queue(maxsize=1)

    # Fill the pool
    existing_conn = MockRawConn(alive=True)
    service._pool.put_nowait(existing_conn)
    assert service._pool.full()

    # Now create an extra pooled connection wrapper
    extra_raw = MockRawConn(alive=True)
    extra_pooled = PooledConnection(extra_raw, service._pool, is_unpooled=False, pool_service=service)

    initial_closed = POOL_METRICS.get_metrics()["connection_close_events"]
    extra_pooled.close()

    # Verify extra raw connection was closed and metric incremented
    assert extra_raw.closed is True
    assert POOL_METRICS.get_metrics()["connection_close_events"] == initial_closed + 1


@patch("time.sleep", return_value=None)
def test_4_query_fails_2006_retried_and_succeeds(mock_sleep):
    """4. Query fails with 2006 -> retried, succeeds on attempt 2, query_retries == 1."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = BaseMySQLService(cfg)

    raw1 = MockRawConn(alive=True)
    raw2 = MockRawConn(alive=True)

    # First cursor fails with 2006, second succeeds
    cursor1 = raw1.cursor()
    cursor1.exceptions_sequence = [pymysql.err.OperationalError(2006, "MySQL server has gone away")]

    cursor2 = raw2.cursor()
    cursor2.results = [{"id": 101, "name": "Success"}]

    with patch.object(service, "_create_new_connection", side_effect=[raw1, raw2]):
        result = service.execute_with_retry("SELECT id, name FROM test_table", fetch="all")

        assert result == [{"id": 101, "name": "Success"}]
        metrics = POOL_METRICS.get_metrics()
        assert metrics["query_retries"] == 1
        assert metrics["query_failures"] == 1


def test_5_query_fails_1142_no_retry():
    """5. Query fails with 1142 -> NO retry, exception raised immediately."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = BaseMySQLService(cfg)

    raw = MockRawConn(alive=True)
    cursor = raw.cursor()
    cursor.exception_to_raise = pymysql.err.OperationalError(1142, "SELECT command denied to user 'demo'")

    with patch.object(service, "_create_new_connection", return_value=raw):
        with pytest.raises(pymysql.err.OperationalError) as exc_info:
            service.execute_with_retry("SELECT * FROM secret_table", fetch="all")

        assert exc_info.value.args[0] == 1142
        metrics = POOL_METRICS.get_metrics()
        assert metrics["query_retries"] == 0
        assert metrics["query_failures"] == 1


def test_6_failure_inside_transaction_rollbacks_and_no_retry():
    """6. Failure inside transaction() -> rollback happens, no retry, exception propagates."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = BaseMySQLService(cfg)

    raw = MockRawConn(alive=True)
    cursor = raw.cursor()
    # Fails with retriable error code 2006, but inside transaction it MUST NOT retry
    cursor.exception_to_raise = pymysql.err.OperationalError(2006, "MySQL server has gone away")

    with patch.object(service, "_create_new_connection", return_value=raw):
        with pytest.raises(pymysql.err.OperationalError):
            with service.transaction() as tx_conn:
                with tx_conn.cursor() as cur:
                    cur.execute("UPDATE helpdesk_tickets SET status='RESOLVED' WHERE id=1")

        # Rollback was executed and retry was strictly avoided
        assert raw.rollback_called is True
        metrics = POOL_METRICS.get_metrics()
        assert metrics["query_retries"] == 0


def test_7_integrity_error_1062_on_duplicate_note_handled():
    """7. IntegrityError 1062 on duplicate note dedup key -> returns existing record, not 500."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = DemoDbService(cfg)

    raw = MockRawConn(alive=True)
    cursor = raw.cursor()

    # First call: INSERT raises 1062 Duplicate entry
    # Second call: SELECT returns existing note row
    cursor.exceptions_sequence = [
        pymysql.err.IntegrityError(1062, "Duplicate entry '1-10-note' for key 'uq_notes_dedup'"),
        None,  # SELECT succeeds
    ]
    cursor.results = [{"id": 88}]

    with patch.object(service, "_create_new_connection", return_value=raw):
        note_id = service.add_ticket_note(ticket_id=1, author_id=10, note="note text", is_internal=True)
        assert note_id == 88


def test_8_sweeper_removes_dead_connection_preserves_fresh():
    """8. Sweeper removes a dead idle connection and does not touch a fresh one."""
    cfg = DbConfig("localhost", 3306, "demo", "pass", "helpdesk")
    service = BaseMySQLService(cfg)
    service._maxsize = 5
    service._idle_ttl = 240.0

    now = time.time()

    # 1. Fresh connection
    fresh_conn = MockRawConn(alive=True)
    fresh_conn._last_used_at = now

    # 2. Dead/idle connection (idle for 300s > 240s TTL, ping raises 2006)
    dead_conn = MockRawConn(alive=False)
    dead_conn._last_used_at = now - 300.0

    service._pool.put_nowait(fresh_conn)
    service._pool.put_nowait(dead_conn)
    assert service._pool.qsize() == 2

    evicted = service.sweep_idle_connections()

    assert evicted == 1
    assert dead_conn.closed is True
    assert fresh_conn.closed is False
    assert service._pool.qsize() == 1
    assert service._pool.get_nowait() is fresh_conn
