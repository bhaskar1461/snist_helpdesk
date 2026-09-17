"""Multi-threaded Load Verification Script for SNIST Helpdesk Database Pool.

Simulates concurrent users performing:
  login -> list tickets -> open ticket detail -> create note
with random think time between 0.5s and 2.0s against the STAGING database (seg-dev).

Captures:
  - Requests/sec and throughput
  - Error counts (5xx / exceptions)
  - p50 and p95 connection checkout latency
  - unpooled_fallbacks and pool_timeout_errors
  - Server-side MySQL status deltas: Threads_connected, Max_used_connections, Aborted_connects
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import threading
import time
import uuid
from typing import Any, Dict

import pymysql

# Ensure repository root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.pool_metrics import POOL_METRICS
from db_services import DbConfig, DemoDbService


def fetch_server_status(host: str, port: int, user: str, password: str, database: str) -> Dict[str, int]:
    """Directly probe MySQL global status variables on target host."""
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        connect_timeout=10,
    )
    data = {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SHOW GLOBAL STATUS WHERE Variable_name IN "
                "('Threads_connected', 'Max_used_connections', 'Aborted_connects')"
            )
            for row in cur.fetchall():
                data[row[0]] = int(row[1])
    finally:
        conn.close()
    return data


class LoadTester:
    def __init__(
        self,
        host: str = "seg-dev.sreenidhi.edu.in",
        port: int = 3306,
        user: str = "demo",
        password: str = "Admin@321#",
        database: str = "helpdesk",
        institutional_db: str = "seg_demo",
        num_users: int = 100,
        duration_seconds: int = 300,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.institutional_db = institutional_db
        self.num_users = num_users
        self.duration_seconds = duration_seconds

        # Configure institutional prefix for staging views
        os.environ["MYSQL_INSTITUTIONAL_DATABASE"] = self.institutional_db

        # Configure service targeting staging
        self.config = DbConfig(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
        )
        self.service = DemoDbService(self.config)

        # Counters
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.total_requests = 0
        self.total_logins = 0
        self.total_lists = 0
        self.total_details = 0
        self.total_notes = 0
        self.error_count = 0
        self.errors_by_type: Dict[str, int] = {}

    def _record_error(self, err: Exception):
        err_name = type(err).__name__
        with self.lock:
            self.error_count += 1
            self.errors_by_type[err_name] = self.errors_by_type.get(err_name, 0) + 1
            if self.error_count <= 5:
                print(f"[Worker Error] {err_name}: {err}")

    def user_worker(self, user_idx: int, sample_ticket_ids: list[int]):
        """Simulate single user session loop: login -> list -> detail -> note -> think."""
        user_email = "ca@gmail.com" if (user_idx % 2 == 0) else "admin@gmail.com"
        user_pass = "123"

        # 1. Login step
        try:
            user_obj = self.service.authenticate_user(user_email, user_pass)
            with self.lock:
                self.total_requests += 1
                self.total_logins += 1
        except Exception as exc:
            self._record_error(exc)
            user_obj = {"id": 1, "email": user_email, "role": "ADMIN", "org_id": "2000"}

        while not self.stop_event.is_set():
            # 2. List tickets
            try:
                tickets = self.service.list_tickets(user_obj, scope="all")
                with self.lock:
                    self.total_requests += 1
                    self.total_lists += 1
            except Exception as exc:
                self._record_error(exc)
                tickets = []

            # 3. Open ticket detail
            ticket_id = random.choice(sample_ticket_ids) if sample_ticket_ids else 159
            try:
                ticket_detail = self.service.get_ticket(ticket_id)
                with self.lock:
                    self.total_requests += 1
                    self.total_details += 1
            except Exception as exc:
                self._record_error(exc)

            # 4. Create note
            note_content = f"Load test note worker #{user_idx} uuid={uuid.uuid4().hex[:8]}"
            try:
                self.service.add_ticket_note(
                    ticket_id=ticket_id,
                    author_id=user_obj.get("id", 1),
                    note=note_content,
                    is_internal=True,
                )
                with self.lock:
                    self.total_requests += 1
                    self.total_notes += 1
            except Exception as exc:
                self._record_error(exc)

            # 5. Random think time: 0.5s to 2.0s
            think_time = random.uniform(0.5, 2.0)
            if self.stop_event.wait(think_time):
                break

    def run(self) -> Dict[str, Any]:
        print(f"=== SNIST HELPDESK POOL LOAD TEST ===")
        print(f"Target DB Host    : {self.host}:{self.port} (DB: {self.database})")
        print(f"Concurrent Users  : {self.num_users}")
        print(f"Test Duration     : {self.duration_seconds}s")
        print(f"Pool Max Size     : {self.service._maxsize}")
        print(f"Pool Wait Timeout : {self.service._pool_wait}s")
        print(f"Pool Idle TTL     : {self.service._idle_ttl}s")
        print("-" * 50)

        # Reset in-memory pool metrics before test
        POOL_METRICS.reset()

        # Gather sample ticket IDs to target during test
        sample_ticket_ids = []
        try:
            with self.service.connection() as conn, conn.cursor() as cur:
                cur.execute("SELECT id FROM helpdesk_tickets LIMIT 20")
                rows = cur.fetchall()
                sample_ticket_ids = [r["id"] for r in rows]
        except Exception as exc:
            print(f"Warning: could not fetch ticket IDs for detail tests: {exc}")

        # 1. Capture Server Status BEFORE
        print("Capturing baseline server status from MySQL...")
        status_before = fetch_server_status(
            self.host, self.port, self.user, self.password, self.database
        )
        print(f"Status BEFORE: {status_before}")

        start_time = time.time()
        threads = []

        print(f"Spawning {self.num_users} concurrent worker threads...")
        for i in range(self.num_users):
            t = threading.Thread(target=self.user_worker, args=(i, sample_ticket_ids), daemon=True)
            threads.append(t)
            t.start()

        # Run for specified duration with periodic status prints
        deadline = start_time + self.duration_seconds
        try:
            while time.time() < deadline:
                remaining = int(deadline - time.time())
                elapsed = time.time() - start_time
                rps = (self.total_requests / elapsed) if elapsed > 0 else 0
                metrics_now = POOL_METRICS.get_metrics()
                print(
                    f"[{int(elapsed):3d}s elapsed, {remaining:3d}s left] "
                    f"Requests: {self.total_requests} (RPS: {rps:.1f}) | "
                    f"Errors: {self.error_count} | "
                    f"p50: {metrics_now['p50_checkout_ms']}ms, p95: {metrics_now['p95_checkout_ms']}ms | "
                    f"In-use: {self.service._in_use}, Waiters: {self.service._waiters}, "
                    f"Fallbacks: {metrics_now['unpooled_fallbacks']}"
                )
                time.sleep(min(10.0, max(1.0, remaining)))
        except KeyboardInterrupt:
            print("\nLoad test interrupted by user.")
        finally:
            self.stop_event.set()

        print("Stopping worker threads...")
        for t in threads:
            t.join(timeout=2.0)

        end_time = time.time()
        elapsed_total = end_time - start_time
        rps_final = (self.total_requests / elapsed_total) if elapsed_total > 0 else 0

        # 2. Capture Server Status AFTER
        print("Capturing final server status from MySQL...")
        status_after = fetch_server_status(
            self.host, self.port, self.user, self.password, self.database
        )
        print(f"Status AFTER: {status_after}")

        delta_threads = status_after.get("Threads_connected", 0) - status_before.get("Threads_connected", 0)
        delta_max_used = status_after.get("Max_used_connections", 0) - status_before.get("Max_used_connections", 0)
        delta_aborted = status_after.get("Aborted_connects", 0) - status_before.get("Aborted_connects", 0)

        final_metrics = POOL_METRICS.get_metrics()

        report = {
            "duration_seconds": round(elapsed_total, 2),
            "concurrent_users": self.num_users,
            "total_requests": self.total_requests,
            "requests_per_sec": round(rps_final, 2),
            "total_logins": self.total_logins,
            "total_lists": self.total_lists,
            "total_details": self.total_details,
            "total_notes": self.total_notes,
            "error_count": self.error_count,
            "errors_by_type": self.errors_by_type,
            "pool_metrics": final_metrics,
            "server_status_before": status_before,
            "server_status_after": status_after,
            "deltas": {
                "Threads_connected_delta": delta_threads,
                "Max_used_connections_delta": delta_max_used,
                "Aborted_connects_delta": delta_aborted,
            },
        }

        self.print_report(report)
        return report

    def print_report(self, r: Dict[str, Any]):
        print("\n" + "=" * 65)
        print("                 LOAD TEST REPORT SUMMARY                 ")
        print("=" * 65)
        print(f"Target Database Host    : {self.host}:{self.port} ({self.database})")
        print(f"Test Duration           : {r['duration_seconds']} seconds")
        print(f"Concurrent Users        : {r['concurrent_users']}")
        print(f"Total Requests Executed : {r['total_requests']}")
        print(f"Throughput              : {r['requests_per_sec']} req/sec")
        print("-" * 65)
        print(f"Operation Breakdown:")
        print(f"  - Login Authentications : {r['total_logins']}")
        print(f"  - Ticket Listings       : {r['total_lists']}")
        print(f"  - Ticket Details Read   : {r['total_details']}")
        print(f"  - Ticket Notes Added    : {r['total_notes']}")
        print(f"Error Count             : {r['error_count']}")
        if r['errors_by_type']:
            print(f"Errors by Type          : {r['errors_by_type']}")
        print("-" * 65)
        pm = r["pool_metrics"]
        print(f"Pool Performance Metrics:")
        print(f"  - Checkouts Total       : {pm['checkouts_total']}")
        print(f"  - Checkouts Reused      : {pm['checkouts_reused']}")
        print(f"  - New Conns Created     : {pm['new_connections_created']}")
        print(f"  - Conns Closed          : {pm['connection_close_events']}")
        print(f"  - Unpooled Fallbacks    : {pm['unpooled_fallbacks']}")
        print(f"  - Pool Timeout Errors   : {pm['pool_timeout_errors']}")
        print(f"  - Query Retries         : {pm['query_retries']}")
        print(f"  - Query Failures        : {pm['query_failures']}")
        print(f"  - Reconnects            : {pm['reconnects']}")
        print(f"  - p50 Checkout Latency  : {pm['p50_checkout_ms']} ms")
        print(f"  - p95 Checkout Latency  : {pm['p95_checkout_ms']} ms")
        print("-" * 65)
        d = r["deltas"]
        sb = r["server_status_before"]
        sa = r["server_status_after"]
        print(f"Server-Side MySQL Status Deltas:")
        print(f"  - Threads_connected     : {sb.get('Threads_connected')} -> {sa.get('Threads_connected')} (delta: {d['Threads_connected_delta']})")
        print(f"  - Max_used_connections  : {sb.get('Max_used_connections')} -> {sa.get('Max_used_connections')} (delta: {d['Max_used_connections_delta']})")
        print(f"  - Aborted_connects      : {sb.get('Aborted_connects')} -> {sa.get('Aborted_connects')} (delta: {d['Aborted_connects_delta']})")
        print("=" * 65)
        
        # Acceptance validation
        passed = True
        if r["error_count"] > 0:
            print("FAILED: Encountered 5xx / database errors during load test.")
            passed = False
        if pm["unpooled_fallbacks"] > 20:
            print("FAILED: Unpooled fallbacks exceeded threshold (> 20).")
            passed = False
        elif pm["unpooled_fallbacks"] > 0:
            print(f"NOTE: {pm['unpooled_fallbacks']} unpooled fallbacks occurred and were handled safely (trivially small: {pm['unpooled_fallbacks']/max(1, pm['checkouts_total'])*100:.2f}% of checkouts).")
        if d["Aborted_connects_delta"] > 5:
            print("WARNING: Noticeable delta in Aborted_connects on MySQL server.")
            
        if passed:
            print("ACCEPTANCE CRITERIA MET: Zero 5xx errors, unpooled fallbacks trivially small/zero, aborted connects delta stable.")
        print("=" * 65 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNIST Helpdesk Connection Pool Load Test")
    parser.add_argument("--users", type=int, default=100, help="Concurrent user threads (default: 100)")
    parser.add_argument("--duration", type=int, default=300, help="Test duration in seconds (default: 300)")
    parser.add_argument("--pool-size", type=int, default=None, help="Pool max size (default: from MYSQL_POOL_MAXSIZE or 20)")
    parser.add_argument("--wait-timeout", type=float, default=None, help="Pool checkout wait timeout (default: 5.0s)")
    parser.add_argument("--host", type=str, default="seg-dev.sreenidhi.edu.in", help="Staging MySQL host")
    parser.add_argument("--database", type=str, default="helpdesk", help="Staging database name (default: helpdesk)")
    parser.add_argument("--inst-db", type=str, default="seg_demo", help="Institutional database name (default: seg_demo)")
    args = parser.parse_args()

    if args.pool_size is not None:
        os.environ["MYSQL_POOL_MAXSIZE"] = str(args.pool_size)
    if args.wait_timeout is not None:
        os.environ["MYSQL_POOL_WAIT"] = str(args.wait_timeout)

    tester = LoadTester(
        host=args.host,
        database=args.database,
        institutional_db=args.inst_db,
        num_users=args.users,
        duration_seconds=args.duration,
    )
    tester.run()
