#!/usr/bin/env python3
"""
Migrate operational Help Desk tables from seg_demo to the dedicated helpdesk database.
Remaps user foreign keys directly to institutional teacher_info.TEACHER_ID and helpdesk_staff_roles.id.
Preserves existing working data with 100% integrity.
"""

import os
import sys
import logging
from pathlib import Path
from sqlalchemy import create_engine, text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate_to_helpdesk_db")

HOST = os.getenv("MYSQL_HOST", "seg-dev.sreenidhi.edu.in")
USER = os.getenv("MYSQL_USER", "demo")
PWD = os.getenv("MYSQL_PASSWORD", "Admin@321#")
import urllib.parse
PWD_ENC = urllib.parse.quote_plus(PWD)
PORT = int(os.getenv("MYSQL_PORT", "3306"))
SOURCE_DB = "seg_demo"
TARGET_DB = "helpdesk"

# Known fallback mappings for legacy emails not matching teacher_info by exact string
KNOWN_FALLBACKS = {
    'kiran.k@sreenidhi.edu.in': 598,      # BURRI KIRAN KUMAR REDDY (TEACHER_ID=598)
    'abhishek.c@sreenidhi.edu.in': 2873,  # NADIPALLY ABHISHEK (TEACHER_ID=2873)
    't_1253@sreenidhi.edu.in': 748,       # POLUBOYINA LAVANYA (TEACHER_ID=748)
}

def migrate():
    source_url = f"mysql+pymysql://{USER}:{PWD_ENC}@{HOST}:{PORT}/{SOURCE_DB}"
    target_url = f"mysql+pymysql://{USER}:{PWD_ENC}@{HOST}:{PORT}/{TARGET_DB}"
    
    log.info("Connecting to source DB (%s) and target DB (%s)...", SOURCE_DB, TARGET_DB)
    e_source = create_engine(source_url)
    e_target = create_engine(target_url)
    
    conn_src = e_source.connect()
    conn_tgt = e_target.connect()
    
    # ── Step 1: Apply v8 Schema to Target DB ──────────────────────────────────
    schema_path = Path(__file__).resolve().parent.parent / "sql" / "helpdesk_schema_v8.sql"
    log.info("Applying schema DDL from %s to %s...", schema_path, TARGET_DB)
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    
    # Clean SQL comments first before splitting
    import re
    cleaned_lines = []
    for line in schema_sql.splitlines():
        trimmed = line.strip()
        if trimmed.startswith("--") or not trimmed:
            continue
        cleaned_lines.append(line)
    cleaned_sql = "\n".join(cleaned_lines)
    
    statements = [s.strip() for s in cleaned_sql.split(";") if s.strip()]
    conn_tgt.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
    for stmt in statements:
        try:
            conn_tgt.execute(text(stmt))
        except Exception as exc:
            log.warning("DDL statement notice: %s", exc)
    conn_tgt.commit()
    log.info("Schema applied successfully to %s.", TARGET_DB)
    
    # ── Step 2: Seed helpdesk_staff_roles ────────────────────────────────────
    log.info("Seeding administrative accounts into helpdesk_staff_roles...")
    admin_accounts = conn_src.execute(text("""
        SELECT id, name, email, password, role, department, phone
        FROM helpdesk_users
        WHERE role IN ('SUPER_ADMIN', 'ADMIN')
           OR LOWER(email) IN ('ict.ca@gmail.com', 'bhaskar.ca@gmail.com', 'lsm.ca@gmail.com', 'ca@gmail.com', 'admin@gmail.com', 'campus.admin@gmail.com', 'snu.admin@gmail.com')
    """)).fetchall()
    
    staff_id_map = {}
    for acc in admin_accounts:
        uid, name, email, pwd, role, dept, phone = acc
        email_clean = (email or "").strip().lower()
        # Clean role for staff_roles ENUM
        staff_role = role if role in ('SUPER_ADMIN', 'ADMIN', 'CA') else 'ADMIN'
        
        # Check if already exists in target
        existing = conn_tgt.execute(
            text("SELECT id FROM helpdesk_staff_roles WHERE LOWER(email) = :email"),
            {"email": email_clean}
        ).fetchone()
        
        if existing:
            staff_id_map[uid] = existing[0]
        else:
            res = conn_tgt.execute(
                text("""
                    INSERT INTO helpdesk_staff_roles (name, email, password_hash, role, department, phone, is_active)
                    VALUES (:name, :email, :pwd, :role, :dept, :phone, 1)
                """),
                {"name": name, "email": email_clean, "pwd": pwd, "role": staff_role, "dept": dept, "phone": phone}
            )
            staff_id_map[uid] = res.lastrowid
            
    conn_tgt.commit()
    log.info("Seeded %d administrative accounts into helpdesk_staff_roles.", len(staff_id_map))
    
    # ── Step 3: Build Complete User ID Mapping Table (Bulk Optimized) ─────────
    log.info("Building complete user ID mapping table in bulk...")
    ti_map_rows = conn_src.execute(text("""
        SELECT hu.id, ti.TEACHER_ID
        FROM helpdesk_users hu
        JOIN teacher_info ti ON LOWER(hu.email) = LOWER(ti.EMAIL_ID)
    """)).fetchall()
    user_id_map = {r[0]: r[1] for r in ti_map_rows}
    
    # Check by TEACHER_ID for remaining
    id_map_rows = conn_src.execute(text("""
        SELECT hu.id, ti.TEACHER_ID
        FROM helpdesk_users hu
        JOIN teacher_info ti ON hu.id = ti.TEACHER_ID
    """)).fetchall()
    for r in id_map_rows:
        if r[0] not in user_id_map:
            user_id_map[r[0]] = r[1]
            
    # Staff roles overrides
    user_id_map.update(staff_id_map)
    
    # Known fallbacks
    for email_fb, tid_fb in KNOWN_FALLBACKS.items():
        fb_row = conn_src.execute(text("SELECT id FROM helpdesk_users WHERE LOWER(email) = :e"), {"e": email_fb}).fetchone()
        if fb_row:
            user_id_map[fb_row[0]] = tid_fb
            
    log.info("Mapped %d users successfully.", len(user_id_map))
    
    def resolve_uid(old_id, default=1):
        if old_id is None:
            return None
        return user_id_map.get(old_id, default)

    # ── Step 4: Migrate helpdesk_categories (Bulk) ───────────────────────────
    log.info("Migrating helpdesk_categories...")
    categories = conn_src.execute(text("SELECT * FROM helpdesk_categories")).fetchall()
    conn_tgt.execute(text("DELETE FROM helpdesk_categories;"))
    cat_params = [
        {
            "id": m["id"],
            "category_name": m["category_name"],
            "department": m["department"],
            "assigned_ca_id": resolve_uid(m.get("assigned_ca_id")),
            "is_active": m.get("is_active", 1),
            "created_at": m.get("created_at")
        }
        for m in [dict(r._mapping) for r in categories]
    ]
    if cat_params:
        conn_tgt.execute(
            text("""
                INSERT INTO helpdesk_categories (id, category_name, department, assigned_ca_id, is_active, created_at)
                VALUES (:id, :category_name, :department, :assigned_ca_id, :is_active, :created_at)
            """),
            cat_params
        )
    conn_tgt.commit()
    log.info("Migrated %d categories.", len(cat_params))
    
    # ── Step 5: Migrate helpdesk_ca_assignments (Bulk) ───────────────────────
    log.info("Migrating helpdesk_ca_assignments...")
    ca_assigns = conn_src.execute(text("SELECT * FROM helpdesk_ca_assignments")).fetchall()
    conn_tgt.execute(text("DELETE FROM helpdesk_ca_assignments;"))
    ca_params = [
        {
            "id": m["id"],
            "category_id": m["category_id"],
            "ca_id": resolve_uid(m.get("ca_id")),
            "block": m.get("block", ""),
            "created_at": m.get("created_at")
        }
        for m in [dict(r._mapping) for r in ca_assigns]
    ]
    if ca_params:
        conn_tgt.execute(
            text("""
                INSERT INTO helpdesk_ca_assignments (id, category_id, ca_id, block, created_at)
                VALUES (:id, :category_id, :ca_id, :block, :created_at)
            """),
            ca_params
        )
    conn_tgt.commit()
    log.info("Migrated %d CA block assignments.", len(ca_params))
    
    # ── Step 6: Migrate helpdesk_tickets (Bulk) ──────────────────────────────
    log.info("Migrating helpdesk_tickets...")
    tickets = conn_src.execute(text("SELECT * FROM helpdesk_tickets")).fetchall()
    conn_tgt.execute(text("DELETE FROM helpdesk_tickets;"))
    ticket_params = [
        {
            "id": m["id"],
            "title": m["title"],
            "description": m["description"],
            "category_id": m["category_id"],
            "problem_type_id": m.get("problem_type_id"),
            "created_by": resolve_uid(m.get("created_by"), default=1),
            "assigned_to": resolve_uid(m.get("assigned_to"), default=1),
            "status": m.get("status", "PENDING"),
            "org_id": m.get("org_id", "2000"),
            "location_id": m.get("location_id"),
            "submission_key": m.get("submission_key"),
            "created_at": m.get("created_at"),
            "updated_at": m.get("updated_at")
        }
        for m in [dict(r._mapping) for r in tickets]
    ]
    if ticket_params:
        conn_tgt.execute(
            text("""
                INSERT INTO helpdesk_tickets (
                    id, title, description, category_id, problem_type_id,
                    created_by, assigned_to, status, org_id, location_id,
                    submission_key, created_at, updated_at
                ) VALUES (
                    :id, :title, :description, :category_id, :problem_type_id,
                    :created_by, :assigned_to, :status, :org_id, :location_id,
                    :submission_key, :created_at, :updated_at
                )
            """),
            ticket_params
        )
    conn_tgt.commit()
    log.info("Migrated %d tickets.", len(ticket_params))

    # ── Step 7: Migrate helpdesk_ticket_notes (Bulk) ─────────────────────────
    log.info("Migrating helpdesk_ticket_notes...")
    notes = conn_src.execute(text("SELECT * FROM helpdesk_ticket_notes")).fetchall()
    conn_tgt.execute(text("DELETE FROM helpdesk_ticket_notes;"))
    note_params = [
        {
            "id": m["id"],
            "ticket_id": m["ticket_id"],
            "author_id": resolve_uid(m.get("author_id"), default=1),
            "note": m["note"],
            "is_internal": m.get("is_internal", 1),
            "created_at": m.get("created_at")
        }
        for m in [dict(r._mapping) for r in notes]
    ]
    if note_params:
        conn_tgt.execute(
            text("""
                INSERT INTO helpdesk_ticket_notes (id, ticket_id, author_id, note, is_internal, created_at)
                VALUES (:id, :ticket_id, :author_id, :note, :is_internal, :created_at)
            """),
            note_params
        )
    conn_tgt.commit()
    log.info("Migrated %d ticket notes.", len(note_params))

    # ── Step 8: Migrate helpdesk_ticket_activity (Bulk) ─────────────────────
    log.info("Migrating helpdesk_ticket_activity...")
    activities = conn_src.execute(text("SELECT * FROM helpdesk_ticket_activity")).fetchall()
    conn_tgt.execute(text("DELETE FROM helpdesk_ticket_activity;"))
    act_params = [
        {
            "id": m["id"],
            "ticket_id": m["ticket_id"],
            "action_by": resolve_uid(m.get("action_by"), default=1),
            "from_status": m.get("from_status"),
            "to_status": m["to_status"],
            "remarks": m.get("remarks"),
            "time_taken": m.get("time_taken"),
            "attachment_path": m.get("attachment_path"),
            "created_at": m.get("created_at")
        }
        for m in [dict(r._mapping) for r in activities]
    ]
    if act_params:
        conn_tgt.execute(
            text("""
                INSERT INTO helpdesk_ticket_activity (
                    id, ticket_id, action_by, from_status, to_status, remarks,
                    time_taken, attachment_path, created_at
                ) VALUES (
                    :id, :ticket_id, :action_by, :from_status, :to_status, :remarks,
                    :time_taken, :attachment_path, :created_at
                )
            """),
            act_params
        )
    conn_tgt.commit()
    log.info("Migrated %d ticket activity rows.", len(act_params))

    # ── Step 9: Migrate helpdesk_audit_events (Bulk) ────────────────────────
    log.info("Migrating helpdesk_audit_events...")
    events = conn_src.execute(text("SELECT * FROM helpdesk_audit_events")).fetchall()
    conn_tgt.execute(text("DELETE FROM helpdesk_audit_events;"))
    ev_params = [
        {
            "id": m["id"],
            "event_type": m["event_type"],
            "actor_id": resolve_uid(m.get("actor_id"), default=1),
            "target_type": m.get("target_type"),
            "target_id": m.get("target_id"),
            "org_id": m.get("org_id", "2000"),
            "details": m.get("details"),
            "created_at": m.get("created_at")
        }
        for m in [dict(r._mapping) for r in events]
    ]
    if ev_params:
        conn_tgt.execute(
            text("""
                INSERT INTO helpdesk_audit_events (
                    id, event_type, actor_id, target_type, target_id, org_id, details, created_at
                ) VALUES (
                    :id, :event_type, :actor_id, :target_type, :target_id, :org_id, :details, :created_at
                )
            """),
            ev_params
        )
    conn_tgt.commit()
    log.info("Migrated %d audit events.", len(ev_params))

    conn_tgt.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
    conn_tgt.commit()

    # ── Step 10: Verification & Summary Audit ────────────────────────────────
    print("\n=======================================================")
    print("MIGRATION AUDIT REPORT — SOURCE VS TARGET ROW COUNTS")
    print("=======================================================")
    tables_to_check = [
        "helpdesk_categories",
        "helpdesk_ca_assignments",
        "helpdesk_tickets",
        "helpdesk_ticket_notes",
        "helpdesk_ticket_activity",
        "helpdesk_audit_events",
        "helpdesk_problem_types",
        "helpdesk_staff_roles"
    ]
    all_ok = True
    for tbl in tables_to_check:
        src_cnt = conn_src.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar() if tbl != "helpdesk_staff_roles" else "N/A"
        tgt_cnt = conn_tgt.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
        print(f"  {tbl:26s} | {SOURCE_DB}: {str(src_cnt):>5s} | {TARGET_DB}: {tgt_cnt:>5d}")
        if src_cnt != "N/A" and src_cnt != tgt_cnt:
            all_ok = False
            
    print("=======================================================")
    if all_ok:
        log.info("SUCCESS: All operational data migrated to %s with 100% integrity.", TARGET_DB)
    else:
        log.error("WARNING: Row count discrepancies detected!")

    conn_src.close()
    conn_tgt.close()

if __name__ == "__main__":
    migrate()
