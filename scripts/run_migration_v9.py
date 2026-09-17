#!/usr/bin/env python3
"""
Migration v9 Runner: Database Integrity and Multi-Tenant Scoping.
Applies org_id columns and database-level integrity constraints idempotently.
"""
from __future__ import annotations

import argparse
import os
import sys
import pymysql
from dotenv import load_dotenv

load_dotenv()


def run_migration(host: str, user: str, password: str, database: str = "helpdesk", dry_run: bool = False):
    print("=" * 80)
    print(f"RUNNING MIGRATION V9 ON: {host}:3306 (DB: {database})")
    print(f"Mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")
    print("=" * 80)

    conn = pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor
    )

    with conn.cursor() as cur:
        # Step 1: Add org_id to tables if missing
        tables_for_org_id = [
            "helpdesk_categories",
            "helpdesk_ca_assignments",
            "helpdesk_staff_roles",
            "helpdesk_problem_types",
        ]

        print("\n1. CHECKING AND ADDING org_id COLUMNS")
        print("-" * 80)
        for tbl in tables_for_org_id:
            cur.execute("""
                SELECT COLUMN_NAME
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = 'org_id'
            """, (database, tbl))
            if cur.fetchone():
                print(f"  [{tbl}] Column 'org_id' already exists. Skipping.")
            else:
                stmt = f"ALTER TABLE `{tbl}` ADD COLUMN `org_id` VARCHAR(20) NOT NULL DEFAULT '2000'"
                if dry_run:
                    print(f"  [DRY-RUN] Would execute: {stmt}")
                else:
                    cur.execute(stmt)
                    print(f"  [{tbl}] Added column 'org_id' VARCHAR(20) NOT NULL DEFAULT '2000'.")

        # Step 2: Check and Add Constraints
        constraints = [
            {
                "name": "chk_tickets_assigned_created",
                "table": "helpdesk_tickets",
                "condition": "assigned_to > 0 AND created_by > 0",
                "violation_query": "SELECT id, title, created_by, assigned_to FROM helpdesk_tickets WHERE created_by <= 0 OR created_by IS NULL OR assigned_to <= 0 OR assigned_to IS NULL"
            },
            {
                "name": "chk_tickets_updated_after_created",
                "table": "helpdesk_tickets",
                "condition": "updated_at >= created_at",
                "violation_query": "SELECT id, title, created_at, updated_at FROM helpdesk_tickets WHERE updated_at < created_at"
            },
            {
                "name": "chk_activity_action_by",
                "table": "helpdesk_ticket_activity",
                "condition": "action_by > 0",
                "violation_query": "SELECT id, ticket_id, action_by FROM helpdesk_ticket_activity WHERE action_by <= 0 OR action_by IS NULL"
            },
            {
                "name": "chk_categories_assigned_ca",
                "table": "helpdesk_categories",
                "condition": "assigned_ca_id IS NULL OR assigned_ca_id > 0",
                "violation_query": "SELECT id, category_name, assigned_ca_id FROM helpdesk_categories WHERE assigned_ca_id IS NOT NULL AND assigned_ca_id <= 0"
            },
            {
                "name": "chk_ca_assignments_ca_id",
                "table": "helpdesk_ca_assignments",
                "condition": "ca_id > 0",
                "violation_query": "SELECT id, category_id, ca_id, block FROM helpdesk_ca_assignments WHERE ca_id <= 0 OR ca_id IS NULL"
            }
        ]

        print("\n2. CHECKING AND ADDING INTEGRITY CHECK CONSTRAINTS")
        print("-" * 80)
        for c in constraints:
            # Check existing constraint
            cur.execute("""
                SELECT CONSTRAINT_NAME
                FROM information_schema.TABLE_CONSTRAINTS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s
            """, (database, c["table"], c["name"]))
            if cur.fetchone():
                print(f"  [{c['table']}] Constraint '{c['name']}' already exists. Skipping.")
                continue

            # Verify no rows violate the condition
            cur.execute(c["violation_query"])
            violations = cur.fetchall()
            if violations:
                print(f"  [ERROR] Cannot add constraint '{c['name']}' on {c['table']}: {len(violations)} violating rows found!")
                for v in violations[:5]:
                    print(f"    Sample violation: {v}")
                raise RuntimeError(f"Constraint {c['name']} pre-check failed on {c['table']}")

            # Add constraint
            stmt = f"ALTER TABLE `{c['table']}` ADD CONSTRAINT `{c['name']}` CHECK ({c['condition']})"
            if dry_run:
                print(f"  [DRY-RUN] Pre-check passed. Would execute: {stmt}")
            else:
                cur.execute(stmt)
                print(f"  [{c['table']}] Added constraint '{c['name']}' (CHECK: {c['condition']}).")

    conn.close()
    print("\n" + "=" * 80)
    print(f"MIGRATION V9 SUCCESSFUL ON {host}")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Migration v9 Runner")
    parser.add_argument("--host", default=os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in"), help="Target DB host")
    parser.add_argument("--user", default=os.getenv("MYSQL_USER", "demo"), help="Target DB user")
    parser.add_argument("--password", default=os.getenv("MYSQL_PASSWORD", "Admin@321#"), help="Target DB password")
    parser.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "helpdesk"), help="Target DB name")
    parser.add_argument("--dry-run", action="store_true", help="Perform dry run only")
    args = parser.parse_args()

    run_migration(args.host, args.user, args.password, args.database, args.dry_run)


if __name__ == "__main__":
    main()
