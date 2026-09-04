"""
fix_assigned_to.py
==================
Fix the "Assigned To" situation across helpdesk users, categories,
multi-CA block assignments, and ticket assignments.

1. Promote/align roles of real technicians & in-charges to CA.
2. Ensure newly identified staff from teacher_info exist with CA role.
3. Configure multi-CA block assignments in helpdesk_ca_assignments for ICT, Facilities, HCM, MM, PM, Maintenance.
4. Set realistic default assigned_ca_id on helpdesk_categories.
5. Re-resolve assigned_to on all existing tickets (remove Super Admin misassignments, distribute ICT tickets accurately by block).

Usage:
  python scripts/fix_assigned_to.py
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash
from db_services import DemoDbService, env_db_config


def main():
    config = env_db_config()
    if not config:
        raise SystemExit("MYSQL_* environment variables are required.")

    demo_db = DemoDbService(config)
    if not demo_db.enabled:
        raise SystemExit("Cannot connect to database.")

    print("=" * 70)
    print("STEP 1: Promoting / Aligning Real Assignee (CA) Roles")
    print("=" * 70)

    # Real technicians and in-charges that should have role CA
    real_cas = [
        # ICT Technicians & CAs
        {"name": "JITTA CHANDRA SHEKAR REDDY", "email": "shekar.j@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "9885584904"},
        {"name": "YEKOLLU SATHISH BALAJI", "email": "balaji.y@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "8142104528"},
        {"name": "DASI ANIL KUMAR", "email": "anil.d@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "7661926630"},
        {"name": "Y RAVI SHANKER", "email": "ravishanker.y@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "9848392356"},
        {"name": "V.V. RAVI KIRAN", "email": "ravikiran.v@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "9849426996"},
        {"name": "Varala Praveen", "email": "praveen.v@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "7093318844"},
        {"name": "Ponnam Naga Raju", "email": "nagaraju.p@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "7702804679"},
        {"name": "YALALA SRI CHARAN VARMA", "email": "sricharan.y@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "7981978520"},
        {"name": "lmmanuel Wonderful C J", "email": "managerict@sreenidhi.edu.in", "role": "CA", "department": "ICT", "phone": "9550204783"},

        # Facilities CAs & In-charges
        {"name": "Musaramthota Vinod Kumar", "email": "managerfs@sreenidhi.edu.in", "role": "CA", "department": "Facilities", "phone": "9701266338"},
        {"name": "ANDEKAR JAYANTHI", "email": "jayanthi.a@sreenidhi.edu.in", "role": "CA", "department": "Facilities", "phone": "9989053551"},
        {"name": "Vanukuru Venkata Rami Reddy", "email": "gph@sreenidhi.edu.in", "role": "CA", "department": "Facilities", "phone": "9848021473"},
        {"name": "JANNAP REDDY DAYAKAR REDDY", "email": "headelectrical@sreenidhi.edu.in", "role": "CA", "department": "Facilities", "phone": "9948319111"},
        {"name": "VEMULA RAMDAS", "email": "so@sreenidhi.edu.in", "role": "CA", "department": "Facilities", "phone": "9912373000"},
        {"name": "Sravan", "email": "sravan.ca@gmail.com", "role": "CA", "department": "Facilities", "phone": "9704083464"},

        # Human Capital Management (HCM)
        {"name": "BODDUNA RAMKUMAR", "email": "ramkumar.b@sreenidhi.edu.in", "role": "CA", "department": "HCM", "phone": "9989172000"},

        # Materials Management (MM)
        {"name": "NAKKETLA CHAKRADHAR", "email": "chakradhar.n@sreenidhi.edu.in", "role": "CA", "department": "MM", "phone": "9000844325"},

        # Project Management & Transport (PM)
        {"name": "BHAGI BABU", "email": "babu.b@sreenidhi.edu.in", "role": "CA", "department": "PM", "phone": "9848019414"},

        # Campus Maintenance
        {"name": "Bhaskar", "email": "bhaskar.ca@gmail.com", "role": "CA", "department": "Maintenance", "phone": "9704083464"},

        # CSE
        {"name": "Chandini", "email": "ca@gmail.com", "role": "CA", "department": "CSE", "phone": "9848012345"},
        {"name": "A.LAVANYA", "email": "t_1253@sreenidhi.edu.in", "role": "CA", "department": "CSE", "phone": "9849123456"},
        {"name": "T SHIRISHA", "email": "shirisha.t@sreenidhi.edu.in", "role": "CA", "department": "CSE", "phone": "9182560056"},
    ]

    default_pwd_hash = generate_password_hash("123")
    user_id_map = {}

    with demo_db.connection() as conn, conn.cursor() as cur:
        for u in real_cas:
            cur.execute("SELECT id, role, department, phone FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (u["email"],))
            row = cur.fetchone()
            if row:
                user_id = row["id"]
                # Update role and department and phone
                cur.execute(
                    "UPDATE helpdesk_users SET role = %s, department = %s, phone = COALESCE(%s, phone) WHERE id = %s",
                    (u["role"], u["department"], u["phone"], user_id),
                )
                print(f"  Updated CA user: {u['name']} ({u['email']}) -> role={u['role']}, dept={u['department']}")
            else:
                cur.execute(
                    """
                    INSERT INTO helpdesk_users (name, email, password, role, department, phone)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (u["name"], u["email"], default_pwd_hash, u["role"], u["department"], u["phone"]),
                )
                user_id = cur.lastrowid
                print(f"  Inserted new CA user: {u['name']} ({u['email']}) -> id={user_id}")
            user_id_map[u["email"].lower()] = user_id

    print("\n" + "=" * 70)
    print("STEP 2: Updating Category Default Assignees")
    print("=" * 70)

    # Preferred default CA per department
    dept_default_ca_email = {
        "ICT": "shekar.j@sreenidhi.edu.in",
        "Facilities": "managerfs@sreenidhi.edu.in",
        "Fecilities": "managerfs@sreenidhi.edu.in",
        "HCM": "ramkumar.b@sreenidhi.edu.in",
        "MM": "chakradhar.n@sreenidhi.edu.in",
        "PM": "babu.b@sreenidhi.edu.in",
        "Maintenance": "bhaskar.ca@gmail.com",
        "CSE": "ca@gmail.com",
    }

    with demo_db.connection() as conn, conn.cursor() as cur:
        for dept, email in dept_default_ca_email.items():
            ca_id = user_id_map.get(email.lower())
            if not ca_id:
                cur.execute("SELECT id FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
                r = cur.fetchone()
                ca_id = r["id"] if r else None

            if ca_id:
                cur.execute(
                    "UPDATE helpdesk_categories SET assigned_ca_id = %s WHERE department = %s",
                    (ca_id, dept),
                )
                print(f"  Set default CA for '{dept}' categories -> user_id={ca_id} ({email})")

        # Specific category overrides
        elec_ca_id = user_id_map.get("headelectrical@sreenidhi.edu.in")
        if elec_ca_id:
            cur.execute(
                "UPDATE helpdesk_categories SET assigned_ca_id = %s WHERE category_name LIKE '%%Electrical%%' AND department IN ('Facilities', 'Fecilities')",
                (elec_ca_id,),
            )
            print(f"  Set Facilities Electrical categories -> Dayakar Reddy (user_id={elec_ca_id})")

    print("\n" + "=" * 70)
    print("STEP 3: Populating Multi-CA Block Assignments (helpdesk_ca_assignments)")
    print("=" * 70)

    # Campus blocks mapping to specific ICT CAs
    ict_block_mappings = [
        # Balaji -> Block-IV, Block-VIII, 1st year block, Biotech Block
        ("balaji.y@sreenidhi.edu.in", ["Block-IV", "Block-VIII", "1st year block", "Biotech Block"]),
        # Ravi Shanker -> Block-V, Block-VII, Admin Block, CCTV/Security room, Security&CCTV, Block-III
        ("ravishanker.y@sreenidhi.edu.in", ["Block-V", "Block-VII", "Admin Block", "CCTV/Security room", "Security&CCTV", "Block-III"]),
        # Ravi Kiran -> Block-II, Block-2
        ("ravikiran.v@sreenidhi.edu.in", ["Block-II", "Block-2"]),
        # Naga Raju -> Block-X, Block-XI, Block-XII, Block-XIII, Block-IX, Block-VI
        ("nagaraju.p@sreenidhi.edu.in", ["Block-X", "Block-XI", "Block-XII", "Block-XIII", "Block-IX", "Block-VI"]),
        # Varala Praveen -> Block-I
        ("praveen.v@sreenidhi.edu.in", ["Block-I"]),
        # Shekar Reddy -> Central Library, University Block, Others, All Blocks
        ("shekar.j@sreenidhi.edu.in", ["Central Library", "Centeral library", "University Block", "Others", "All Blocks"]),
        # Anil Kumar -> All Blocks
        ("anil.d@sreenidhi.edu.in", ["All Blocks"]),
        # Sri Charan Varma -> All Blocks
        ("sricharan.y@sreenidhi.edu.in", ["All Blocks"]),
    ]

    with demo_db.connection() as conn, conn.cursor() as cur:
        # Get all ICT categories
        cur.execute("SELECT id, category_name FROM helpdesk_categories WHERE department = 'ICT'")
        ict_cats = cur.fetchall()

        assignments_created = 0
        for ca_email, blocks in ict_block_mappings:
            ca_id = user_id_map.get(ca_email.lower())
            if not ca_id:
                cur.execute("SELECT id FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (ca_email,))
                r = cur.fetchone()
                ca_id = r["id"] if r else None
            if not ca_id:
                continue

            for cat in ict_cats:
                for block in blocks:
                    cur.execute(
                        """
                        INSERT INTO helpdesk_ca_assignments (category_id, ca_id, block)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE ca_id = VALUES(ca_id)
                        """,
                        (cat["id"], ca_id, block),
                    )
                    assignments_created += 1

        print(f"  Created/Updated {assignments_created} ICT block assignments across {len(ict_cats)} categories")

        # Facilities block assignments
        cur.execute("SELECT id, category_name FROM helpdesk_categories WHERE department IN ('Facilities', 'Fecilities')")
        fac_cats = cur.fetchall()
        fac_ca_id = user_id_map.get("managerfs@sreenidhi.edu.in")
        jayanthi_id = user_id_map.get("jayanthi.a@sreenidhi.edu.in")

        fac_assignments = 0
        for cat in fac_cats:
            if fac_ca_id:
                cur.execute(
                    "INSERT INTO helpdesk_ca_assignments (category_id, ca_id, block) VALUES (%s, %s, 'All Blocks') ON DUPLICATE KEY UPDATE ca_id=VALUES(ca_id)",
                    (cat["id"], fac_ca_id),
                )
                fac_assignments += 1
            if jayanthi_id:
                for b in ["Admin Block", "Central Library", "Centeral library", "Canteen"]:
                    cur.execute(
                        "INSERT INTO helpdesk_ca_assignments (category_id, ca_id, block) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE ca_id=VALUES(ca_id)",
                        (cat["id"], jayanthi_id, b),
                    )
                    fac_assignments += 1

        print(f"  Created/Updated {fac_assignments} Facilities block assignments across {len(fac_cats)} categories")

    print("\n" + "=" * 70)
    print("STEP 4: Re-Resolving Ticket Assignees (Balancing & Accuracy)")
    print("=" * 70)

    # Block matching helper for ICT tickets
    def resolve_ict_assignee(block_name: str, created_by_id: int):
        b = (block_name or "").lower().strip()
        # If the ticket was raised by a technician who attends that block, keep them
        balaji_id = user_id_map.get("balaji.y@sreenidhi.edu.in")
        shanker_id = user_id_map.get("ravishanker.y@sreenidhi.edu.in")
        kiran_id = user_id_map.get("ravikiran.v@sreenidhi.edu.in")
        nagaraju_id = user_id_map.get("nagaraju.p@sreenidhi.edu.in")
        praveen_id = user_id_map.get("praveen.v@sreenidhi.edu.in")
        shekar_id = user_id_map.get("shekar.j@sreenidhi.edu.in")
        anil_id = user_id_map.get("anil.d@sreenidhi.edu.in")

        # Exact technician checks
        if "block-iv" in b or "block-4" in b or "block-viii" in b or "block-8" in b or "1st year" in b or "biotech" in b:
            return balaji_id
        if "block-v" in b or "block-5" in b or "block-vii" in b or "block-7" in b or "admin" in b or "cctv" in b or "security" in b or "block-iii" in b or "block-3" in b:
            return shanker_id
        if "block-ii" in b or "block-2" in b:
            return kiran_id
        if any(x in b for x in ["block-x", "block-xi", "block-xii", "block-xiii", "block-ix", "block-vi", "block-6", "block-9", "block-10", "block-11", "block-12", "block-13"]):
            return nagaraju_id
        if "block-i" in b or "block-1" in b:
            return praveen_id or shanker_id
        if "library" in b or "university" in b or "others" in b:
            return shekar_id
        return anil_id or shekar_id

    with demo_db.connection() as conn, conn.cursor() as cur:
        # Fetch all tickets with their details
        cur.execute("""
            SELECT t.id, t.title, t.category_id, t.created_by, t.assigned_to,
                   c.category_name, c.department,
                   l.block as loc_block
            FROM helpdesk_tickets t
            JOIN helpdesk_categories c ON t.category_id = c.id
            LEFT JOIN location l ON t.location_id = l.id
        """)
        all_tickets = cur.fetchall()

        reassigned_count = 0
        super_admin_fixed = 0

        maint_ca = user_id_map.get("bhaskar.ca@gmail.com")
        cse_ca = user_id_map.get("ca@gmail.com") or user_id_map.get("t_1253@sreenidhi.edu.in")
        fac_ca = user_id_map.get("managerfs@sreenidhi.edu.in")
        hcm_ca = user_id_map.get("ramkumar.b@sreenidhi.edu.in")
        mm_ca = user_id_map.get("chakradhar.n@sreenidhi.edu.in")
        pm_ca = user_id_map.get("babu.b@sreenidhi.edu.in")

        for t in all_tickets:
            tid = t["id"]
            dept = t["department"]
            cat_name = t["category_name"]
            curr_assigned = t["assigned_to"]
            block = t["loc_block"] or ""

            # Extract block from title if not in location
            if not block:
                title = t["title"] or ""
                block_match = re.search(r"at\s+([^-\n]+?)\s+-", title, re.IGNORECASE)
                if block_match:
                    block = block_match.group(1).strip()
                elif "Block-" in title or "Admin Block" in title or "library" in title.lower():
                    for token in ["Block-XIII", "Block-XII", "Block-XI", "Block-VIII", "Block-VII", "Block-VI",
                                  "Block-V", "Block-IV", "Block-III", "Block-II", "Block-I", "Block-2",
                                  "Admin Block", "Centeral library", "Central Library", "University Block", "1st year block"]:
                        if token.lower() in title.lower():
                            block = token
                            break

            new_assigned = None

            # 1. Fix Super Admin (id=1) misassignments
            if curr_assigned == 1:
                super_admin_fixed += 1
                if dept == "Maintenance":
                    new_assigned = maint_ca
                elif dept == "CSE":
                    new_assigned = cse_ca
                elif dept in ("Facilities", "Fecilities"):
                    new_assigned = fac_ca
                elif dept == "ICT":
                    new_assigned = resolve_ict_assignee(block, t["created_by"])
                else:
                    new_assigned = maint_ca

            # 2. Fix ICT tickets (currently all assigned to 871)
            elif dept == "ICT":
                target_ca = resolve_ict_assignee(block, t["created_by"])
                if target_ca and target_ca != curr_assigned:
                    new_assigned = target_ca

            # 3. Department specific fixes
            elif dept in ("Facilities", "Fecilities") and curr_assigned not in [user_id_map.get("managerfs@sreenidhi.edu.in"), user_id_map.get("jayanthi.a@sreenidhi.edu.in"), user_id_map.get("headelectrical@sreenidhi.edu.in")]:
                if "electrical" in cat_name.lower():
                    new_assigned = user_id_map.get("headelectrical@sreenidhi.edu.in") or fac_ca
                else:
                    new_assigned = fac_ca

            elif dept == "HCM" and hcm_ca and curr_assigned != hcm_ca:
                new_assigned = hcm_ca

            elif dept == "MM" and mm_ca and curr_assigned != mm_ca:
                new_assigned = mm_ca

            elif dept == "PM" and pm_ca and curr_assigned != pm_ca:
                new_assigned = pm_ca

            # Apply reassignment
            if new_assigned and new_assigned != curr_assigned:
                cur.execute("UPDATE helpdesk_tickets SET assigned_to = %s WHERE id = %s", (new_assigned, tid))
                reassigned_count += 1

        print(f"  Fixed {super_admin_fixed} tickets previously assigned to Super Admin")
        print(f"  Reassigned a total of {reassigned_count} tickets to their accurate block CAs")

    print("\n" + "=" * 70)
    print("STEP 5: Verification & Distribution Report")
    print("=" * 70)

    with demo_db.connection() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT t.assigned_to, u.name, u.email, u.role, u.department, COUNT(*) as ticket_count
            FROM helpdesk_tickets t
            LEFT JOIN helpdesk_users u ON t.assigned_to = u.id
            GROUP BY t.assigned_to, u.name, u.email, u.role, u.department
            ORDER BY ticket_count DESC
        """)
        rows = cur.fetchall()
        print(f"\n  Final Ticket Assignment Distribution (Total tickets: {sum(r['ticket_count'] for r in rows)}):")
        for r in rows:
            print(f"    {r['name'][:30]:<32} | {r['email']:<30} | {r['department']:<14} | {r['role']:<6} | {r['ticket_count']} tickets")

        cur.execute("SELECT COUNT(*) AS cnt FROM helpdesk_ca_assignments")
        ca_assign_count = cur.fetchone()["cnt"]
        print(f"\n  Total Block-CA mappings in helpdesk_ca_assignments: {ca_assign_count}")

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM helpdesk_categories c
            JOIN helpdesk_users u ON c.assigned_ca_id = u.id
            WHERE u.role IN ('CA', 'ASSIGNEE')
        """)
        valid_ca_cats = cur.fetchone()["cnt"]
        cur.execute("SELECT COUNT(*) AS cnt FROM helpdesk_categories")
        total_cats = cur.fetchone()["cnt"]
        print(f"  Categories with valid CA: {valid_ca_cats}/{total_cats}")

    print("\n  Done! Assigned To fix complete!")


if __name__ == "__main__":
    main()
