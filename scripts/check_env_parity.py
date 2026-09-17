#!/usr/bin/env python3
"""
scripts/check_env_parity.py
Compares staging vs production environment parity and validates:
1. Row counts for all 8 helpdesk_* tables on both hosts (side-by-side table).
2. Categories with assigned_ca_id IS NULL on production -> MUST be 0.
3. helpdesk_ca_assignments count on production -> MUST equal staging's 622.
4. Orphan check: any ca_assignments row whose category_id or ca_id doesn't exist on production -> MUST be 0.
5. Exit code 1 if any critical check fails, 0 if healthy.
"""

import os
import sys
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

CORE_TABLES = [
    "helpdesk_categories",
    "helpdesk_ca_assignments",
    "helpdesk_staff_roles",
    "helpdesk_problem_types",
    "helpdesk_tickets",
    "helpdesk_ticket_activity",
    "helpdesk_ticket_notes",
    "helpdesk_audit_events",
]

def check_parity():
    src_host = os.getenv("MYSQL_SOURCE_HOST", "seg-dev.sreenidhi.edu.in")
    src_port = int(os.getenv("MYSQL_SOURCE_PORT", os.getenv("MYSQL_PORT", "3306")))
    src_user = os.getenv("MYSQL_SOURCE_USER", os.getenv("MYSQL_USER", "demo"))
    src_pwd = os.getenv("MYSQL_SOURCE_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
    src_db = os.getenv("MYSQL_SOURCE_DB", "helpdesk")

    tgt_host = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in")
    tgt_port = int(os.getenv("MYSQL_PORT", "3306"))
    tgt_user = os.getenv("MYSQL_USER", "demo")
    tgt_pwd = os.getenv("MYSQL_PASSWORD", "")
    tgt_db = os.getenv("MYSQL_DATABASE", "helpdesk")

    print("================================================================================")
    print("SNIST HELPDESK ENVIRONMENT PARITY CHECK")
    print(f"Staging (Source):    {src_host}:{src_port} (DB: {src_db})")
    print(f"Production (Target): {tgt_host}:{tgt_port} (DB: {tgt_db})")
    print("================================================================================\n")

    src_conn = pymysql.connect(
        host=src_host, port=src_port, user=src_user, password=src_pwd, database=src_db,
        cursorclass=pymysql.cursors.DictCursor
    )
    tgt_conn = pymysql.connect(
        host=tgt_host, port=tgt_port, user=tgt_user, password=tgt_pwd, database=tgt_db,
        cursorclass=pymysql.cursors.DictCursor
    )

    failures = []

    # 1. Row counts side-by-side
    print("1. ROW COUNTS FOR CORE HELPDESK TABLES (STAGING vs PRODUCTION)")
    print("-" * 80)
    print(f"{'Table Name':<30} | {'Staging':>12} | {'Production':>12} | {'Status':<15}")
    print("-" * 80)

    src_counts = {}
    tgt_counts = {}

    with src_conn.cursor() as s_cur, tgt_conn.cursor() as t_cur:
        for t in CORE_TABLES:
            try:
                s_cur.execute(f"SELECT COUNT(*) AS cnt FROM `{t}`")
                s_cnt = s_cur.fetchone()["cnt"]
            except Exception as e:
                s_cnt = f"ERR: {e}"

            try:
                t_cur.execute(f"SELECT COUNT(*) AS cnt FROM `{t}`")
                t_cnt = t_cur.fetchone()["cnt"]
            except Exception as e:
                t_cnt = f"ERR: {e}"

            src_counts[t] = s_cnt
            tgt_counts[t] = t_cnt

            status = "OK"
            if t in ("helpdesk_tickets", "helpdesk_ticket_activity", "helpdesk_ticket_notes", "helpdesk_audit_events"):
                status = "Live (Isolated)"
            elif s_cnt != t_cnt and t == "helpdesk_ca_assignments":
                status = "MISMATCH"
            elif t == "helpdesk_categories":
                status = "OK (Prod+Staging)"
            elif t == "helpdesk_problem_types":
                status = "Prod Initialized"

            print(f"{t:<30} | {str(s_cnt):>12} | {str(t_cnt):>12} | {status:<15}")
    print("-" * 80)

    # 2. Check categories with assigned_ca_id IS NULL on production -> MUST be 0
    print("\n2. CATEGORIES ASSIGNED_CA_ID NULL CHECK (PRODUCTION)")
    with tgt_conn.cursor() as cur:
        cur.execute("SELECT id, category_name, department FROM helpdesk_categories WHERE assigned_ca_id IS NULL")
        null_cats = cur.fetchall()
        if null_cats:
            print(f"  FAILED: Found {len(null_cats)} categories with assigned_ca_id IS NULL:")
            for nc in null_cats[:10]:
                print(f"    - ID {nc['id']}: '{nc['category_name']}' ({nc['department']})")
            failures.append(f"{len(null_cats)} categories on production have NULL assigned_ca_id")
        else:
            print("  PASSED: 0 categories with assigned_ca_id IS NULL on production.")

    # 3. Check helpdesk_ca_assignments count on production -> MUST equal staging's 622
    print("\n3. CA ASSIGNMENTS COUNT VERIFICATION")
    stage_ca_cnt = src_counts.get("helpdesk_ca_assignments", 0)
    prod_ca_cnt = tgt_counts.get("helpdesk_ca_assignments", 0)
    if prod_ca_cnt == 622 and stage_ca_cnt == 622:
        print(f"  PASSED: helpdesk_ca_assignments on production is {prod_ca_cnt} (equals staging's 622).")
    else:
        msg = f"helpdesk_ca_assignments count on production ({prod_ca_cnt}) does not match staging's expected 622 (staging: {stage_ca_cnt})"
        print(f"  FAILED: {msg}")
        failures.append(msg)

    # 4. Orphan check on production:
    # Any ca_assignments row whose category_id or ca_id doesn't exist on production -> MUST be 0
    print("\n4. ORPHAN FOREIGN KEY INTEGRITY CHECK (PRODUCTION)")
    with tgt_conn.cursor() as cur:
        # Category check
        cur.execute("""
            SELECT a.id, a.category_id, a.ca_id
            FROM helpdesk_ca_assignments a
            LEFT JOIN helpdesk_categories c ON c.id = a.category_id
            WHERE c.id IS NULL
        """)
        orphan_cats = cur.fetchall()

        # CA check (must exist in teacher_info or helpdesk_staff_roles)
        cur.execute("""
            SELECT a.id, a.category_id, a.ca_id
            FROM helpdesk_ca_assignments a
            LEFT JOIN teacher_info t ON t.TEACHER_ID = a.ca_id
            LEFT JOIN helpdesk_staff_roles s ON (s.id = a.ca_id OR s.teacher_id = a.ca_id)
            WHERE t.TEACHER_ID IS NULL AND s.id IS NULL
        """)
        orphan_cas = cur.fetchall()

        if orphan_cats:
            print(f"  FAILED: Found {len(orphan_cats)} orphan category references in helpdesk_ca_assignments.")
            failures.append(f"{len(orphan_cats)} orphan category references in ca_assignments")
        else:
            print("  PASSED: 0 orphan category references.")

        if orphan_cas:
            print(f"  FAILED: Found {len(orphan_cas)} orphan CA references in helpdesk_ca_assignments.")
            failures.append(f"{len(orphan_cas)} orphan CA references in ca_assignments")
        else:
            print("  PASSED: 0 orphan CA references.")

    src_conn.close()
    tgt_conn.close()

    print("\n================================================================================")
    if failures:
        print("PARITY CHECK SUMMARY: FAILED")
        for f in failures:
            print(f"  - {f}")
        print("================================================================================")
        return 1
    else:
        print("PARITY CHECK SUMMARY: ALL CHECKS PASSED (HEALTHY)")
        print("================================================================================")
        return 0


if __name__ == "__main__":
    code = check_parity()
    sys.exit(code)
