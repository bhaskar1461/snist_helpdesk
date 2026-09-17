#!/usr/bin/env python3
"""
scripts/snapshot_before_seed.py
Pre-seed snapshot utility for SNIST Helpdesk.
Takes a complete SQL snapshot of tables to be modified and writes it to backups/pre_seed_<timestamp>.sql.gz
with pre-seed row counts embedded in the dump header.
"""

import os
import sys
import gzip
import datetime
from pathlib import Path
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

TABLES = [
    "helpdesk_categories",
    "helpdesk_ca_assignments",
    "helpdesk_staff_roles",
    "helpdesk_problem_types",
]

def snapshot():
    host = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "demo")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "helpdesk")

    backup_dir = Path(__file__).resolve().parent.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"pre_seed_{timestamp}.sql.gz"

    print("============================================================")
    print("SNIST Helpdesk Pre-Seed Snapshot")
    print(f"Host: {host}:{port} (Database: {database})")
    print(f"Target file: {backup_file}")
    print("============================================================")

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
    )

    row_counts = {}
    with conn.cursor() as cur:
        for t in TABLES:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM `{t}`")
            row_counts[t] = cur.fetchone()["cnt"]

    print("Pre-seed row counts:")
    for t, cnt in row_counts.items():
        print(f"  {t:26s}: {cnt} rows")

    lines = [
        "-- ============================================================\n",
        f"-- SNIST Helpdesk Pre-Seed Safety Snapshot\n",
        f"-- Database: {database} (Host: {host}:{port})\n",
        f"-- Timestamp: {datetime.datetime.now().isoformat()}\n",
        "-- Pre-seed row counts:\n",
    ]
    for t, cnt in row_counts.items():
        lines.append(f"--   {t}: {cnt} rows\n")
    lines.append("-- ============================================================\n\n")
    lines.append("SET FOREIGN_KEY_CHECKS = 0;\n\n")

    with conn.cursor() as cur:
        for t in TABLES:
            lines.append(f"-- Table structure for `{t}`\n")
            lines.append(f"DROP TABLE IF EXISTS `{t}`;\n")
            cur.execute(f"SHOW CREATE TABLE `{t}`")
            create_stmt = cur.fetchone()["Create Table"]
            lines.append(f"{create_stmt};\n\n")

            cur.execute(f"SELECT * FROM `{t}`")
            rows = cur.fetchall()
            if rows:
                lines.append(f"-- Dumping data for table `{t}` ({len(rows)} rows)\n")
                cols = list(rows[0].keys())
                col_str = ", ".join([f"`{c}`" for c in cols])
                for r in rows:
                    vals = []
                    for c in cols:
                        v = r[c]
                        if v is None:
                            vals.append("NULL")
                        elif isinstance(v, (int, float)):
                            vals.append(str(v))
                        else:
                            # escape single quotes and backslashes
                            v_str = str(v).replace("\\", "\\\\").replace("'", "\\'")
                            vals.append(f"'{v_str}'")
                    val_str = ", ".join(vals)
                    lines.append(f"INSERT INTO `{t}` ({col_str}) VALUES ({val_str});\n")
                lines.append("\n")

    lines.append("SET FOREIGN_KEY_CHECKS = 1;\n")
    conn.close()

    content = "".join(lines).encode("utf-8")
    with gzip.open(backup_file, "wb") as f_gz:
        f_gz.write(content)

    print(f"\nSnapshot completed successfully: {backup_file} ({len(content)} uncompressed bytes, {backup_file.stat().st_size} compressed bytes)")
    return backup_file

if __name__ == "__main__":
    snapshot()
