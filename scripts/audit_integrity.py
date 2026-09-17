#!/usr/bin/env python3
"""
SNIST Helpdesk Database Integrity Audit
Audits relational referential integrity, orphan records, activity history,
and required field constraints on the target database.
Exits with code 0 if all checks pass, or 1 if any check fails.
"""
from __future__ import annotations

import argparse
import os
import sys
import pymysql
from dotenv import load_dotenv

load_dotenv()


def run_audit(host: str, user: str, password: str, database: str = "helpdesk") -> int:
    print("=" * 80)
    print("SNIST HELPDESK DATABASE INTEGRITY AUDIT")
    print(f"Target Database: {host}:3306 (DB: {database})")
    print("=" * 80)

    try:
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            cursorclass=pymysql.cursors.DictCursor
        )
    except Exception as exc:
        print(f"FAILED TO CONNECT: {exc}")
        return 1

    checks_passed = True

    with conn.cursor() as cur:
        # Check if local views or tables exist
        cur.execute("SHOW TABLES")
        tables = {list(r.values())[0].lower() for r in cur.fetchall()}
        has_teacher_info = "teacher_info" in tables
        has_location = "location" in tables
        has_helpdesk_users = "helpdesk_users" in tables

        # ----------------------------------------------------------------------
        # CHECK 1: Tickets with assigned_to or created_by not in staff directory
        # ----------------------------------------------------------------------
        print("\n1. TICKETS ASSIGNEE & CREATOR REFERENTIAL CHECK")
        print("-" * 80)
        if has_teacher_info:
            cur.execute("""
                SELECT t.id, t.title, t.created_by, t.assigned_to
                FROM helpdesk_tickets t
                LEFT JOIN teacher_info tc ON tc.TEACHER_ID = t.created_by
                LEFT JOIN helpdesk_staff_roles sc ON (sc.teacher_id = t.created_by OR sc.id = t.created_by)
                WHERE tc.TEACHER_ID IS NULL AND sc.id IS NULL
            """)
            invalid_creators = cur.fetchall()

            cur.execute("""
                SELECT t.id, t.title, t.created_by, t.assigned_to
                FROM helpdesk_tickets t
                LEFT JOIN teacher_info ta ON ta.TEACHER_ID = t.assigned_to
                LEFT JOIN helpdesk_staff_roles sa ON (sa.teacher_id = t.assigned_to OR sa.id = t.assigned_to)
                WHERE ta.TEACHER_ID IS NULL AND sa.id IS NULL
            """)
            invalid_assignees = cur.fetchall()
        else:
            cur.execute("""
                SELECT t.id, t.title, t.created_by
                FROM helpdesk_tickets t
                LEFT JOIN helpdesk_staff_roles sc ON (sc.teacher_id = t.created_by OR sc.id = t.created_by)
                WHERE sc.id IS NULL
            """)
            invalid_creators = cur.fetchall()

            cur.execute("""
                SELECT t.id, t.title, t.assigned_to
                FROM helpdesk_tickets t
                LEFT JOIN helpdesk_staff_roles sa ON (sa.teacher_id = t.assigned_to OR sa.id = t.assigned_to)
                WHERE sa.id IS NULL
            """)
            invalid_assignees = cur.fetchall()

        if not invalid_creators and not invalid_assignees:
            print("  PASSED: All tickets reference valid creators and assignees.")
        else:
            checks_passed = False
            print(f"  FAILED: {len(invalid_creators)} invalid creators, {len(invalid_assignees)} invalid assignees found.")
            for c in invalid_creators[:3]:
                print(f"    Orphan Creator: Ticket #{c['id']} (created_by: {c['created_by']})")
            for a in invalid_assignees[:3]:
                print(f"    Orphan Assignee: Ticket #{a['id']} (assigned_to: {a['assigned_to']})")

        # ----------------------------------------------------------------------
        # CHECK 2: Tickets category_id and location_id references
        # ----------------------------------------------------------------------
        print("\n2. TICKETS CATEGORY & LOCATION INTEGRITY CHECK")
        print("-" * 80)
        cur.execute("""
            SELECT t.id, t.title, t.category_id
            FROM helpdesk_tickets t
            LEFT JOIN helpdesk_categories c ON c.id = t.category_id
            WHERE c.id IS NULL
        """)
        invalid_cat_tickets = cur.fetchall()

        invalid_loc_tickets = []
        if has_location:
            cur.execute("""
                SELECT t.id, t.title, t.location_id
                FROM helpdesk_tickets t
                LEFT JOIN location loc ON loc.id = t.location_id
                WHERE t.location_id IS NOT NULL AND loc.id IS NULL
            """)
            invalid_loc_tickets = cur.fetchall()

        if not invalid_cat_tickets and not invalid_loc_tickets:
            print("  PASSED: All tickets reference valid categories and locations.")
        else:
            checks_passed = False
            if invalid_cat_tickets:
                print(f"  FAILED: {len(invalid_cat_tickets)} tickets reference non-existent categories.")
                for ic in invalid_cat_tickets[:3]:
                    print(f"    Ticket #{ic['id']} -> category_id {ic['category_id']}")
            if invalid_loc_tickets:
                print(f"  FAILED: {len(invalid_loc_tickets)} tickets reference non-existent locations.")
                for il in invalid_loc_tickets[:3]:
                    print(f"    Ticket #{il['id']} -> location_id {il['location_id']}")

        # ----------------------------------------------------------------------
        # CHECK 3: ca_assignments orphan check
        # ----------------------------------------------------------------------
        print("\n3. CA ASSIGNMENTS ORPHAN CHECK")
        print("-" * 80)
        cur.execute("""
            SELECT a.id, a.category_id, a.ca_id
            FROM helpdesk_ca_assignments a
            LEFT JOIN helpdesk_categories c ON c.id = a.category_id
            WHERE c.id IS NULL
        """)
        orphan_assign_cats = cur.fetchall()

        if has_teacher_info:
            cur.execute("""
                SELECT a.id, a.category_id, a.ca_id
                FROM helpdesk_ca_assignments a
                LEFT JOIN teacher_info t ON t.TEACHER_ID = a.ca_id
                LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = a.ca_id OR s.id = a.ca_id)
                WHERE t.TEACHER_ID IS NULL AND s.id IS NULL
            """)
        else:
            cur.execute("""
                SELECT a.id, a.category_id, a.ca_id
                FROM helpdesk_ca_assignments a
                LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = a.ca_id OR s.id = a.ca_id)
                WHERE s.id IS NULL
            """)
        orphan_assign_cas = cur.fetchall()

        if not orphan_assign_cats and not orphan_assign_cas:
            print("  PASSED: Zero orphan CA assignment records.")
        else:
            checks_passed = False
            if orphan_assign_cats:
                print(f"  FAILED: {len(orphan_assign_cats)} ca_assignments reference missing categories.")
            if orphan_assign_cas:
                print(f"  FAILED: {len(orphan_assign_cas)} ca_assignments reference missing CAs.")

        # ----------------------------------------------------------------------
        # CHECK 4: Categories pointing to inactive CAs
        # ----------------------------------------------------------------------
        print("\n4. CATEGORIES INACTIVE CA CHECK")
        print("-" * 80)
        # Check if any assigned_ca_id belongs to a deactivated user (is_active = 0)
        user_join = "LEFT JOIN helpdesk_users u ON u.id = c.assigned_ca_id" if has_helpdesk_users else ""
        user_filter = "OR (u.id IS NOT NULL AND u.is_active = 0)" if has_helpdesk_users else ""
        cur.execute(f"""
            SELECT c.id, c.category_name, c.assigned_ca_id,
                   s.name AS staff_name, s.is_active AS staff_is_active
            FROM helpdesk_categories c
            LEFT JOIN helpdesk_staff_roles s ON (s.teacher_id = c.assigned_ca_id OR s.id = c.assigned_ca_id)
            {user_join}
            WHERE c.assigned_ca_id IS NOT NULL
              AND (
                  (s.id IS NOT NULL AND s.is_active = 0)
                  {user_filter}
              )
        """)
        inactive_ca_cats = cur.fetchall()

        if not inactive_ca_cats:
            print("  PASSED: Zero categories assigned to inactive CAs.")
        else:
            checks_passed = False
            print(f"  FAILED: {len(inactive_ca_cats)} categories assigned to inactive CAs.")
            for ic in inactive_ca_cats[:3]:
                print(f"    Category '{ic['category_name']}' (ID: {ic['id']}) assigned to inactive CA {ic['assigned_ca_id']}")

        # ----------------------------------------------------------------------
        # CHECK 5: Tickets missing activity log (every ticket must have activity)
        # ----------------------------------------------------------------------
        print("\n5. TICKETS ACTIVITY EVENT INTEGRITY")
        print("-" * 80)
        cur.execute("""
            SELECT t.id, t.title, t.created_at
            FROM helpdesk_tickets t
            LEFT JOIN helpdesk_ticket_activity a ON a.ticket_id = t.id
            WHERE a.id IS NULL
        """)
        tickets_without_activity = cur.fetchall()

        if not tickets_without_activity:
            print("  PASSED: All tickets possess activity log records.")
        else:
            checks_passed = False
            print(f"  FAILED: {len(tickets_without_activity)} tickets possess zero activity records.")
            for tw in tickets_without_activity[:3]:
                print(f"    Ticket #{tw['id']} ('{tw['title']}') has no activity events.")

        # ----------------------------------------------------------------------
        # CHECK 6: Duplicate submission_key values
        # ----------------------------------------------------------------------
        print("\n6. SUBMISSION KEY UNIQUENESS CHECK")
        print("-" * 80)
        cur.execute("""
            SELECT submission_key, COUNT(*) AS cnt
            FROM helpdesk_tickets
            WHERE submission_key IS NOT NULL AND TRIM(submission_key) != ''
            GROUP BY submission_key
            HAVING COUNT(*) > 1
        """)
        dup_keys = cur.fetchall()

        if not dup_keys:
            print("  PASSED: All submission_key values are globally unique.")
        else:
            checks_passed = False
            print(f"  FAILED: {len(dup_keys)} duplicate submission_key values found.")
            for dk in dup_keys[:3]:
                print(f"    Duplicate submission_key '{dk['submission_key']}': {dk['cnt']} tickets")

        # ----------------------------------------------------------------------
        # CHECK 7: NULL or empty required fields in helpdesk_tickets
        # ----------------------------------------------------------------------
        print("\n7. TICKETS REQUIRED FIELDS COMPLETENESS CHECK")
        print("-" * 80)
        cur.execute("""
            SELECT id, title, description, category_id, created_by, assigned_to, status, org_id
            FROM helpdesk_tickets
            WHERE title IS NULL OR TRIM(title) = ''
               OR description IS NULL OR TRIM(description) = ''
               OR category_id IS NULL
               OR created_by IS NULL
               OR assigned_to IS NULL
               OR status IS NULL
               OR org_id IS NULL OR TRIM(org_id) = ''
        """)
        incomplete_tickets = cur.fetchall()

        if not incomplete_tickets:
            print("  PASSED: All tickets have required fields (title, description, category, created_by, assigned_to, status, org_id) fully populated.")
        else:
            checks_passed = False
            print(f"  FAILED: {len(incomplete_tickets)} tickets have NULL or empty required fields.")
            for it in incomplete_tickets[:3]:
                print(f"    Incomplete Ticket #{it['id']}")

    conn.close()

    print("\n" + "=" * 80)
    if checks_passed:
        print("DATABASE INTEGRITY AUDIT: ALL 7 CHECKS PASSED (HEALTHY)")
        print("=" * 80)
        return 0
    else:
        print("DATABASE INTEGRITY AUDIT: INTEGRITY FAILURES DETECTED")
        print("=" * 80)
        return 1


def main():
    parser = argparse.ArgumentParser(description="SNIST Helpdesk Database Integrity Audit")
    parser.add_argument("--host", default=os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in"), help="Database host")
    parser.add_argument("--user", default=os.getenv("MYSQL_USER", "demo"), help="Database user")
    parser.add_argument("--password", default=os.getenv("MYSQL_PASSWORD", "Admin@321#"), help="Database password")
    parser.add_argument("--database", default=os.getenv("MYSQL_DATABASE", "helpdesk"), help="Database name")
    args = parser.parse_args()

    sys.exit(run_audit(args.host, args.user, args.password, args.database))


if __name__ == "__main__":
    main()
