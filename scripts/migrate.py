#!/usr/bin/env python3
"""SNIST Helpdesk — Lightweight, Zero-Dependency Database Migration Runner.

Guarantees:
1. Advisory locking: Uses MySQL GET_LOCK('helpdesk_migration', 0) to prevent 
   concurrent multi-worker deployment races (Granian --workers 2).
2. Checksum validation: Computes SHA-256 for drift detection on modified files.
3. Schema tracking: Stores applied migrations in `helpdesk_schema_migrations`.
4. Idempotency & Safe Execution: Single statement execution with exact timing.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = BASE_DIR / "sql" / "migrations"

try:
    import pymysql
    from dotenv import load_dotenv
except ModuleNotFoundError as exc:
    # Attempt transparent re-exec into project virtualenv if invoked via system Python
    if "MIGRATE_REEXEC" not in os.environ:
        os.environ["MIGRATE_REEXEC"] = "1"
        for venv_name in ["venv", ".venv"]:
            for py_bin in ["bin/python3", "bin/python", "Scripts/python.exe"]:
                candidate = BASE_DIR / venv_name / py_bin
                if candidate.is_file():
                    os.execv(str(candidate), [str(candidate), str(Path(__file__).resolve())] + sys.argv[1:])

    print(
        f"\n[ERROR] Missing required Python dependency: {exc.name}\n\n"
        "Please run this script using your virtual environment:\n"
        "  source venv/bin/activate   # or: source .venv/bin/activate\n"
        f"  python3 {' '.join(sys.argv)}\n\n"
        "Or invoke the virtual environment Python directly:\n"
        f"  ./venv/bin/python3 {' '.join(sys.argv)}\n"
        f"  # or: ./.venv/bin/python3 {' '.join(sys.argv)}\n\n"
        "Or install missing dependencies into the active environment:\n"
        "  pip install pymysql python-dotenv\n"
        "  # or: pip install -r requirements.txt\n",
        file=sys.stderr,
    )
    sys.exit(1)

TRACKING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS helpdesk_schema_migrations (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    migration_name VARCHAR(255) NOT NULL,
    applied_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    applied_by VARCHAR(100) NOT NULL,
    checksum CHAR(64) NOT NULL,
    execution_ms INT NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_migration_name (migration_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def compute_checksum(content: str) -> str:
    """Compute normalized SHA-256 checksum of SQL content (ignoring CRLF differences)."""
    normalized = content.replace("\r\n", "\n").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def split_sql_statements(sql: str) -> List[str]:
    """Split SQL file content into individual executable statements."""
    statements: List[str] = []
    current_statement: List[str] = []
    lines = sql.replace("\r\n", "\n").split("\n")

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        current_statement.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(current_statement).strip()
            if stmt.endswith(";"):
                stmt = stmt[:-1].strip()
            if stmt:
                statements.append(stmt)
            current_statement = []

    if current_statement:
        stmt = "\n".join(current_statement).strip()
        if stmt:
            statements.append(stmt)

    return statements


def parse_migration_file(path: Path) -> Tuple[str, str, str]:
    """Parse a migration file into (full_sql, up_sql, down_sql)."""
    content = path.read_text(encoding="utf-8")
    down_marker = re.search(r"^\s*--\s*DOWN\s*$", content, re.MULTILINE | re.IGNORECASE)
    if down_marker:
        up_sql = content[:down_marker.start()].strip()
        down_sql = content[down_marker.end():].strip()
    else:
        up_sql = content.strip()
        down_sql = ""
    return content, up_sql, down_sql


def get_db_connection(env_name: str = "prod", connect_timeout: int = 10) -> pymysql.Connection:
    """Establish a direct PyMySQL connection based on environment."""
    load_dotenv(BASE_DIR / ".env")

    if env_name.lower() in ("staging", "dev", "seg-dev"):
        host = os.getenv("MYSQL_STAGING_HOST", "seg-dev.sreenidhi.edu.in")
        user = os.getenv("MYSQL_STAGING_USER", "demo")
        password = os.getenv("MYSQL_STAGING_PASSWORD", "Admin@321#")
        database = os.getenv("MYSQL_STAGING_DATABASE", "seg_demo")
        port = int(os.getenv("MYSQL_STAGING_PORT", "3306"))
    else:
        host = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in")
        user = os.getenv("MYSQL_USER", "demo")
        password = os.getenv("MYSQL_PASSWORD", "Admin@321#")
        database = os.getenv("MYSQL_DATABASE", "helpdesk")
        port = int(os.getenv("MYSQL_PORT", "3306"))

    return pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
        connect_timeout=connect_timeout,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


class MigrationRunner:
    def __init__(self, conn: pymysql.Connection, migrations_dir: Path = MIGRATIONS_DIR):
        self.conn = conn
        self.migrations_dir = migrations_dir
        self.lock_held = False

    def acquire_lock(self, timeout_sec: int = 0) -> bool:
        """Acquire MySQL user advisory lock to serialize migrations."""
        with self.conn.cursor() as cur:
            cur.execute("SELECT GET_LOCK('helpdesk_migration', %s) AS lock_status", (timeout_sec,))
            res = cur.fetchone()
            status = res["lock_status"] if res else None
            self.lock_held = (status == 1)
            return self.lock_held

    def release_lock(self) -> None:
        """Release MySQL advisory lock."""
        if self.lock_held:
            try:
                with self.conn.cursor() as cur:
                    cur.execute("SELECT RELEASE_LOCK('helpdesk_migration')")
            except Exception:
                pass
            finally:
                self.lock_held = False

    def ensure_tracking_table(self) -> None:
        """Ensure the helpdesk_schema_migrations table exists."""
        with self.conn.cursor() as cur:
            cur.execute(TRACKING_TABLE_SQL)

    def get_applied_migrations(self) -> Dict[str, Dict]:
        """Fetch all currently applied migrations from the tracking table (read-only)."""
        with self.conn.cursor() as cur:
            cur.execute("SHOW TABLES LIKE 'helpdesk_schema_migrations'")
            if not cur.fetchone():
                return {}
            cur.execute("SELECT id, migration_name, applied_at, applied_by, checksum, execution_ms FROM helpdesk_schema_migrations ORDER BY id ASC")
            rows = cur.fetchall()
            return {r["migration_name"]: r for r in rows}

    def list_migration_files(self) -> List[Path]:
        """List all .sql migration files in order of numeric prefix."""
        if not self.migrations_dir.exists():
            return []
        files = [p for p in self.migrations_dir.glob("*.sql") if re.match(r"^\d+_", p.name)]
        def _sort_key(p: Path) -> int:
            m = re.match(r"^(\d+)_", p.name)
            return int(m.group(1)) if m else 999999
        files.sort(key=_sort_key)
        return files

    def status(self) -> List[Dict]:
        """Calculate status for all migrations: applied, pending, or drifted."""
        applied = self.get_applied_migrations()
        files = self.list_migration_files()
        status_list = []

        for p in files:
            name = p.name
            full_sql, _, _ = parse_migration_file(p)
            current_checksum = compute_checksum(full_sql)

            if name in applied:
                record = applied[name]
                if record["checksum"] == current_checksum:
                    state = "APPLIED"
                else:
                    state = "DRIFTED"
                status_list.append({
                    "name": name,
                    "state": state,
                    "applied_at": record["applied_at"],
                    "applied_by": record["applied_by"],
                    "execution_ms": record["execution_ms"],
                    "path": p,
                })
            else:
                status_list.append({
                    "name": name,
                    "state": "PENDING",
                    "applied_at": None,
                    "applied_by": None,
                    "execution_ms": None,
                    "path": p,
                })

        return status_list

    def apply_migration(self, path: Path, dry_run: bool = False) -> bool:
        """Apply a single migration file."""
        name = path.name
        full_sql, up_sql, _ = parse_migration_file(path)
        checksum = compute_checksum(full_sql)
        statements = split_sql_statements(up_sql)

        if dry_run:
            print(f"\n[DRY RUN] Would execute {len(statements)} statements for {name}:")
            for idx, stmt in enumerate(statements, 1):
                preview = "\n  ".join(stmt.split("\n")[:3])
                print(f"  {idx}. {preview} ...")
            return True

        print(f"\nApplying migration: {name} ({len(statements)} statement(s))...")
        user = getpass.getuser()
        start_time = time.time()

        with self.conn.cursor() as cur:
            for idx, stmt in enumerate(statements, 1):
                try:
                    cur.execute(stmt)
                except pymysql.Error as exc:
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    print(f"\n[MIGRATION FAILED] {name} at statement #{idx}:")
                    print(f"  Error {exc.args[0]}: {exc.args[1]}")
                    print(f"  Statement:\n{stmt}")
                    return False

            elapsed_ms = int((time.time() - start_time) * 1000)
            self.ensure_tracking_table()
            cur.execute(
                """
                INSERT INTO helpdesk_schema_migrations 
                    (migration_name, applied_by, checksum, execution_ms)
                VALUES (%s, %s, %s, %s)
                """,
                (name, user, checksum, elapsed_ms),
            )

        print(f"  [OK] Applied {name} in {elapsed_ms}ms.")
        return True

    def rollback_migration(self, path: Path, dry_run: bool = False) -> bool:
        """Rollback a single migration file using its -- DOWN section."""
        name = path.name
        _, _, down_sql = parse_migration_file(path)

        if not down_sql:
            print(f"[ROLLBACK ABORTED] Migration {name} has no '-- DOWN' rollback section.")
            return False

        statements = split_sql_statements(down_sql)

        if dry_run:
            print(f"\n[DRY RUN] Would execute {len(statements)} rollback statements for {name}:")
            for idx, stmt in enumerate(statements, 1):
                print(f"  {idx}. {stmt[:100]} ...")
            return True

        print(f"\nRolling back migration: {name} ({len(statements)} statement(s))...")
        start_time = time.time()

        with self.conn.cursor() as cur:
            for idx, stmt in enumerate(statements, 1):
                try:
                    cur.execute(stmt)
                except pymysql.Error as exc:
                    print(f"\n[ROLLBACK FAILED] {name} at statement #{idx}:")
                    print(f"  Error {exc.args[0]}: {exc.args[1]}")
                    print(f"  Statement:\n{stmt}")
                    return False

            cur.execute("DELETE FROM helpdesk_schema_migrations WHERE migration_name = %s", (name,))

        elapsed_ms = int((time.time() - start_time) * 1000)
        print(f"  [OK] Rolled back {name} in {elapsed_ms}ms.")
        return True

    def bootstrap(self, assume_applied_targets: List[str]) -> bool:
        """Mark existing migrations as applied without executing DDL."""
        self.ensure_tracking_table()
        all_files = self.list_migration_files()
        already_applied = self.get_applied_migrations()
        user = getpass.getuser()

        selected_files: List[Path] = []
        for target in assume_applied_targets:
            target_clean = target.strip()
            # Support '0001..0005' range syntax
            if ".." in target_clean:
                start_s, end_s = target_clean.split("..")
                start_n = int(start_s)
                end_n = int(end_s)
                for f in all_files:
                    m = re.match(r"^(\d+)_", f.name)
                    if m and start_n <= int(m.group(1)) <= end_n:
                        if f not in selected_files:
                            selected_files.append(f)
            else:
                for f in all_files:
                    if f.name.startswith(target_clean) or f.name == target_clean:
                        if f not in selected_files:
                            selected_files.append(f)

        if not selected_files:
            print("[BOOTSTRAP WARNING] No matching migration files found for targets.")
            return False

        with self.conn.cursor() as cur:
            for path in selected_files:
                name = path.name
                if name in already_applied:
                    print(f"  - {name} is already registered in tracking table. Skipping.")
                    continue

                full_sql, _, _ = parse_migration_file(path)
                checksum = compute_checksum(full_sql)

                cur.execute(
                    """
                    INSERT INTO helpdesk_schema_migrations 
                        (migration_name, applied_by, checksum, execution_ms)
                    VALUES (%s, %s, %s, 0)
                    """,
                    (name, f"{user} (bootstrap)", checksum),
                )
                print(f"  [OK] Bootstrapped {name} as pre-applied (checksum: {checksum[:12]}...).")

        return True

    def repair(self, target: Optional[str] = None) -> bool:
        """Recalculate checksums and re-apply drifted migrations."""
        self.ensure_tracking_table()
        statuses = self.status()
        drifted = [s for s in statuses if s["state"] == "DRIFTED"]
        if not drifted:
            print("No drifted migrations detected.")
            return True

        user = getpass.getuser()
        for s in drifted:
            if target and not s["name"].startswith(target):
                continue
            name = s["name"]
            path = s["path"]
            full_sql, up_sql, _ = parse_migration_file(path)
            checksum = compute_checksum(full_sql)
            statements = split_sql_statements(up_sql)
            print(f"Repairing drifted migration: {name} ({len(statements)} statement(s))...")
            start_time = time.time()
            with self.conn.cursor() as cur:
                for idx, stmt in enumerate(statements, 1):
                    try:
                        cur.execute(stmt)
                    except pymysql.Error as exc:
                        print(f"  [REPAIR FAILED] {name} at statement #{idx}: {exc}")
                        return False
                elapsed_ms = int((time.time() - start_time) * 1000)
                cur.execute(
                    "UPDATE helpdesk_schema_migrations SET checksum = %s, execution_ms = %s, applied_by = %s WHERE migration_name = %s",
                    (checksum, elapsed_ms, f"{user} (repaired)", name),
                )
            print(f"  [OK] Successfully repaired {name} and synchronized checksum.")
        return True


def print_status_table(status_list: List[Dict]) -> None:
    """Format and print the migration status table."""
    print("=" * 80)
    print(f"{'MIGRATION NAME':<38} | {'STATUS':<12} | {'APPLIED AT':<20} | {'EXEC (ms)'}")
    print("=" * 80)
    for s in status_list:
        state = s["state"]
        if state == "APPLIED":
            badge = "[APPLIED]"
        elif state == "DRIFTED":
            badge = "[! DRIFTED]"
        else:
            badge = "[PENDING]"

        applied_str = str(s["applied_at"])[:19] if s["applied_at"] else "-"
        exec_str = str(s["execution_ms"]) if s["execution_ms"] is not None else "-"
        print(f"{s['name']:<38} | {badge:<12} | {applied_str:<20} | {exec_str}")
    print("=" * 80)


def check_pending_migrations(config=None, conn=None) -> Tuple[List[str], List[str]]:
    """
    Read-only check for pending or drifted migrations.
    Returns (pending_list, drifted_list).
    Does NOT acquire advisory lock or execute DDL.
    """
    close_conn = False
    if conn is None:
        if config is not None:
            conn = pymysql.connect(
                host=config.host,
                user=config.user,
                password=config.password,
                database=config.database,
                port=config.port,
                connect_timeout=5,
                autocommit=True,
                cursorclass=pymysql.cursors.DictCursor,
            )
            close_conn = True
        else:
            conn = get_db_connection()
            close_conn = True

    try:
        runner = MigrationRunner(conn)
        statuses = runner.status()
        pending = [s["name"] for s in statuses if s["state"] == "PENDING"]
        drifted = [s["name"] for s in statuses if s["state"] == "DRIFTED"]
        return pending, drifted
    finally:
        if close_conn and conn:
            try:
                conn.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="SNIST Helpdesk Database Migration Runner")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # status command
    p_status = subparsers.add_parser("status", help="Show migration status table")
    p_status.add_argument("--env", default="prod", choices=["prod", "staging"], help="Target environment")

    # up command
    p_up = subparsers.add_parser("up", help="Apply pending migrations")
    p_up.add_argument("--target", type=str, help="Target specific migration name or prefix")
    p_up.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    p_up.add_argument("--env", default="prod", choices=["prod", "staging"], help="Target environment")

    # down command
    p_down = subparsers.add_parser("down", help="Rollback migrations using -- DOWN section")
    p_down.add_argument("--target", type=str, required=False, default=None, help="Target migration name to rollback (defaults to latest applied)")
    p_down.add_argument("--force", action="store_true", help="Force rollback even on baseline migrations (0001-0006)")
    p_down.add_argument("--dry-run", action="store_true", help="Print statements without executing")
    p_down.add_argument("--env", default="prod", choices=["prod", "staging"], help="Target environment")

    # bootstrap command
    p_boot = subparsers.add_parser("bootstrap", help="Mark existing migrations as applied without executing DDL")
    p_boot.add_argument("--assume-applied", required=True, nargs="+", help="Migration names, prefixes, or ranges (e.g., 0001..0005)")
    p_boot.add_argument("--env", default="prod", choices=["prod", "staging"], help="Target environment")

    # repair command
    p_repair = subparsers.add_parser("repair", help="Recalculate checksums and re-apply drifted migrations")
    p_repair.add_argument("--target", type=str, help="Target specific migration name or prefix (e.g., 0006)")
    p_repair.add_argument("--env", default="prod", choices=["prod", "staging"], help="Target environment")

    args = parser.parse_args()
    is_dry_run = getattr(args, "dry_run", False) or ("--dry-run" in sys.argv)

    try:
        conn = get_db_connection(args.env)
    except Exception as exc:
        print(f"[FATAL ERROR] Could not connect to database ({args.env}): {exc}", file=sys.stderr)
        sys.exit(1)

    runner = MigrationRunner(conn)

    # 1. Acquire advisory lock for write commands
    if args.command in ("up", "down", "bootstrap", "repair") and not is_dry_run:
        print("Acquiring migration advisory lock ('helpdesk_migration')...")
        if not runner.acquire_lock(timeout_sec=0):
            print(
                "[ERROR] Could not acquire migration lock 'helpdesk_migration'.\n"
                "Another migration or application deployment is currently in progress.\n"
                "Exiting to prevent race hazard.",
                file=sys.stderr,
            )
            conn.close()
            sys.exit(1)
        print("Advisory lock acquired.")

    try:
        if args.command == "status":
            statuses = runner.status()
            print_status_table(statuses)
            has_pending = any(s["state"] == "PENDING" for s in statuses)
            has_drifted = any(s["state"] == "DRIFTED" for s in statuses)
            if has_drifted:
                print("\n[WARNING] Checksum drift detected on one or more applied migrations!", file=sys.stderr)
            if has_pending:
                print(f"\nThere are {sum(1 for s in statuses if s['state'] == 'PENDING')} pending migration(s).")
            else:
                print("\nDatabase schema is completely up-to-date.")

        elif args.command == "up":
            runner.ensure_tracking_table()
            statuses = runner.status()
            drifted = [s for s in statuses if s["state"] == "DRIFTED"]
            if drifted:
                names = ", ".join(s["name"] for s in drifted)
                print(
                    f"\n[ERROR] Migration integrity violation: Checksum drift detected on applied migration(s): {names}.\n"
                    f"An already-applied migration file on disk has been modified after being applied.\n"
                    f"Aborting to prevent schema corruption. Reconciliations must be applied as new numbered migrations.",
                    file=sys.stderr,
                )
                sys.exit(1)

            pending = [s for s in statuses if s["state"] == "PENDING"]

            if not pending:
                print("No pending migrations to apply.")
                sys.exit(0)

            for s in pending:
                if args.target and not s["name"].startswith(args.target):
                    continue
                success = runner.apply_migration(s["path"], dry_run=is_dry_run)
                if not success:
                    print(f"\nMigration chain halted on failure at {s['name']}.", file=sys.stderr)
                    sys.exit(1)

            print("\nAll pending migrations applied successfully.")

        elif args.command == "down":
            runner.ensure_tracking_table()
            statuses = runner.status()
            applied = [s for s in statuses if s["state"] == "APPLIED"]
            if not applied:
                print("[ERROR] No applied migrations available to roll back.", file=sys.stderr)
                sys.exit(1)

            if args.target:
                target_status = next((s for s in statuses if s["name"].startswith(args.target) or s["name"] == args.target), None)
                if not target_status:
                    print(f"[ERROR] Migration matching target '{args.target}' not found.", file=sys.stderr)
                    sys.exit(1)
            else:
                target_status = applied[-1]

            if target_status["state"] != "APPLIED":
                print(f"[ERROR] Migration {target_status['name']} is not in APPLIED state.", file=sys.stderr)
                sys.exit(1)

            # Baseline protection for core tables
            is_baseline = any(target_status["name"].startswith(f"{i:04d}") for i in range(1, 7))
            if is_baseline and not getattr(args, "force", False):
                print(
                    f"[ERROR] Safety Violation: Migration {target_status['name']} is part of the protected baseline (0001-0006).\n"
                    f"Rolling back core tables would destroy production data. Use --force if this is intentional.",
                    file=sys.stderr,
                )
                sys.exit(1)

            success = runner.rollback_migration(target_status["path"], dry_run=is_dry_run)
            if not success:
                sys.exit(1)

        elif args.command == "bootstrap":
            print(f"Bootstrapping migrations for {args.assume_applied}...")
            success = runner.bootstrap(args.assume_applied)
            if not success:
                sys.exit(1)
            print("\nBootstrap complete.")

        elif args.command == "repair":
            print("Repairing drifted migration(s)...")
            success = runner.repair(target=getattr(args, "target", None))
            if not success:
                sys.exit(1)
            print("\nRepair complete.")

    finally:
        runner.release_lock()
        conn.close()


if __name__ == "__main__":
    main()
