import pymysql
import os
from werkzeug.security import generate_password_hash

def fix_creators():
    MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
    MYSQL_PORT = int(os.getenv("MYSQL_PORT", 3306))
    MYSQL_USER = os.getenv("MYSQL_USER", "snist_user")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "snist_pass_2026")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "seg_demo")

    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )

    with conn.cursor() as cur:
        # Build map from TEACHER_CODE / SAP_ID -> helpdesk_users.id
        print("Building teacher to helpdesk_users map...")
        cur.execute("""
            SELECT ti.TEACHER_CODE, ti.SAP_ID, ti.TEACHER_NAME, ti.EMAIL_ID, u.id AS user_id
            FROM teacher_info ti
            JOIN helpdesk_users u ON LOWER(u.email) = LOWER(ti.EMAIL_ID)
            WHERE ti.EMAIL_ID IS NOT NULL AND ti.EMAIL_ID != '';
        """)
        rows = cur.fetchall()
        teacher_map = {}
        for r in rows:
            uid = r["user_id"]
            if r.get("TEACHER_CODE"):
                teacher_map[r["TEACHER_CODE"].strip().upper()] = uid
                teacher_map[r["TEACHER_CODE"].strip()] = uid
            if r.get("SAP_ID"):
                teacher_map[r["SAP_ID"].strip().upper()] = uid
                teacher_map[r["SAP_ID"].strip()] = uid

        print(f"Mapped {len(teacher_map)} teacher code aliases to helpdesk_users IDs.")

        # Ensure a designated 'Legacy Faculty' user exists for completely unknown legacy submitters
        cur.execute("SELECT id FROM helpdesk_users WHERE email = 'legacy.faculty@sreenidhi.edu.in';")
        legacy_user = cur.fetchone()
        if not legacy_user:
            cur.execute("""
                INSERT INTO helpdesk_users (name, email, password, role, department, phone)
                VALUES ('Legacy Faculty Archive', 'legacy.faculty@sreenidhi.edu.in', %s, 'FACULTY', 'General', '9704083464');
            """, (generate_password_hash("Password@123"),))
            legacy_uid = cur.lastrowid
        else:
            legacy_uid = legacy_user["id"]

        # Fetch legacy complaints
        cur.execute("SELECT TICKET_ID, RAISED_BY FROM demo_sys_complaint WHERE TICKET_ID > 0;")
        complaints = cur.fetchall()

        updated_count = 0
        for c in complaints:
            tid = c["TICKET_ID"]
            raised_by = (c.get("RAISED_BY") or "").strip()
            
            creator_id = teacher_map.get(raised_by.upper()) or teacher_map.get(raised_by) or legacy_uid
            
            # Update helpdesk_tickets
            cur.execute(
                "UPDATE helpdesk_tickets SET created_by = %s WHERE id = %s AND (created_by = 1 OR created_by = 2);",
                (creator_id, tid)
            )
            if cur.rowcount > 0:
                updated_count += 1

        print(f"Successfully remapped {updated_count} legacy tickets to their real submitters (legacy_uid: {legacy_uid}).")

if __name__ == "__main__":
    fix_creators()
