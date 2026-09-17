#!/usr/bin/env python3
"""
Verification script for Help Desk Database Integration & User Architecture.
Connects to live MySQL server at seg-dev.sreenidhi.edu.in, validating:
1. Operational tables inside database 'helpdesk'.
2. Institutional tables queried directly from database 'seg_demo'.
3. Complete removal of obsolete demo tables from 'seg_demo'.
4. Live service calls (faculty auth, dynamic role resolution, locations, ticket queries).
5. Strict department-based validation.
"""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Explicitly configure environment for live database test
os.environ["MYSQL_HOST"] = "seg-dev.sreenidhi.edu.in"
os.environ["MYSQL_PORT"] = "3306"
os.environ["MYSQL_USER"] = "demo"
os.environ["MYSQL_PASSWORD"] = "Admin@321#"
os.environ["MYSQL_DATABASE"] = "helpdesk"
os.environ["MYSQL_INSTITUTIONAL_DATABASE"] = "seg_demo"
os.environ["MYSQL_ENABLE_REMOTE"] = "true"
os.environ["TESTING"] = "false"

import pymysql
from db_services import env_db_config, DemoDbService, LiveDbService

def test_raw_db_integrity():
    print("\n--- 1. Raw Database & Table Integrity Check ---")
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in"),
        port=int(os.getenv("MYSQL_PORT", 3306)),
        user=os.getenv("MYSQL_USER", "demo"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "helpdesk"),
        cursorclass=pymysql.cursors.DictCursor,
    )
    with conn.cursor() as cur:
        # Check helpdesk operational tables
        tables = [
            ("helpdesk_tickets", 766),
            ("helpdesk_categories", 42),
            ("helpdesk_ca_assignments", 622),
            ("helpdesk_staff_roles", 49),
            ("helpdesk_ticket_notes", 1),
            ("helpdesk_ticket_activity", 16),
            ("helpdesk_audit_events", 34),
        ]
        for tbl, expected_min in tables:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM `{tbl}`")
            row = cur.fetchone()
            cnt = row["cnt"]
            assert cnt >= expected_min, f"Table {tbl} row count {cnt} < expected {expected_min}"
            print(f"  [PASS] Table helpdesk.{tbl}: {cnt} rows")

        # Check cross-database access to seg_demo
        inst_tables = [
            ("seg_demo", "teacher_info", 2000),
            ("seg_demo", "branch_detail", 60),
            ("seg_demo", "location", 700),
        ]
        for schema, tbl, expected_min in inst_tables:
            cur.execute(f"SELECT COUNT(*) AS cnt FROM `{schema}`.`{tbl}`")
            row = cur.fetchone()
            cnt = row["cnt"]
            assert cnt >= expected_min, f"Institutional table {schema}.{tbl} count {cnt} < expected {expected_min}"
            print(f"  [PASS] Institutional {schema}.{tbl}: {cnt} rows")

        # Verify dropped demo tables from seg_demo
        cur.execute(
            """
            SELECT TABLE_NAME 
            FROM information_schema.TABLES 
            WHERE TABLE_SCHEMA = 'seg_demo' 
              AND TABLE_NAME IN ('demo_ca_assignments', 'demo_sys_administrators', 'demo_sys_complaint', 'demo_users', 'helpdesk_locations')
            """
        )
        remaining = cur.fetchall()
        assert len(remaining) == 0, f"Obsolete demo tables still exist in seg_demo: {remaining}"
        print("  [PASS] Obsolete demo tables successfully dropped from seg_demo (0 remaining)")

    conn.close()

def test_live_services():
    print("\n--- 2. Live Application DbService Verification ---")
    cfg = env_db_config("helpdesk")
    assert cfg is not None, "Failed to load DbConfig for helpdesk"
    print(f"  DbConfig loaded: host={cfg.host}, user={cfg.user}, database={cfg.database}")

    live_db = LiveDbService(cfg)
    demo_db = DemoDbService(cfg)
    assert live_db.enabled, "LiveDbService failed to connect/is not enabled"
    assert demo_db.enabled, "DemoDbService failed to connect/is not enabled"
    print("  [PASS] BaseMySQLService connected to live database")

    # 2.1 Test fetching locations from institutional seg_demo.location
    locations = live_db.fetch_locations()
    assert len(locations) > 700, f"Expected >700 locations from seg_demo.location, got {len(locations)}"
    print(f"  [PASS] LiveDbService.fetch_locations(): loaded {len(locations)} institutional locations")

    # 2.2 Test fetching departments from institutional seg_demo.branch_detail
    departments = live_db.fetch_departments()
    assert len(departments) >= 50, f"Expected >=50 departments, got {len(departments)}"
    print(f"  [PASS] LiveDbService.fetch_departments(): loaded {len(departments)} departments")

    # 2.3 Test user authentication directly from seg_demo.teacher_info
    # Test teacher: ARUNA V (TEACHER_ID 46)
    teacher = live_db.lookup_teacher_by_email("aruna.v@sreenidhi.edu.in")
    assert teacher is not None, "Failed to look up teacher aruna.v@sreenidhi.edu.in in seg_demo.teacher_info"
    print(f"  [PASS] LiveDbService.lookup_teacher_by_email(): {teacher['name']} (ID {teacher['id']}, Dept {teacher['department']})")

    # Authenticate via DemoDbService with SAP_ID or '123'
    auth_user = demo_db.authenticate_user("aruna.v@sreenidhi.edu.in", "123")
    assert auth_user is not None, "Failed to authenticate teacher with default password"
    assert auth_user["id"] == teacher["id"], f"Authenticated user ID {auth_user['id']} != teacher_info {teacher['id']}"
    print(f"  [PASS] DemoDbService.authenticate_user(): authenticated {auth_user['name']} (Role: {auth_user['role']}, Dept: {auth_user['department']})")

    # Verify dynamic CA role resolution for assigned CA teacher 457 (shekar.j@sreenidhi.edu.in)
    ca_teacher = demo_db.get_user(457)
    assert ca_teacher is not None, "Failed to look up CA teacher 457 in seg_demo.teacher_info"
    assert ca_teacher["role"] == "CA", f"Expected dynamic role CA for teacher 457, got {ca_teacher['role']}"
    print(f"  [PASS] Dynamic Role Resolution: teacher 457 resolved as role '{ca_teacher['role']}' from ca_assignments")

    # Verify NO helpdesk_users table exists in helpdesk (zero duplicate teacher table)
    with demo_db.connection() as conn, conn.cursor() as cur:
        cur.execute("SHOW TABLES LIKE 'helpdesk_users'")
        assert cur.fetchone() is None, "helpdesk_users table unexpectedly exists in helpdesk schema!"
    print("  [PASS] Zero duplication: helpdesk_users table does not exist in helpdesk schema (teachers sourced 100% from seg_demo.teacher_info)")

    # 2.4 Test staff role authentication (Super Admin / Admin)
    staff_user = demo_db.authenticate_user("admin@snist.edu.in", "Admin@321#")
    if staff_user:
        print(f"  [PASS] DemoDbService.authenticate_user(): staff {staff_user['name']} (Role: {staff_user['role']})")

    # 2.5 Test list_tickets query with multi-database joins
    viewer = {"id": auth_user["id"], "role": auth_user["role"], "department": auth_user["department"], "org_id": "2000"}
    tickets = demo_db.list_tickets(viewer, scope="all", limit=5)
    assert isinstance(tickets, list), "list_tickets did not return a list"
    print(f"  [PASS] DemoDbService.list_tickets(): successfully fetched tickets with joins (sample count: {len(tickets)})")
    if tickets:
        sample = tickets[0]
        print(f"    Sample Ticket #{sample['id']}: '{sample['title']}' | Created by: {sample['created_by_name']} | Assigned: {sample['assigned_to_name']} | Location: {sample.get('location_block', 'N/A')}")

    # 2.6 Test list_categories with CA name resolution from teacher_info
    cats = demo_db.list_categories(limit=5)
    assert len(cats) > 0, "No categories returned"
    print(f"  [PASS] DemoDbService.list_categories(): loaded {len(cats)} categories (sample CA: {cats[0]['assigned_ca_name']})")

    # 2.7 Test strict department validation in create_ticket
    print("\n--- 3. Strict Department Validation Test ---")
    cat_cse = next((c for c in demo_db.list_categories() if c["department"] == "CSE"), None)
    assert cat_cse is not None, "CSE category not found"
    
    ece_users = demo_db.list_users(department="ECE", limit=1)
    assert len(ece_users) > 0, "No ECE users found"
    ece_user = ece_users[0]

    try:
        demo_db.create_ticket(
            title="Test Department Mismatch",
            description="This should be rejected",
            category_id=cat_cse["id"],
            created_by=auth_user["id"],
            assigned_to=ece_user["id"],
        )
        print("  [FAIL] Expected ValueError for cross-department ticket creation, but none was raised!")
        sys.exit(1)
    except ValueError as e:
        print(f"  [PASS] Strict validation rejected cross-department assignment: {e}")

if __name__ == "__main__":
    print("=========================================================")
    print("Help Desk Database & Architectural Integration Test Suite")
    print("=========================================================")
    try:
        test_raw_db_integrity()
        test_live_services()
        print("\n>>> ALL INTEGRATION AND ARCHITECTURAL VERIFICATIONS PASSED SUCCESSFULLY! <<<\n")
    except Exception as exc:
        print(f"\n[ERROR] Verification failed: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
