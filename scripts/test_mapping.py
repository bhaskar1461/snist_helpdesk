#!/usr/bin/env python3
"""
Test and build the user ID remapping between seg_demo.helpdesk_users and seg_demo.teacher_info / helpdesk_staff_roles.
"""

from sqlalchemy import create_engine, text

def test_mapping():
    e_demo = create_engine('mysql+pymysql://demo:Admin%40321%23@seg-dev.sreenidhi.edu.in:3306/seg_demo')
    conn = e_demo.connect()

    # 1. Fetch all distinct users in helpdesk_tickets, notes, activity, ca_assignments, categories
    print("Collecting all referenced users...")
    q = """
        SELECT DISTINCT created_by AS uid FROM helpdesk_tickets
        UNION
        SELECT DISTINCT assigned_to AS uid FROM helpdesk_tickets
        UNION
        SELECT DISTINCT author_id AS uid FROM helpdesk_ticket_notes
        UNION
        SELECT DISTINCT action_by AS uid FROM helpdesk_ticket_activity
        UNION
        SELECT DISTINCT ca_id AS uid FROM helpdesk_ca_assignments
        UNION
        SELECT DISTINCT assigned_ca_id AS uid FROM helpdesk_categories WHERE assigned_ca_id IS NOT NULL
    """
    user_ids = [r[0] for r in conn.execute(text(q)).fetchall() if r[0] is not None]
    print(f"Total distinct user IDs referenced across all Help Desk tables: {len(user_ids)}")

    # 2. Test remapping for each user
    id_map = {}
    missing = []
    
    # Specific known fallbacks
    known_fallbacks = {
        'kiran.k@sreenidhi.edu.in': 598,
        'abhishek.c@sreenidhi.edu.in': 2873,
        't_1253@sreenidhi.edu.in': 748,
    }

    for uid in user_ids:
        hu = conn.execute(text("SELECT id, name, email, role FROM helpdesk_users WHERE id = :id"), {"id": uid}).fetchone()
        if not hu:
            missing.append((uid, "NOT_IN_HELPDESK_USERS"))
            continue
        
        email = (hu[2] or "").strip().lower()
        role = hu[3]
        
        # Check teacher_info
        ti = conn.execute(text("SELECT TEACHER_ID FROM teacher_info WHERE LOWER(EMAIL_ID) = :email LIMIT 1"), {"email": email}).fetchone()
        if ti:
            id_map[uid] = ti[0]
        elif email in known_fallbacks:
            id_map[uid] = known_fallbacks[email]
        elif email in ("admin@gmail.com", "campus.admin@gmail.com", "hod@gmail.com", "ca@gmail.com", "faculty@gmail.com", "snu.admin@gmail.com"):
            # Will map to staff roles or demo admin
            id_map[uid] = uid  # Retain admin ID in helpdesk_staff_roles
        else:
            missing.append((uid, hu[1], email, role))

    print(f"Successfully mapped: {len(id_map)} / {len(user_ids)}")
    if missing:
        print(f"Missing / unmapped users ({len(missing)}):")
        for m in missing:
            print(" ", m)
    else:
        print("PERFECT: 100% of referenced users are mapped!")

    conn.close()

if __name__ == "__main__":
    test_mapping()
