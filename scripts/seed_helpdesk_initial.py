import os
import pymysql
from werkzeug.security import generate_password_hash

DB_HOST = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in")
DB_USER = os.getenv("MYSQL_USER", "demo")
DB_PASS = os.getenv("MYSQL_PASSWORD", "")
DB_PORT = int(os.getenv("MYSQL_PORT", "3306"))

DEFAULT_STAFF = [
    {"name": "Super Admin", "email": "admin@gmail.com", "role": "SUPER_ADMIN", "department": "Administration", "password": "123"},
    {"name": "Campus Admin", "email": "campus.admin@gmail.com", "role": "ADMIN", "department": "Administration", "password": "123"},
    {"name": "CTO Admin", "email": "cto@sreenidhi.edu.in", "role": "SUPER_ADMIN", "department": "CTO", "password": None},
    {"name": "Srinivas SAP", "email": "srinivas.n@sreenidhi.edu.in", "role": "SUPER_ADMIN", "department": "SAP", "password": None},
    {"name": "ICT Manager", "email": "managerict@sreenidhi.edu.in", "role": "CA", "department": "ICT", "password": None},
    {"name": "Facilities Manager", "email": "managerfs@sreenidhi.edu.in", "role": "CA", "department": "Facilities", "password": None},
    {"name": "HCM Executive", "email": "ramkumar.b@sreenidhi.edu.in", "role": "CA", "department": "HCM", "password": None},
    {"name": "MM Executive", "email": "chakradhar.n@sreenidhi.edu.in", "role": "CA", "department": "MM", "password": None},
]

DEFAULT_CATEGORIES = [
    # ICT & Systems
    {"name": "Internet & Wi-Fi", "department": "ICT"},
    {"name": "Computer & Peripherals", "department": "ICT"},
    {"name": "LCD Projector & AV", "department": "ICT"},
    {"name": "Printers & Scanners", "department": "ICT"},
    {"name": "Software & Operating System", "department": "ICT"},
    {"name": "ERP & Portal Access", "department": "SAP"},
    # Facilities & Estates
    {"name": "Plumbing & Water Supply", "department": "Facilities"},
    {"name": "Electrical & Lighting", "department": "Facilities"},
    {"name": "Air Conditioning (AC)", "department": "Facilities"},
    {"name": "Classroom & Lab Furniture", "department": "Facilities"},
    {"name": "Housekeeping & Cleanliness", "department": "Facilities"},
    # Transport
    {"name": "Campus Transport & Buses", "department": "Transport"},
    # General / Academic
    {"name": "Lab Equipment Maintenance", "department": "CSE"},
    {"name": "Lab Equipment Maintenance", "department": "ECE"},
    {"name": "Lab Equipment Maintenance", "department": "EEE"},
    {"name": "Lab Equipment Maintenance", "department": "ME"},
]

DEFAULT_PROBLEMS = {
    "Internet & Wi-Fi": ["Wi-Fi Disconnected / Weak Signal", "LAN Cable / Port Fault", "Slow Internet Speed", "IP Address Conflict"],
    "Computer & Peripherals": ["System Not Powering On", "Keyboard / Mouse Not Working", "Monitor Display Issue", "RAM / Storage Failure"],
    "LCD Projector & AV": ["No Display / HDMI Signal Lost", "Projector Lamp Failure", "Audio / Speaker Issue", "Remote Control Missing/Fault"],
    "Printers & Scanners": ["Paper Jam", "Cartridge / Toner Empty", "Network Printer Offline", "Scanner Not Responding"],
    "Software & Operating System": ["OS Crash / Blue Screen", "Antivirus / License Issue", "Software Installation Request", "Slow System Performance"],
    "Plumbing & Water Supply": ["Water Supply Disruption", "Tap / Pipeline Leakage", "Washroom Drain Blocked", "Water Cooler Fault"],
    "Electrical & Lighting": ["Power Tripped / No Power", "Tube Light / Fan Fault", "Burnt Switch / Socket", "UPS Backup Failure"],
    "Air Conditioning (AC)": ["AC Not Cooling", "AC Water Dripping", "AC Remote / Thermostat Fault", "AC Not Powering On"],
}

def seed():
    conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASS, database="helpdesk", port=DB_PORT)
    with conn.cursor() as cur:
        # 1. Staff roles
        print("Seeding helpdesk_staff_roles...")
        for s in DEFAULT_STAFF:
            pwd_hash = generate_password_hash(s["password"]) if s["password"] else None
            # Find teacher_id from sreenidhi.teacher_info if exists
            cur.execute("SELECT TEACHER_ID FROM sreenidhi.teacher_info WHERE LOWER(EMAIL_ID) = LOWER(%s) LIMIT 1", (s["email"],))
            t_row = cur.fetchone()
            teacher_id = t_row[0] if t_row else None
            
            cur.execute("""
                INSERT INTO helpdesk_staff_roles (teacher_id, name, email, password_hash, role, department)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE role = VALUES(role), department = VALUES(department), teacher_id = VALUES(teacher_id)
            """, (teacher_id, s["name"], s["email"], pwd_hash, s["role"], s["department"]))
        
        # 2. Categories
        print("Seeding helpdesk_categories...")
        cat_id_map = {}
        for c in DEFAULT_CATEGORIES:
            cur.execute("""
                INSERT INTO helpdesk_categories (category_name, department, is_active)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE is_active = 1
            """, (c["name"], c["department"]))
            cur.execute("SELECT id FROM helpdesk_categories WHERE category_name = %s AND department = %s", (c["name"], c["department"]))
            cat_id_map[c["name"]] = cur.fetchone()[0]

        # 3. Problem Types
        print("Seeding helpdesk_problem_types...")
        for cat_name, problems in DEFAULT_PROBLEMS.items():
            cat_id = cat_id_map.get(cat_name)
            if not cat_id:
                continue
            for prob in problems:
                cur.execute("""
                    INSERT INTO helpdesk_problem_types (category_id, problem_name, is_active)
                    VALUES (%s, %s, 1)
                    ON DUPLICATE KEY UPDATE is_active = 1
                """, (cat_id, prob))

        conn.commit()
        print("Seeding completed successfully!")
    conn.close()

if __name__ == "__main__":
    seed()
