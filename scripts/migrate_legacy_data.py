"""
Migration script for legacy Sreenidhi database (sys_administrators & sys_complaint)
into main SNIST helpdesk tables: demo_users, demo_locations, demo_categories, demo_tickets.
"""

import os
import sys
import pymysql
import pymysql.constants.CLIENT
from werkzeug.security import generate_password_hash

# DB Config
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
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

def run_migration():
    print("=" * 60)
    print("Migrating Legacy Sreenidhi Data to Helpdesk Schema")
    print("=" * 60)

    db = get_db()
    cursor = db.cursor()

    # 1. Execute SQL dump file to build demo_sys_ tables inside seg_demo
    sql_dump_path = os.path.join(os.path.dirname(__file__), "..", "sql", "sreenidhi_dump.sql")
    if os.path.exists(sql_dump_path):
        print("[..] Reading and executing sql/sreenidhi_dump.sql...")
        with open(sql_dump_path, "r", encoding="utf-8", errors="ignore") as f:
            sql_script = f.read()

        try:
            cursor.execute(sql_script)
            while cursor.nextset():
                pass
            print("[OK] Loaded legacy database schema & tables into seg_demo.")
        except Exception as e:
            print(f"[!] Warning on executing SQL dump: {e}")

    # Select main database
    cursor.execute(f"USE `{MYSQL_DATABASE}`;")

    # Ensure helpdesk_locations table exists
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

    # 2. Migrate demo_sys_administrators -> demo_users
    print("[..] Migrating demo_sys_administrators -> demo_users...")
    cursor.execute("SELECT * FROM demo_sys_administrators;")
    admins = cursor.fetchall()
    
    default_pw_hash = generate_password_hash("Password@123")
    teacher_to_user_id = {}
    users_migrated = 0

    for a in admins:
        tid = a["TEACHER_ID"].strip()
        name = a["NAME"].strip()
        dept = a["DEPARTMENT"].strip() if a["DEPARTMENT"] else "GENERAL"
        email = a["EMAIL_ID"].strip().lower() if a["EMAIL_ID"] else f"{tid.lower()}@sreenidhi.edu.in"
        role_str = (a["ADMIN_ROLE"] or "").strip().lower()

        # Role mapping
        if "super" in role_str:
            role = "SUPER_ADMIN"
        elif role_str in ["ict", "fecilities", "hcm", "mm", "pm"]:
            role = "ADMIN"
        else:
            role = "FACULTY"

        # Check if user already exists
        cursor.execute("SELECT id FROM helpdesk_users WHERE email = %s;", (email,))
        row = cursor.fetchone()
        if row:
            uid = row["id"]
        else:
            cursor.execute("""
                INSERT INTO helpdesk_users (name, email, password, role, department)
                VALUES (%s, %s, %s, %s, %s);
            """, (name, email, default_pw_hash, role, dept))
            uid = cursor.lastrowid
            users_migrated += 1
        
        teacher_to_user_id[tid] = uid

    # Map all teachers from teacher_info into teacher_to_user_id
    cursor.execute("""
        SELECT ti.TEACHER_CODE, ti.SAP_ID, u.id AS user_id
        FROM teacher_info ti
        JOIN helpdesk_users u ON LOWER(u.email) = LOWER(ti.EMAIL_ID)
        WHERE ti.EMAIL_ID IS NOT NULL AND ti.EMAIL_ID != '';
    """)
    for r in cursor.fetchall():
        uid = r["user_id"]
        if r.get("TEACHER_CODE"):
            teacher_to_user_id[r["TEACHER_CODE"].strip()] = uid
            teacher_to_user_id[r["TEACHER_CODE"].strip().upper()] = uid
        if r.get("SAP_ID"):
            teacher_to_user_id[r["SAP_ID"].strip()] = uid
            teacher_to_user_id[r["SAP_ID"].strip().upper()] = uid

    print(f"[OK] Migrated/mapped {len(teacher_to_user_id)} legacy user aliases.")

    # Ensure a designated 'Legacy Faculty' user exists for completely unknown legacy submitters
    cursor.execute("SELECT id FROM helpdesk_users WHERE email = 'legacy.faculty@sreenidhi.edu.in';")
    legacy_user = cursor.fetchone()
    if not legacy_user:
        cursor.execute("""
            INSERT INTO helpdesk_users (name, email, password, role, department, phone)
            VALUES ('Legacy Faculty Archive', 'legacy.faculty@sreenidhi.edu.in', %s, 'FACULTY', 'General', '9704083464');
        """, (default_pw_hash,))
        default_creator_id = cursor.lastrowid
    else:
        default_creator_id = legacy_user["id"]

    # Get a default CA user ID for category mapping
    cursor.execute("SELECT id FROM helpdesk_users WHERE role = 'CA' LIMIT 1;")
    default_ca = cursor.fetchone()
    default_ca_id = default_ca["id"] if default_ca else 1

    # 3. Migrate locations & categories & complaints
    print("[..] Migrating demo_sys_complaint -> helpdesk_tickets...")
    cursor.execute("SELECT * FROM demo_sys_complaint WHERE TICKET_ID > 1;")
    complaints = cursor.fetchall()

    tickets_migrated = 0
    locations_cache = {}
    categories_cache = {}

    for c in complaints:
        ticket_id = c["TICKET_ID"]
        block = (c["BLOCK"] or "General Block").strip()
        room = (c["ROOMNO"] or "General Room").strip()
        device_type = (c["DEVICE_TYPE"] or "General Hardware").strip()
        raised_by_tid = (c["RAISED_BY"] or "").strip()
        raised_dt = c["RAISED_DATATIME"]
        dept = (c["DEPARTMENT"] or "ICT").strip()
        
        # Handle description blob
        raw_desc = c["RAISED_DESCRIPTION"]
        if isinstance(raw_desc, bytes):
            try:
                description = raw_desc.decode("utf-8", errors="ignore").strip()
            except Exception:
                description = str(raw_desc)
        else:
            description = str(raw_desc or "")
        
        if not description:
            description = f"Legacy Complaint #{ticket_id} for {device_type}"

        title = f"{device_type} Issue at {block} - {room}" if device_type else f"Issue at {block} - {room}"

        # 3b. Resolve category_id
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

        # 3c. Resolve created_by user_id
        creator_id = teacher_to_user_id.get(raised_by_tid.upper()) or teacher_to_user_id.get(raised_by_tid, default_creator_id)

        # Check if ticket already imported
        cursor.execute("SELECT id FROM helpdesk_tickets WHERE id = %s;", (ticket_id,))
        if not cursor.fetchone():
            cursor.execute("""
                INSERT INTO helpdesk_tickets 
                (id, title, description, category_id, created_by, assigned_to, status, org_id, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, 'PENDING', '2000', %s);
            """, (ticket_id, title[:180], description, cat_id, creator_id, default_ca_id, raised_dt))
            tickets_migrated += 1

    print(f"[OK] Migration completed! Successfully imported {tickets_migrated} legacy tickets.")
    print("=" * 60)

if __name__ == "__main__":
    run_migration()
