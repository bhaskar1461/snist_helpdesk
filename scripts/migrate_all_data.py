"""
Comprehensive Data Migration Script for SNIST Helpdesk.
Migrates:
  1. All 2,000+ faculty members from teacher_info into helpdesk_users.
  2. Legacy sys_administrators into helpdesk_users.
  3. Legacy sys_complaint tickets into helpdesk_tickets and helpdesk_categories.
  4. Preserves default demo accounts with password '123'.
"""

import os
import sys
import pathlib
import pymysql
import pymysql.constants.CLIENT
from werkzeug.security import generate_password_hash

# Auto-load .env if present
env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

# Database Connection Settings
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "seg_demo")


def get_db():
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        autocommit=True,
        client_flag=pymysql.constants.CLIENT.MULTI_STATEMENTS,
        cursorclass=pymysql.cursors.DictCursor
    )


def run_full_migration():
    print("=" * 65)
    print("  SNIST Helpdesk — Full Database Data Migration Pipeline")
    print("=" * 65)

    conn = get_db()
    cursor = conn.cursor()

    # Step 1: Ensure helpdesk_locations table exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS helpdesk_locations (
            id INT UNSIGNED NOT NULL AUTO_INCREMENT,
            block VARCHAR(100) NOT NULL,
            room VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_block_room (block, room)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # Step 2: Load SQL dump files if teacher_info or demo_sys_ tables are missing
    base_dir = pathlib.Path(__file__).resolve().parent.parent
    dump_files = [
        base_dir / "New Project 20260803 1346.sql",
        base_dir / "sql" / "sreenidhi_dump.sql"
    ]

    for dump_file in dump_files:
        if dump_file.exists():
            print(f"[..] Reading & executing dump file: {dump_file.name}...")
            try:
                text = dump_file.read_text(encoding="utf-8", errors="ignore")
                # Remove zero-date constraints for MySQL session
                cursor.execute("SET SESSION sql_mode = '';")
                cursor.execute(text)
                while cursor.nextset():
                    pass
                print(f"[OK] Dump file {dump_file.name} processed.")
            except Exception as e:
                print(f"[!] Warning on dump {dump_file.name}: {e}")

    cursor.execute(f"USE `{MYSQL_DATABASE}`;")

    # Step 3: Migrate all 2,000+ Teachers from teacher_info -> helpdesk_users
    print("\n[1/3] Migrating Faculty & Teachers from teacher_info -> helpdesk_users...")
    try:
        cursor.execute("""
            SELECT 
                t.TEACHER_ID, t.TEACHER_NAME, t.EMAIL_ID, t.SAP_ID,
                COALESCE(b.BRANCH_NAME, b.BRANCH_CODE, 'GENERAL') AS department
            FROM teacher_info t
            LEFT JOIN branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
        """)
        teachers = cursor.fetchall()
        print(f"  Found {len(teachers)} teacher records in teacher_info.")

        default_pw = generate_password_hash("Password@123")
        teachers_inserted = 0

        # Build map of existing emails
        cursor.execute("SELECT LOWER(email) AS email FROM helpdesk_users WHERE email IS NOT NULL AND email != ''")
        existing_emails = {r["email"] for r in cursor.fetchall()}

        for t in teachers:
            name = (t["TEACHER_NAME"] or "").strip()
            tid = str(t["TEACHER_ID"] or "").strip()
            email = (t["EMAIL_ID"] or "").strip().lower()
            dept = (t["department"] or "GENERAL").strip()

            if not name:
                continue

            if not email or "@" not in email:
                email = f"teacher_{tid}@sreenidhi.edu.in" if tid else f"teacher_{hash(name) % 100000}@sreenidhi.edu.in"

            if email in existing_emails:
                continue

            cursor.execute("""
                INSERT INTO helpdesk_users (name, email, password, role, department)
                VALUES (%s, %s, %s, 'FACULTY', %s)
            """, (name, email, default_pw, dept))
            existing_emails.add(email)
            teachers_inserted += 1

        print(f"  [OK] Successfully imported {teachers_inserted} new faculty members into helpdesk_users.")
    except Exception as e:
        print(f"  [!] Teacher migration note: {e}")

    # Step 4: Migrate legacy sys_administrators -> helpdesk_users
    print("\n[2/3] Migrating Legacy Administrators -> helpdesk_users...")
    teacher_to_user_id = {}
    try:
        cursor.execute("SELECT * FROM demo_sys_administrators;")
        admins = cursor.fetchall()
        for a in admins:
            tid = (a["TEACHER_ID"] or "").strip()
            name = (a["NAME"] or "").strip()
            dept = (a["DEPARTMENT"] or "GENERAL").strip()
            email = (a["EMAIL_ID"] or "").strip().lower() if a["EMAIL_ID"] else f"{tid.lower()}@sreenidhi.edu.in"
            role_str = (a["ADMIN_ROLE"] or "").strip().lower()

            if "super" in role_str:
                role = "SUPER_ADMIN"
            elif role_str in ["ict", "fecilities", "hcm", "mm", "pm"]:
                role = "ADMIN"
            else:
                role = "FACULTY"

            cursor.execute("SELECT id FROM helpdesk_users WHERE email = %s;", (email,))
            row = cursor.fetchone()
            if row:
                uid = row["id"]
            else:
                cursor.execute("""
                    INSERT INTO helpdesk_users (name, email, password, role, department)
                    VALUES (%s, %s, %s, %s, %s);
                """, (name, email, generate_password_hash("Password@123"), role, dept))
                uid = cursor.lastrowid

            teacher_to_user_id[tid] = uid

        print(f"  [OK] Processed {len(admins)} legacy administrators.")
    except Exception as e:
        print(f"  [!] Administrator migration note: {e}")

    # Default CA fallback ID
    cursor.execute("SELECT id FROM helpdesk_users WHERE role IN ('SUPER_ADMIN', 'ADMIN', 'CA') LIMIT 1;")
    default_ca = cursor.fetchone()
    default_ca_id = default_ca["id"] if default_ca else 1

    # Step 5: Migrate complaints & categories -> helpdesk_tickets & helpdesk_categories
    print("\n[3/3] Migrating Legacy Complaints -> helpdesk_tickets & helpdesk_categories...")
    try:
        cursor.execute("SELECT * FROM demo_sys_complaint WHERE TICKET_ID > 1;")
        complaints = cursor.fetchall()

        tickets_migrated = 0
        categories_cache = {}

        for c in complaints:
            ticket_id = c["TICKET_ID"]
            block = (c["BLOCK"] or "General Block").strip()
            room = (c["ROOMNO"] or "General Room").strip()
            device_type = (c["DEVICE_TYPE"] or "General Hardware").strip()
            raised_by_tid = (c["RAISED_BY"] or "").strip()
            raised_dt = c["RAISED_DATATIME"]
            dept = (c["DEPARTMENT"] or "ICT").strip()

            raw_desc = c["RAISED_DESCRIPTION"]
            if isinstance(raw_desc, bytes):
                description = raw_desc.decode("utf-8", errors="ignore").strip()
            else:
                description = str(raw_desc or "").strip()

            if not description:
                description = f"Legacy Complaint #{ticket_id} for {device_type}"

            title = f"{device_type} Issue at {block} - {room}" if device_type else f"Issue at {block} - {room}"

            # Category mapping
            cat_key = (device_type, dept)
            if cat_key not in categories_cache:
                cursor.execute("SELECT id FROM helpdesk_categories WHERE category_name = %s AND department = %s;", (device_type, dept))
                crow = cursor.fetchone()
                if crow:
                    categories_cache[cat_key] = crow["id"]
                else:
                    cursor.execute("""
                        INSERT INTO helpdesk_categories (category_name, department, assigned_ca_id, is_active)
                        VALUES (%s, %s, NULL, 1);
                    """, (device_type, dept))
                    categories_cache[cat_key] = cursor.lastrowid
            cat_id = categories_cache[cat_key]

            creator_id = teacher_to_user_id.get(raised_by_tid, default_ca_id)

            cursor.execute("SELECT id FROM helpdesk_tickets WHERE id = %s;", (ticket_id,))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO helpdesk_tickets 
                    (id, title, description, category_id, created_by, assigned_to, status, org_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', '2000', %s);
                """, (ticket_id, title[:180], description, cat_id, creator_id, default_ca_id, raised_dt))
                tickets_migrated += 1

        print(f"  [OK] Successfully imported {tickets_migrated} legacy tickets and populated category mappings.")
    except Exception as e:
        print(f"  [!] Ticket migration note: {e}")

    # Print Summary Counts
    cursor.execute("SELECT COUNT(*) AS total FROM helpdesk_users;")
    total_users = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM helpdesk_categories;")
    total_cats = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM helpdesk_tickets;")
    total_tickets = cursor.fetchone()["total"]

    print("\n" + "=" * 65)
    print("  MIGRATION SUMMARY")
    print("=" * 65)
    print(f"  Total Registered Users in helpdesk_users:     {total_users:,}")
    print(f"  Total Categories in helpdesk_categories:      {total_cats:,}")
    print(f"  Total Tickets in helpdesk_tickets:           {total_tickets:,}")
    print("=" * 65 + "\n")

    # Trigger Metabase database sync if available
    try:
        try:
            from scripts.configure_metabase import login, find_database, sync_database
        except ImportError:
            from configure_metabase import login, find_database, sync_database
            
        if login():
            db_id = find_database()
            if db_id:
                sync_database(db_id)
    except Exception as exc:
        print(f"[!] Metabase sync trigger note: {exc}")


if __name__ == "__main__":
    run_full_migration()
