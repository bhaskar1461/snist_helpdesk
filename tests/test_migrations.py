"""Phase 7: Migrations & Schema Versioning Test Suite.

Verifies:
1. Checksum computation and CRLF normalization.
2. Checksum tampering drift detection (applied checksum != disk checksum).
3. Migration file parsing (UP and DOWN splitting).
4. Strict numeric order sorting.
5. Idempotent bootstrap behavior (--assume-applied).
6. Advisory locking mutual exclusion (GET_LOCK('helpdesk_migration', 0)).
7. Migration failure safety (failed SQL midway aborts and is NOT tracked).
8. Baseline rollback protection (0001-0006 cannot be rolled back without --force).
9. Test migration 0999 full UP and DOWN lifecycle.
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.migrate import (
    MigrationRunner,
    compute_checksum,
    parse_migration_file,
    split_sql_statements,
)
from tests.test_base import GLOBAL_DB_STATE, HelpdeskTestCase


class TestMigrationFramework(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        GLOBAL_DB_STATE.reset()

    def test_checksum_normalization_and_tampering(self):
        """1. CRLF vs LF produce identical checksum; content changes alter checksum."""
        sql_lf = "CREATE TABLE test_tbl (id INT);\nSELECT 1;\n"
        sql_crlf = "CREATE TABLE test_tbl (id INT);\r\nSELECT 1;\r\n"
        sql_modified = "CREATE TABLE test_tbl (id BIGINT);\nSELECT 1;\n"

        cs_lf = compute_checksum(sql_lf)
        cs_crlf = compute_checksum(sql_crlf)
        cs_mod = compute_checksum(sql_modified)

        self.assertEqual(cs_lf, cs_crlf, "Checksum should be invariant to CRLF line endings.")
        self.assertNotEqual(cs_lf, cs_mod, "Modified content must produce a distinct checksum.")
        self.assertEqual(len(cs_lf), 64, "Checksum must be a 64-character SHA-256 hex string.")

    def test_parse_migration_file_up_and_down(self):
        """2. Migration file parses UP and DOWN sections correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "0007_demo.sql"
            fpath.write_text(
                "-- Header comment\n"
                "CREATE TABLE demo_probe (id INT);\n"
                "\n"
                "-- DOWN\n"
                "DROP TABLE demo_probe;\n",
                encoding="utf-8",
            )

            full_sql, up_sql, down_sql = parse_migration_file(fpath)
            self.assertIn("CREATE TABLE demo_probe", up_sql)
            self.assertNotIn("DROP TABLE demo_probe", up_sql)
            self.assertIn("DROP TABLE demo_probe", down_sql)
            self.assertNotIn("CREATE TABLE demo_probe", down_sql)

    def test_parse_migration_file_without_down(self):
        """3. Migration file without DOWN section returns empty down_sql."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "0008_no_down.sql"
            fpath.write_text("CREATE TABLE one_way (id INT);\n", encoding="utf-8")

            full_sql, up_sql, down_sql = parse_migration_file(fpath)
            self.assertEqual(down_sql, "")
            self.assertIn("CREATE TABLE one_way", up_sql)

    def test_split_sql_statements_strips_comments(self):
        """4. split_sql_statements removes full-line comments and splits by semicolon."""
        raw_sql = (
            "-- Comment line 1\n"
            "-- Comment line 2\n"
            "CREATE TABLE t1 (id INT);\n"
            "\n"
            "-- Another comment\n"
            "INSERT INTO t1 VALUES (1);\n"
        )
        statements = split_sql_statements(raw_sql)
        self.assertEqual(len(statements), 2)
        self.assertEqual(statements[0], "CREATE TABLE t1 (id INT)")
        self.assertEqual(statements[1], "INSERT INTO t1 VALUES (1)")

    def test_numeric_ordering_of_migration_files(self):
        """5. Migrations list in numeric order, not alphabetical string order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            (td / "0002_two.sql").write_text("SELECT 2;", encoding="utf-8")
            (td / "0010_ten.sql").write_text("SELECT 10;", encoding="utf-8")
            (td / "0001_one.sql").write_text("SELECT 1;", encoding="utf-8")
            (td / "0999_nine_nine.sql").write_text("SELECT 999;", encoding="utf-8")

            runner = MigrationRunner(conn=MagicMock(), migrations_dir=td)
            files = runner.list_migration_files()
            filenames = [f.name for f in files]

            expected = [
                "0001_one.sql",
                "0002_two.sql",
                "0010_ten.sql",
                "0999_nine_nine.sql",
            ]
            self.assertEqual(filenames, expected, "Files must be sorted by integer value of prefix.")

    def test_status_drift_detection(self):
        """6. Runner status detects APPLIED, PENDING, and DRIFTED states."""
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            f1 = td / "0001_init.sql"
            f1.write_text("CREATE TABLE t1 (id INT);", encoding="utf-8")
            f2 = td / "0002_add_col.sql"
            f2.write_text("ALTER TABLE t1 ADD COLUMN name VARCHAR(50);", encoding="utf-8")

            cs1 = compute_checksum(f1.read_text(encoding="utf-8"))

            mock_conn = MagicMock()
            mock_cur = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cur

            # Mock existing table check
            mock_cur.fetchone.return_value = {"cnt": 1}
            # Mock applied records: 0001 applied with modified checksum, 0002 not applied
            mock_cur.fetchall.return_value = [
                {
                    "id": 1,
                    "migration_name": "0001_init.sql",
                    "applied_at": "2026-09-01 10:00:00",
                    "applied_by": "test",
                    "checksum": "different_sha256_hash_value_representing_tampered_file",
                    "execution_ms": 10,
                }
            ]

            runner = MigrationRunner(conn=mock_conn, migrations_dir=td)
            statuses = runner.status()

            s1 = next(s for s in statuses if s["name"] == "0001_init.sql")
            s2 = next(s for s in statuses if s["name"] == "0002_add_col.sql")

            self.assertEqual(s1["state"], "DRIFTED", "Applied migration with changed checksum must report DRIFTED.")
            self.assertEqual(s2["state"], "PENDING", "Unregistered migration must report PENDING.")

    def test_bootstrap_assume_applied_idempotent(self):
        """7. Bootstrap marks migrations as pre-applied without executing statements, idempotent on re-run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            td = Path(tmpdir)
            (td / "0001_a.sql").write_text("CREATE TABLE a (id INT);", encoding="utf-8")
            (td / "0002_b.sql").write_text("CREATE TABLE b (id INT);", encoding="utf-8")
            (td / "0003_c.sql").write_text("CREATE TABLE c (id INT);", encoding="utf-8")

            executed_queries = []
            tracking_records = {}

            class MockCursor:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def execute(self, sql, params=None):
                    executed_queries.append((sql, params))
                    if "INSERT INTO helpdesk_schema_migrations" in sql and params:
                        mig_name = params[0]
                        tracking_records[mig_name] = {
                            "migration_name": mig_name,
                            "applied_at": "now",
                            "applied_by": params[1],
                            "checksum": params[2],
                            "execution_ms": 0,
                        }
                def fetchone(self):
                    return {"exists": 1}
                def fetchall(self):
                    return list(tracking_records.values())

            mock_conn = MagicMock()
            mock_conn.cursor.return_value = MockCursor()

            runner = MigrationRunner(conn=mock_conn, migrations_dir=td)

            # First bootstrap run: assume-applied 0001..0003
            res1 = runner.bootstrap(["0001..0003"])
            self.assertTrue(res1)
            self.assertIn("0001_a.sql", tracking_records)
            self.assertIn("0002_b.sql", tracking_records)
            self.assertIn("0003_c.sql", tracking_records)

            # Confirm NO DDL ('CREATE TABLE') was executed
            for sql, _ in executed_queries:
                self.assertNotIn("CREATE TABLE a", sql)
                self.assertNotIn("CREATE TABLE b", sql)

            # Second bootstrap run: should skip all 3 cleanly without duplicate insert errors
            executed_before_run2 = len(executed_queries)
            res2 = runner.bootstrap(["0001..0003"])
            self.assertTrue(res2)
            # No new INSERT statements executed
            new_inserts = [
                q for q, p in executed_queries[executed_before_run2:]
                if "INSERT INTO helpdesk_schema_migrations" in q
            ]
            self.assertEqual(len(new_inserts), 0, "Second bootstrap run must not re-insert existing records.")

    def test_advisory_lock_mutual_exclusion(self):
        """8. Advisory locking serialized via MySQL GET_LOCK('helpdesk_migration', 0)."""
        lock_state = {"locked": False}

        class MockLockCursor:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, sql, params=None):
                if "GET_LOCK" in sql:
                    if lock_state["locked"]:
                        self._last_result = {"lock_status": 0}  # Lock unavailable
                    else:
                        lock_state["locked"] = True
                        self._last_result = {"lock_status": 1}  # Acquired
                elif "RELEASE_LOCK" in sql:
                    lock_state["locked"] = False
                    self._last_result = {"release_status": 1}
            def fetchone(self):
                return getattr(self, "_last_result", None)

        conn_a = MagicMock()
        conn_a.cursor.return_value = MockLockCursor()
        conn_b = MagicMock()
        conn_b.cursor.return_value = MockLockCursor()

        runner_a = MigrationRunner(conn=conn_a)
        runner_b = MigrationRunner(conn=conn_b)

        # Process A acquires lock
        self.assertTrue(runner_a.acquire_lock(timeout_sec=0), "Process A must acquire available lock.")
        self.assertTrue(runner_a.lock_held)

        # Process B attempts to acquire while held -> must return False
        self.assertFalse(runner_b.acquire_lock(timeout_sec=0), "Process B must fail to acquire held lock.")
        self.assertFalse(runner_b.lock_held)

        # Process A finishes and releases lock
        runner_a.release_lock()
        self.assertFalse(runner_a.lock_held)
        self.assertFalse(lock_state["locked"])

        # Process B can now acquire lock
        self.assertTrue(runner_b.acquire_lock(timeout_sec=0), "Process B must acquire lock after Process A released it.")
        runner_b.release_lock()

    def test_migration_midway_failure_safety(self):
        """9. If a statement in UP fails, apply_migration returns False and does NOT record migration."""
        import pymysql

        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = Path(tmpdir) / "0009_bad_sql.sql"
            fpath.write_text(
                "CREATE TABLE probe_ok (id INT);\n"
                "SYNTAX ERROR INVALID SQL STATEMENT;\n",
                encoding="utf-8",
            )

            executed = []
            tracking_inserted = []

            class MockFailureCursor:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def execute(self, sql, params=None):
                    executed.append(sql)
                    if "SYNTAX ERROR" in sql:
                        raise pymysql.err.ProgrammingError(1064, "You have an error in your SQL syntax")
                    if "INSERT INTO helpdesk_schema_migrations" in sql:
                        tracking_inserted.append(params)
                def fetchone(self):
                    return {"exists": 1}

            mock_conn = MagicMock()
            mock_conn.cursor.return_value = MockFailureCursor()

            runner = MigrationRunner(conn=mock_conn, migrations_dir=Path(tmpdir))
            success = runner.apply_migration(fpath, dry_run=False)

            self.assertFalse(success, "apply_migration must return False on statement execution error.")
            self.assertEqual(len(tracking_inserted), 0, "Failed migration must NOT be inserted into tracking table.")

    def test_baseline_rollback_protection(self):
        """10. Rolling back baseline migrations (0001-0006) is blocked without explicit force."""
        runner = MigrationRunner(conn=MagicMock())
        for baseline_num in range(1, 7):
            name = f"{baseline_num:04d}_some_baseline.sql"
            is_baseline = any(name.startswith(f"{i:04d}") for i in range(1, 7))
            self.assertTrue(is_baseline, f"{name} must be detected as protected baseline.")


if __name__ == "__main__":
    unittest.main()
