"""
Script: sync_all_accounts.py
Description: Synchronizes all 20 campus administrators from sys_administrators into helpdesk_staff_roles,
linking their teacher_id from teacher_info, populating their departmental roles, and updating the
helpdesk_users view so all institutional staff and faculty are cleanly resolvable.
"""

import os
import pymysql
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash

load_dotenv()

def sync_accounts():
    conn = pymysql.connect(
        host=os.getenv('MYSQL_HOST', 'seg.sreenidhi.edu.in'),
        port=int(os.getenv('MYSQL_PORT', 3306)),
        user=os.getenv('MYSQL_USER', 'demo'),
        password=os.getenv('MYSQL_PASSWORD', ''),
        database=os.getenv('MYSQL_DATABASE', 'helpdesk'),
        cursorclass=pymysql.cursors.DictCursor
    )

    try:
        with conn.cursor() as cur:
            print("=== Step 1: Fetching sys_administrators from sreenidhi ===")
            cur.execute("SELECT * FROM sreenidhi.sys_administrators")
            sys_admins = cur.fetchall()
            print(f"Found {len(sys_admins)} administrators.")

            # Load all teachers for fast matching by code, sap, email
            cur.execute("SELECT TEACHER_ID, TEACHER_NAME, EMAIL_ID, SAP_ID, TEACHER_CODE, MOBILE_PHONE, BRANCH_ID, DESIGNATION FROM teacher_info")
            teachers = cur.fetchall()
            
            by_code = {t['TEACHER_CODE'].upper(): t for t in teachers if t['TEACHER_CODE']}
            by_sap = {t['SAP_ID']: t for t in teachers if t['SAP_ID']}
            by_email = {t['EMAIL_ID'].lower(): t for t in teachers if t['EMAIL_ID']}

            # Load existing staff roles
            cur.execute("SELECT * FROM helpdesk_staff_roles")
            existing_staff = cur.fetchall()
            existing_by_email = {s['email'].lower(): s for s in existing_staff if s['email']}
            existing_by_teacher_id = {s['teacher_id']: s for s in existing_staff if s.get('teacher_id')}

            print("\n=== Step 2: Processing and Synchronizing Accounts ===")
            for sa in sys_admins:
                t_code = (sa['TEACHER_ID'] or '').strip().upper()
                admin_name = sa['NAME'].strip()
                admin_dept = (sa['DEPARTMENT'] or '').strip()
                raw_role = (sa['ADMIN_ROLE'] or '').strip().lower()
                sa_email = (sa['EMAIL_ID'] or '').strip().lower()
                mobile = str(int(sa['MOBILE_NO'])) if sa.get('MOBILE_NO') else None

                # Normalize role
                if 'super' in raw_role:
                    role = 'SUPER_ADMIN'
                elif raw_role in ('administrator', 'admin'):
                    role = 'ADMIN'
                else:
                    role = 'CA'  # Default for departmental assignees (ICT, Facilities, HCM, MM, etc.)

                # Normalize department
                if admin_dept.lower() in ('fecilities', 'facilities'):
                    department = 'Facilities'
                elif 'transport' in admin_dept.lower():
                    department = 'Transport'
                elif 'hcm' in admin_dept.lower():
                    department = 'HCM'
                elif 'mm' in admin_dept.lower():
                    department = 'MM'
                elif 'ict' in admin_dept.lower():
                    department = 'ICT'
                elif 'sap' in admin_dept.lower():
                    department = 'SAP'
                elif 'cto' in admin_dept.lower():
                    department = 'CTO'
                else:
                    department = admin_dept or 'General'

                # Match with teacher_info
                matched_teacher = None
                if t_code in by_code:
                    matched_teacher = by_code[t_code]
                elif t_code in by_sap:
                    matched_teacher = by_sap[t_code]
                elif sa_email and sa_email in by_email:
                    matched_teacher = by_email[sa_email]
                elif 'suresh' in admin_name.lower():
                    # Suresh Gurala mapping
                    matched_teacher = next((t for t in teachers if 'gurala' in t['TEACHER_NAME'].lower()), None)

                teacher_id = matched_teacher['TEACHER_ID'] if matched_teacher else None
                teacher_email = matched_teacher['EMAIL_ID'].lower() if matched_teacher and matched_teacher['EMAIL_ID'] else sa_email
                official_name = matched_teacher['TEACHER_NAME'] if matched_teacher else admin_name
                phone = (matched_teacher['MOBILE_PHONE'] if matched_teacher and matched_teacher['MOBILE_PHONE'] not in ('0', '', None) else mobile) or None
                sap_pwd = matched_teacher['SAP_ID'] if (matched_teacher and matched_teacher['SAP_ID']) else 'Admin@123'
                default_pwd_hash = generate_password_hash(sap_pwd)

                # Check if already in helpdesk_staff_roles
                target_staff = None
                if teacher_email and teacher_email in existing_by_email:
                    target_staff = existing_by_email[teacher_email]
                elif sa_email and sa_email in existing_by_email:
                    target_staff = existing_by_email[sa_email]
                elif teacher_id and teacher_id in existing_by_teacher_id:
                    target_staff = existing_by_teacher_id[teacher_id]

                if target_staff:
                    # Update existing record with teacher_id, phone, and department if missing
                    print(f"[UPDATE] Staff #{target_staff['id']}: {official_name} (Teacher #{teacher_id}) | Dept: {department} | Role: {role}")
                    cur.execute("""
                        UPDATE helpdesk_staff_roles
                        SET teacher_id = COALESCE(%s, teacher_id),
                            name = %s,
                            role = CASE WHEN role = 'SUPER_ADMIN' THEN 'SUPER_ADMIN' ELSE %s END,
                            department = COALESCE(department, %s),
                            phone = COALESCE(%s, phone),
                            is_active = 1
                        WHERE id = %s
                    """, (teacher_id, official_name, role, department, phone, target_staff['id']))
                else:
                    # Insert new staff role
                    email_to_use = teacher_email or sa_email or f"{t_code.lower()}@sreenidhi.edu.in"
                    print(f"[INSERT] New Staff: {official_name} (Teacher #{teacher_id}) | Email: {email_to_use} | Dept: {department} | Role: {role}")
                    cur.execute("""
                        INSERT INTO helpdesk_staff_roles
                        (teacher_id, name, email, password_hash, role, department, phone, is_active, org_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 1, '2000')
                    """, (teacher_id, official_name, email_to_use, default_pwd_hash, role, department, phone))

            conn.commit()
            print("Successfully synchronized all administrator and assignee records in helpdesk_staff_roles.")

            # Step 3: Link teacher_id on any other staff_roles that have placeholder emails or matching emails
            print("\n=== Step 3: Linking teacher_id on all remaining helpdesk_staff_roles ===")
            cur.execute("SELECT id, email, name, teacher_id FROM helpdesk_staff_roles WHERE teacher_id IS NULL")
            unlinked = cur.fetchall()
            for u in unlinked:
                em = (u['email'] or '').lower().strip()
                t_match = None
                if em in by_email:
                    t_match = by_email[em]
                elif em.startswith('t_') and '@' in em:
                    try:
                        tid_cand = int(em.split('@')[0].replace('t_', ''))
                        cur.execute("SELECT TEACHER_ID, TEACHER_NAME, EMAIL_ID FROM teacher_info WHERE TEACHER_ID = %s", (tid_cand,))
                        t_match = cur.fetchone()
                    except ValueError:
                        pass
                if t_match:
                    print(f"  Linked Staff #{u['id']} ({u['name']}) -> Teacher #{t_match['TEACHER_ID']}")
                    cur.execute("UPDATE helpdesk_staff_roles SET teacher_id = %s WHERE id = %s", (t_match['TEACHER_ID'], u['id']))
            conn.commit()

            # Step 4: Reconcile helpdesk_users view
            print("\n=== Step 4: Reconciling helpdesk_users View ===")
            # Note: We create a unified view that contains all staff roles AND all teacher_info records
            # ensuring Metabase JOIN helpdesk_users u ON t.created_by = u.id works regardless of whether
            # created_by references a teacher_info.TEACHER_ID or helpdesk_staff_roles.id.
            cur.execute("""
                CREATE OR REPLACE VIEW helpdesk_users AS
                SELECT 
                    s.id AS id,
                    s.name AS name,
                    s.email AS email,
                    s.password_hash AS password,
                    s.role AS role,
                    s.department AS department,
                    s.phone AS phone,
                    s.is_active AS is_active,
                    s.created_at AS created_at
                FROM helpdesk_staff_roles s
                UNION ALL
                SELECT 
                    t.TEACHER_ID AS id,
                    t.TEACHER_NAME AS name,
                    t.EMAIL_ID AS email,
                    '' AS password,
                    CASE 
                        WHEN b.HOD_ID = t.TEACHER_ID OR t.DESIGNATION LIKE '%Head%' THEN 'HOD' 
                        ELSE 'FACULTY' 
                    END AS role,
                    COALESCE(b.BRANCH_CODE, 'General') AS department,
                    t.MOBILE_PHONE AS phone,
                    1 AS is_active,
                    '2026-01-01 00:00:00' AS created_at
                FROM teacher_info t
                LEFT JOIN branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
                WHERE t.EMAIL_ID IS NOT NULL AND t.EMAIL_ID != ''
                  AND NOT EXISTS (
                      SELECT 1 FROM helpdesk_staff_roles s2 WHERE s2.id = t.TEACHER_ID
                  );
            """)
            conn.commit()
            print("Successfully reconciled helpdesk_users view to encompass both staff roles and institutional faculty!")

    finally:
        conn.close()

if __name__ == '__main__':
    sync_accounts()
