#!/usr/bin/env python3
"""
Archive and safely drop obsolete demo and duplicate tables from seg_demo.
In accordance with the Accidental Data Loss Prevention skill and SNIST ERP Project Rules,
this script backs up table structures and rows before performing any DROP operation.

Tables targeted for archiving & removal:
- demo_ca_assignments (0 rows, obsolete)
- demo_sys_administrators (20 rows, obsolete legacy 2025 demo table)
- demo_sys_complaint (98 rows, obsolete legacy Aug 2025 demo complaints)
- demo_users (9 rows, obsolete legacy demo accounts)
- helpdesk_locations (0 rows, duplicate empty table; institutional location table is used)
- helpdesk_ca_locations (0 rows, duplicate empty table)
"""

import os
import sys
import argparse
import datetime
import urllib.parse
from pathlib import Path
from sqlalchemy import create_engine, text

HOST = os.getenv("MYSQL_HOST", "seg-dev.sreenidhi.edu.in")
USER = os.getenv("MYSQL_USER", "demo")
PWD = os.getenv("MYSQL_PASSWORD", "Admin@321#")
PWD_ENC = urllib.parse.quote_plus(PWD)
PORT = int(os.getenv("MYSQL_PORT", "3306"))
DATABASE = "seg_demo"

TABLES_TO_ARCHIVE = [
    "demo_ca_assignments",
    "demo_sys_administrators",
    "demo_sys_complaint",
    "demo_users",
    "helpdesk_locations",
    "helpdesk_ca_locations",
]

def archive_and_drop(confirm_drop=False):
    db_url = f"mysql+pymysql://{USER}:{PWD_ENC}@{HOST}:{PORT}/{DATABASE}"
    engine = create_engine(db_url)
    conn = engine.connect()

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(__file__).resolve().parent.parent / "sql"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f"backup_demo_tables_{timestamp}.sql"

    print(f"[1/3] Archiving obsolete demo tables from `{DATABASE}` to {backup_file}...")
    
    with open(backup_file, "w", encoding="utf-8") as f:
        f.write(f"-- SNIST Help Desk Obsolete Demo Tables Backup\n")
        f.write(f"-- Database: {DATABASE}\n")
        f.write(f"-- Created: {datetime.datetime.now().isoformat()}\n\n")
        f.write("SET FOREIGN_KEY_CHECKS = 0;\n\n")

        for tbl in TABLES_TO_ARCHIVE:
            # Check if table exists
            exists = conn.execute(
                text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :tbl"),
                {"db": DATABASE, "tbl": tbl}
            ).scalar()

            if not exists:
                print(f"  - Table `{tbl}` does not exist in `{DATABASE}`. Skipping.")
                continue

            # Fetch CREATE TABLE statement
            create_stmt_row = conn.execute(text(f"SHOW CREATE TABLE `{tbl}`")).fetchone()
            create_stmt = create_stmt_row[1] if create_stmt_row else ""

            # Fetch rows
            rows = conn.execute(text(f"SELECT * FROM `{tbl}`")).fetchall()
            row_count = len(rows)
            print(f"  - Archiving `{tbl}`: {row_count} rows...")

            f.write(f"-- Table: `{tbl}` ({row_count} rows)\n")
            f.write(f"DROP TABLE IF EXISTS `{tbl}`;\n")
            f.write(f"{create_stmt};\n\n")

            if row_count > 0:
                cols = [c[0] for c in conn.execute(text(f"DESCRIBE `{tbl}`")).fetchall()]
                col_names = ", ".join([f"`{c}`" for c in cols])
                for r in rows:
                    vals = []
                    for v in r:
                        if v is None:
                            vals.append("NULL")
                        elif isinstance(v, (int, float)):
                            vals.append(str(v))
                        else:
                            clean_v = str(v).replace("'", "''").replace("\\", "\\\\")
                            vals.append(f"'{clean_v}'")
                    val_str = ", ".join(vals)
                    f.write(f"INSERT INTO `{tbl}` ({col_names}) VALUES ({val_str});\n")
                f.write("\n")

        f.write("SET FOREIGN_KEY_CHECKS = 1;\n")

    print(f"[2/3] Backup completed successfully: {backup_file} ({backup_file.stat().st_size} bytes)")

    if not confirm_drop:
        print("\n[3/3] DRY-RUN MODE: No tables were dropped.")
        print("To execute DROP TABLE on verified demo tables, run:")
        print("  python scripts/archive_and_drop_demo_tables.py --confirm-drop")
        conn.close()
        return

    print("\n[3/3] Executing safe DROP TABLE on obsolete demo tables...")
    for tbl in TABLES_TO_ARCHIVE:
        exists = conn.execute(
            text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :tbl"),
            {"db": DATABASE, "tbl": tbl}
        ).scalar()
        if exists:
            conn.execute(text(f"DROP TABLE IF EXISTS `{DATABASE}`.`{tbl}`"))
            print(f"  [OK] Dropped table `{DATABASE}`.`{tbl}`")
        else:
            print(f"  - Table `{tbl}` already removed.")

    conn.commit()
    print("\nAll obsolete demo tables safely dropped. Production institutional tables remain intact.")
    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Archive and drop obsolete demo tables.")
    parser.add_argument("--confirm-drop", action="store_true", help="Execute DROP TABLE after backup.")
    args = parser.parse_args()
    archive_and_drop(confirm_drop=args.confirm_drop)
