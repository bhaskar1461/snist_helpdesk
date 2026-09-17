"""
Script: migrate_historical_complaints.py
Description: Migrates 881 historical complaints from sreenidhi.sys_complaint and
sreenidhi.status_complaint into helpdesk.helpdesk_tickets and helpdesk.helpdesk_ticket_activity.
"""

import os
import datetime
import pymysql
from dotenv import load_dotenv

load_dotenv()

def parse_date(d, fallback=None):
    if not d:
        return fallback or datetime.datetime(2025, 8, 1, 0, 0, 0)
    if isinstance(d, datetime.datetime):
        return d
    try:
        s = str(d).strip()
        if s.startswith('0000-00-00'):
            return fallback or datetime.datetime(2025, 8, 1, 0, 0, 0)
        return datetime.datetime.fromisoformat(s)
    except Exception:
        return fallback or datetime.datetime(2025, 8, 1, 0, 0, 0)

def decode_text(val):
    if val is None:
        return ""
    if isinstance(val, (bytes, bytearray)):
        return val.decode('latin1', errors='replace').strip()
    return str(val).strip()

def migrate():
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
            print("=== Step 1: Loading Lookup Dictionaries ===")
            
            # 1. Categories
            cur.execute("SELECT id, category_name, department, assigned_ca_id FROM helpdesk_categories")
            cats = cur.fetchall()
            cat_by_name = {c['category_name'].lower().strip(): c for c in cats}
            cat_default = cat_by_name.get('others') or cat_by_name.get('system') or cats[0]

            # 2. Teachers / Users
            cur.execute("SELECT TEACHER_ID, TEACHER_CODE, SAP_ID, EMAIL_ID FROM teacher_info")
            teachers = cur.fetchall()
            user_by_code = {}
            for t in teachers:
                if t['TEACHER_CODE']:
                    user_by_code[t['TEACHER_CODE'].upper().strip()] = t['TEACHER_ID']
                if t['SAP_ID']:
                    user_by_code[t['SAP_ID'].strip()] = t['TEACHER_ID']

            cur.execute("SELECT id, teacher_id, email FROM helpdesk_staff_roles")
            staff = cur.fetchall()
            for s in staff:
                if s.get('teacher_id'):
                    user_by_code[str(s['teacher_id'])] = s['teacher_id']
                if s.get('email'):
                    user_by_code[s['email'].lower()] = s['id']

            # 3. Locations
            cur.execute("SELECT id, block, room_no FROM location")
            locations = cur.fetchall()
            loc_by_block_room = {}
            loc_by_block = {}
            for loc in locations:
                b = (loc['block'] or '').lower().strip()
                r = (loc['room_no'] or '').lower().strip()
                if b and r:
                    loc_by_block_room[(b, r)] = loc['id']
                if b and b not in loc_by_block:
                    loc_by_block[b] = loc['id']

            # 4. Fetch complaints
            print("=== Step 2: Fetching historical complaints from sreenidhi ===")
            cur.execute("""
                SELECT 
                    c.TICKET_ID,
                    c.BLOCK,
                    c.ROOMNO,
                    c.DEVICE_TYPE,
                    c.RAISED_BY,
                    c.RAISED_DATATIME,
                    c.RAISED_DESCRIPTION,
                    c.PARENT_DEPARTMENT,
                    c.DEPARTMENT,
                    s.SUPER_ADMIN,
                    s.ASSIGNED_TO,
                    s.ASSIGNED_DATETIME,
                    s.ASSIGNED_DESCRPTION,
                    s.STATUS,
                    s.CLOSED_DATETIME,
                    s.CLOSED_DESCRIPTION,
                    s.HOLD_DESCRIPTION,
                    s.REOPEN_DESCRIPTION
                FROM sreenidhi.sys_complaint c
                LEFT JOIN sreenidhi.status_complaint s ON c.TICKET_ID = s.TICKET_ID
                ORDER BY c.TICKET_ID ASC
            """)
            complaints = cur.fetchall()
            print(f"Found {len(complaints)} complaints to process.")

            tickets_migrated = 0
            activity_migrated = 0

            print("\n=== Step 3: Inserting complaints into helpdesk_tickets ===")
            for c in complaints:
                ticket_id = c['TICKET_ID']
                if ticket_id <= 0:
                    continue

                raw_dev = decode_text(c['DEVICE_TYPE'])
                dev_clean = raw_dev.lower()
                
                # Match category
                matched_cat = cat_by_name.get(dev_clean)
                if not matched_cat:
                    # Fuzzy match or partial
                    for k, v in cat_by_name.items():
                        if k in dev_clean or dev_clean in k:
                            matched_cat = v
                            break
                if not matched_cat:
                    matched_cat = cat_default

                category_id = matched_cat['id']
                
                # Block & Room
                block_raw = decode_text(c['BLOCK'])
                room_raw = decode_text(c['ROOMNO'])
                location_id = loc_by_block_room.get((block_raw.lower(), room_raw.lower()))
                if not location_id:
                    location_id = loc_by_block.get(block_raw.lower())

                # Description & Title
                desc_text = decode_text(c['RAISED_DESCRIPTION'])
                if not desc_text:
                    desc_text = f"Reported issue with {raw_dev or 'equipment'} in {block_raw} {room_raw}."
                
                title = f"{raw_dev or matched_cat['category_name']} issue in {block_raw} {room_raw}".strip()
                if len(title) > 175:
                    title = title[:175] + "..."

                # Created By
                raised_by_code = decode_text(c['RAISED_BY']).upper()
                created_by = user_by_code.get(raised_by_code, 1)

                # Assigned To
                assigned_to_code = decode_text(c['ASSIGNED_TO']).upper()
                assigned_to = user_by_code.get(assigned_to_code)
                if not assigned_to:
                    assigned_to = matched_cat.get('assigned_ca_id') or 5

                # Status
                raw_status = decode_text(c['STATUS']).lower()
                if raw_status in ('closed', 'resolve', 'resolved'):
                    status = 'RESOLVED'
                elif raw_status in ('in progress', 'inprogress', 'assigned'):
                    status = 'IN_PROGRESS'
                elif raw_status in ('hold', 'on hold', 'on_hold'):
                    status = 'ON_HOLD'
                elif raw_status in ('reopen', 'reopened'):
                    status = 'REOPENED'
                else:
                    status = 'PENDING'

                created_at = parse_date(c['RAISED_DATATIME'])
                closed_at = parse_date(c['CLOSED_DATETIME'], fallback=created_at)
                updated_at = closed_at if status == 'RESOLVED' else parse_date(c['ASSIGNED_DATETIME'], fallback=created_at)

                # Insert or update ticket
                cur.execute("""
                    INSERT INTO helpdesk_tickets
                    (id, title, description, category_id, created_by, assigned_to, status, org_id, location_id, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, '2000', %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        title = VALUES(title),
                        description = VALUES(description),
                        category_id = VALUES(category_id),
                        created_by = VALUES(created_by),
                        assigned_to = VALUES(assigned_to),
                        status = VALUES(status),
                        location_id = VALUES(location_id),
                        created_at = VALUES(created_at),
                        updated_at = VALUES(updated_at)
                """, (ticket_id, title, desc_text, category_id, created_by, assigned_to, status, location_id, created_at, updated_at))
                tickets_migrated += 1

                # Activity Log: Initial creation
                cur.execute("""
                    INSERT IGNORE INTO helpdesk_ticket_activity
                    (ticket_id, action_by, from_status, to_status, remarks, created_at)
                    VALUES (%s, %s, NULL, 'PENDING', 'Complaint submitted via legacy portal', %s)
                """, (ticket_id, created_by, created_at))
                activity_migrated += 1

                # Activity Log: Resolution / Status change
                if status != 'PENDING':
                    res_remarks = decode_text(c['CLOSED_DESCRIPTION']) or decode_text(c['HOLD_DESCRIPTION']) or f"Status transitioned to {status}"
                    cur.execute("""
                        INSERT IGNORE INTO helpdesk_ticket_activity
                        (ticket_id, action_by, from_status, to_status, remarks, created_at)
                        VALUES (%s, %s, 'PENDING', %s, %s, %s)
                    """, (ticket_id, assigned_to, status, res_remarks, updated_at))
                    activity_migrated += 1

            conn.commit()
            print(f"Successfully migrated {tickets_migrated} tickets and {activity_migrated} activity events into helpdesk database!")

            # Verify ticket counts by status
            cur.execute("SELECT status, COUNT(*) as cnt FROM helpdesk_tickets GROUP BY status")
            print("\n=== Current helpdesk_tickets status breakdown ===")
            for r in cur.fetchall():
                print(f"  {r['status']}: {r['cnt']}")

            cur.execute("SELECT COUNT(*) as total FROM helpdesk_tickets")
            print(f"Total helpdesk_tickets in database: {cur.fetchone()['total']}")

    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
