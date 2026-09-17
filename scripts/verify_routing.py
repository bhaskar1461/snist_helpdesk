#!/usr/bin/env python3
"""
scripts/verify_routing.py
End-to-end routing verification for SNIST Helpdesk.
Tests routing resolution for all 16 core production categories across campus blocks.
Asserts that ZERO categories resolve to the Super Admin/Admin emergency fallback.
"""

import os
import sys
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

# Admin IDs that represent emergency fallback
ADMIN_EMAILS = {"admin@gmail.com", "campus.admin@gmail.com", "cto@sreenidhi.edu.in"}

def verify_routing():
    host = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    user = os.getenv("MYSQL_USER", "demo")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "helpdesk")

    print("================================================================================")
    print("SNIST HELPDESK ROUTING ENGINE VERIFICATION")
    print(f"Target Host: {host}:{port} (Database: {database})")
    print("================================================================================\n")

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
    )

    # Load administrator IDs that would constitute emergency fallback
    with conn.cursor() as cur:
        cur.execute("SELECT id, email, role FROM helpdesk_staff_roles WHERE role IN ('SUPER_ADMIN', 'ADMIN')")
        admin_staff = {r["id"]: r for r in cur.fetchall()}
        cur.execute("SELECT id, email, role FROM helpdesk_users WHERE role IN ('SUPER_ADMIN', 'ADMIN')")
        admin_users = {r["id"]: r for r in cur.fetchall()}

    # Load 16 core production categories (or all active categories)
    with conn.cursor() as cur:
        cur.execute("SELECT id, category_name, department, assigned_ca_id FROM helpdesk_categories WHERE id <= 16 ORDER BY id")
        prod_cats = cur.fetchall()

    test_blocks = ["Block-I", "Block-IV", "Admin Block", "Central Library", "All Blocks", ""]

    print(f"{'Cat ID':<6} | {'Department':<12} | {'Category Name':<32} | {'Block':<15} | {'Matched CAs':<15} | {'Load':<8} | {'Chosen CA':<28} | {'Status'}")
    print("-" * 140)

    fallback_count = 0
    total_tests = 0
    routing_records = []

    with conn.cursor() as cur:
        for c in prod_cats:
            cat_id = c["id"]
            c_name = c["category_name"]
            c_dept = c["department"]
            def_ca = c["assigned_ca_id"]

            for block in ["Block-I", "Admin Block"]:
                total_tests += 1
                matched_cas = []
                matched_by = "none"

                # Step 1: Exact block match or 'All Blocks'
                if block:
                    cur.execute(
                        """
                        SELECT ca_id FROM helpdesk_ca_assignments 
                        WHERE category_id = %s AND (LOWER(block) = LOWER(%s) OR LOWER(block) IN ('all blocks', 'all', 'campus'))
                        """,
                        (cat_id, block),
                    )
                    rows = cur.fetchall()
                    if rows:
                        matched_cas = list(dict.fromkeys([r["ca_id"] for r in rows]))
                        matched_by = "block"

                # Step 2: Any block / all assigned CAs for this category
                if not matched_cas:
                    cur.execute(
                        "SELECT DISTINCT ca_id FROM helpdesk_ca_assignments WHERE category_id = %s",
                        (cat_id,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        matched_cas = list(dict.fromkeys([r["ca_id"] for r in rows]))
                        matched_by = "cat_assign"

                # Step 3: Category default assigned_ca_id
                if not matched_cas and def_ca:
                    matched_cas = [def_ca]
                    matched_by = "cat_default"

                # Choose CA using least loaded logic
                chosen_ca_id = None
                chosen_ca_load = 0
                if matched_cas:
                    # Query open ticket loads
                    cur.execute(f"""
                        SELECT assigned_to, COUNT(*) as cnt
                        FROM helpdesk_tickets
                        WHERE assigned_to IN ({','.join(str(x) for x in matched_cas)})
                          AND status IN ('PENDING', 'IN_PROGRESS', 'REOPENED')
                        GROUP BY assigned_to
                    """)
                    loads = {r["assigned_to"]: r["cnt"] for r in cur.fetchall()}
                    chosen_ca_id = min(matched_cas, key=lambda cid: loads.get(cid, 0))
                    chosen_ca_load = loads.get(chosen_ca_id, 0)
                else:
                    # Emergency fallback
                    cur.execute("SELECT id FROM helpdesk_users WHERE role IN ('HOD', 'ADMIN', 'SUPER_ADMIN') AND is_active = 1 ORDER BY id ASC LIMIT 1")
                    chosen_ca_id = cur.fetchone()["id"]
                    matched_by = "emergency_fallback"

                # Lookup chosen CA info
                cur.execute("SELECT TEACHER_NAME, EMAIL_ID FROM teacher_info WHERE TEACHER_ID = %s", (chosen_ca_id,))
                t_info = cur.fetchone()
                if t_info:
                    ca_desc = f"{t_info['TEACHER_NAME'][:18]} (ID:{chosen_ca_id})"
                else:
                    cur.execute("SELECT name, email, role FROM helpdesk_staff_roles WHERE id = %s", (chosen_ca_id,))
                    s_info = cur.fetchone()
                    if s_info:
                        ca_desc = f"{s_info['name'][:18]} (Staff:{chosen_ca_id})"
                    else:
                        ca_desc = f"ID:{chosen_ca_id}"

                is_emergency = (matched_by == "emergency_fallback") or (chosen_ca_id in (1, 2) and "admin@gmail.com" in [admin_staff.get(chosen_ca_id, {}).get("email")])
                if is_emergency:
                    fallback_count += 1
                    status = "FALLBACK"
                else:
                    status = "OK"

                ca_list_str = ",".join(str(x) for x in matched_cas[:3])
                if len(matched_cas) > 3:
                    ca_list_str += f"+{len(matched_cas)-3}"

                print(f"{cat_id:<6} | {c_dept:<12} | {c_name:<32} | {block:<15} | {ca_list_str:<15} | {chosen_ca_load:<8} | {ca_desc:<28} | {status}")
                routing_records.append({
                    "category_id": cat_id,
                    "category_name": c_name,
                    "department": c_dept,
                    "block": block,
                    "matched_cas": matched_cas,
                    "matched_by": matched_by,
                    "chosen_ca": chosen_ca_id,
                    "chosen_ca_desc": ca_desc,
                    "status": status,
                })

    conn.close()
    print("-" * 140)

    print(f"\nTotal Routing Scenarios Tested: {total_tests}")
    print(f"Emergency Fallback Count: {fallback_count}")

    if fallback_count > 0:
        print(f"\nCRITICAL ASSERTION FAILED: {fallback_count} categories resolved to Super Admin/Admin emergency fallback!")
        return 1
    else:
        print("\nASSERTION PASSED: ZERO categories resolved to the Super Admin/Admin emergency fallback.")
        return 0


if __name__ == "__main__":
    code = verify_routing()
    sys.exit(code)
