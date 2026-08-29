from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db_services import DemoDbService, LiveDbService, env_db_config


def main():
    config = env_db_config()
    if not config:
        raise SystemExit("MYSQL_* environment variables are required.")

    demo_service = DemoDbService(config)
    live_service = LiveDbService(config)
    schema_path = ROOT / "sql" / "demo_schema.sql"
    demo_service.ensure_schema(schema_path)

    # Seed default departments in branch_detail if empty
    with demo_service.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM branch_detail")
        row = cur.fetchone()
        count = row.get("count", 0) if isinstance(row, dict) else (row[0] if row else 0)
        if count == 0:
            default_depts = [
                ("CSE", "Computer Science & Engineering", "2000"),
                ("ECE", "Electronics & Communication Engineering", "2000"),
                ("Facilities", "Facilities & Estates", "2000"),
                ("Maintenance", "Campus Maintenance", "2000"),
                ("Administration", "Campus Administration", "2000"),
                ("ICT", "Information & Communication Technology", "2000"),
                ("HCM", "Human Capital Management", "2000"),
                ("Fecilities", "Facilities Management", "2000"),
                ("PM", "Project Management & Transport", "2000"),
                ("MM", "Materials Management", "2000"),
                ("LSM", "Logistics & Services Management", "2000"),
            ]
            for code, name, org in default_depts:
                cur.execute(
                    "INSERT IGNORE INTO branch_detail (BRANCH_CODE, BRANCH_NAME, ORG_ID) VALUES (%s, %s, %s)",
                    (code, name, org)
                )
            print(f"Seeded {len(default_depts)} departments in branch_detail.")

    # Seed default locations in location table
    with demo_service.connection() as conn, conn.cursor() as cur:
        default_locations = [
            ("Block-I", "Ground Floor", "1106", "Seminar Hall", "2000"),
            ("Block-I", "1st Floor", "1205", "Classroom 1205", "2000"),
            ("Block-II", "Ground Floor", "2104", "Lab 2104", "2000"),
            ("Block-III", "1st Floor", "3116", "CSE Lab 3116", "2000"),
            ("Block-IV", "2nd Floor", "4109", "ECE Lab 4109", "2000"),
            ("Block-IV", "2nd Floor", "4211", "ECE Lab 4211", "2000"),
            ("Block-V", "1st Floor", "5105", "ICT Lab 5105", "2000"),
            ("Block-V", "2nd Floor", "5201", "Faculty Room 5201", "2000"),
            ("Block-VI", "Ground Floor", "6002", "Classroom 6002", "2000"),
            ("Block-VII", "1st Floor", "7105", "Civil Lab 7105", "2000"),
            ("Block-VIII", "Ground Floor", "8004", "Studio 8004", "2000"),
            ("Block-IX", "1st Floor", "9109", "Classroom 9109", "2000"),
            ("Block-X", "1st Floor", "10105", "Classroom 10105", "2000"),
            ("Block-XI", "1st Floor", "11104", "Lab 11104", "2000"),
            ("Block-XII", "1st Floor", "12107", "Classroom 12107", "2000"),
            ("Block-XIII", "1st Floor", "13104", "Classroom 13104", "2000"),
            ("Admin Block", "Ground Floor", "ADM-01", "Principal Office", "2000"),
            ("Admin Block", "1st Floor", "5105", "Administrative Office", "2000"),
            ("Central Library", "1st Floor", "LIB-7115", "Reading Room", "2000"),
            ("1st year block", "1st Floor", "4109", "First Year Lab", "2000"),
            ("Biotech Block", "Ground Floor", "4109", "Biotech Lab", "2000"),
            ("Security / CCTV", "Ground Floor", "SEC-01", "Security Office", "2000"),
            ("Canteen", "Ground Floor", "CAN-01", "Campus Canteen", "2000"),
        ]
        for block, floor, room_no, name, org in default_locations:
            cur.execute(
                "INSERT INTO location (block, floor, room_no, name, ORG_ID) VALUES (%s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name)",
                (block, floor, room_no, name, org)
            )
        print(f"Seeded {len(default_locations)} locations in location table.")
    
    # Base required users for system operation across all departments
    users = [
        # Administration (including real CTO and SAP Super Admin from sys_administrators)
        {"name": "Super Admin", "email": "admin@gmail.com", "password": "123", "role": "SUPER_ADMIN", "department": "Administration", "phone": "9704083464"},
        {"name": "Suresh Gurala (CTO)", "email": "cto@sreenidhi.edu.in", "password": "123", "role": "SUPER_ADMIN", "department": "Administration", "phone": "9949994071"},
        {"name": "Naluvala Srinivas (SAP)", "email": "srinivas.n@sreenidhi.edu.in", "password": "123", "role": "SUPER_ADMIN", "department": "Administration", "phone": "9948033225"},
        {"name": "Campus Admin", "email": "campus.admin@gmail.com", "password": "123", "role": "ADMIN", "department": "Administration", "phone": "9704083464"},
        {"name": "Registrar Admin", "email": "registrar@snist.edu.in", "password": "123", "role": "ADMIN", "department": "Administration", "phone": "9704083464"},

        # CSE Department
        {"name": "Dr. Kavya", "email": "hod@gmail.com", "password": "123", "role": "HOD", "department": "CSE", "phone": "9704083464"},
        {"name": "Chandini", "email": "ca@gmail.com", "password": "123", "role": "CA", "department": "CSE", "phone": "9704083464"},
        {"name": "Prof. Rajesh Kumar", "email": "rajesh.cse@snist.edu.in", "password": "123", "role": "CA", "department": "CSE", "phone": "9704083464"},
        {"name": "Prof. Ananya Sharma", "email": "ananya.cse@snist.edu.in", "password": "123", "role": "FACULTY", "department": "CSE", "phone": "9704083464"},
        {"name": "Dr. Vikram Reddy", "email": "vikram.cse@snist.edu.in", "password": "123", "role": "FACULTY", "department": "CSE", "phone": "9704083464"},
        {"name": "Prof. Sneha Patel", "email": "sneha.cse@snist.edu.in", "password": "123", "role": "FACULTY", "department": "CSE", "phone": "9704083464"},
        {"name": "Demo Faculty", "email": "faculty@gmail.com", "password": "123", "role": "FACULTY", "department": "CSE", "phone": "9704083464"},

        # ECE Department
        {"name": "Dr. Harini", "email": "hod.ece@gmail.com", "password": "123", "role": "HOD", "department": "ECE", "phone": "9704083464"},
        {"name": "Suresh ECE", "email": "suresh.ece@snist.edu.in", "password": "123", "role": "CA", "department": "ECE", "phone": "9704083464"},
        {"name": "Dr. Priya Nair", "email": "priya.ece@snist.edu.in", "password": "123", "role": "FACULTY", "department": "ECE", "phone": "9704083464"},
        {"name": "Prof. Ramesh Rao", "email": "ramesh.ece@snist.edu.in", "password": "123", "role": "FACULTY", "department": "ECE", "phone": "9704083464"},
        {"name": "Prof. Arvind Swamy", "email": "arvind.ece@snist.edu.in", "password": "123", "role": "FACULTY", "department": "ECE", "phone": "9704083464"},

        # ICT Department (Real in-charges & CAs from sys_administrators)
        {"name": "Dr. Mohan ICT", "email": "hod.ict@snist.edu.in", "password": "123", "role": "HOD", "department": "ICT", "phone": "9704083464"},
        {"name": "lmmanuel Wonderful C J", "email": "managerict@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "9550204783"},
        {"name": "Jitta Chandra Shekar Reddy", "email": "shekar.j@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "9885584904"},
        {"name": "Yekollu Sathish Balaji", "email": "balaji.y@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "8142104528"},
        {"name": "Dasi Anil Kumar", "email": "anil.d@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "7661926630"},
        {"name": "Y Ravi Shanker", "email": "ravishanker.y@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "9848392356"},
        {"name": "V.V. Ravi Kiran", "email": "ravikiran.v@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "9849426996"},
        {"name": "Varala Praveen", "email": "praveen.v@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "9704083464"},
        {"name": "ICT CA", "email": "ict.ca@gmail.com", "password": "123", "role": "CA", "department": "ICT", "phone": "9704083464"},
        {"name": "Prof. Kalyan Varma", "email": "kalyan.ict@snist.edu.in", "password": "123", "role": "CA", "department": "ICT", "phone": "9704083464"},
        {"name": "Prof. Divya Teja", "email": "divya.ict@snist.edu.in", "password": "123", "role": "FACULTY", "department": "ICT", "phone": "9704083464"},
        {"name": "Dr. Santosh Kumar", "email": "santosh.ict@snist.edu.in", "password": "123", "role": "FACULTY", "department": "ICT", "phone": "9704083464"},

        # Facilities & Estates / Facilities Management (Real in-charges from sys_administrators)
        {"name": "Vinod Kumar M", "email": "managerfs@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "Facilities", "phone": "8712220028"},
        {"name": "Andekar Jayanthi", "email": "jayanthi.a@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "Facilities", "phone": "9704083464"},
        {"name": "Sravan", "email": "sravan.ca@gmail.com", "password": "123", "role": "CA", "department": "Facilities", "phone": "9704083464"},
        {"name": "Venkat Facilities", "email": "venkat.fac@snist.edu.in", "password": "123", "role": "CA", "department": "Facilities", "phone": "9704083464"},
        {"name": "Naresh Kumar", "email": "naresh.fac@snist.edu.in", "password": "123", "role": "FACULTY", "department": "Facilities", "phone": "9704083464"},
        {"name": "Facilities CA", "email": "facilities.ca@gmail.com", "password": "123", "role": "CA", "department": "Fecilities", "phone": "9704083464"},
        {"name": "Shiva Facilities", "email": "shiva.fm@snist.edu.in", "password": "123", "role": "CA", "department": "Fecilities", "phone": "9704083464"},
        {"name": "Mahesh FM", "email": "mahesh.fm@snist.edu.in", "password": "123", "role": "FACULTY", "department": "Fecilities", "phone": "9704083464"},

        # Campus Maintenance
        {"name": "Bhaskar", "email": "bhaskar.ca@gmail.com", "password": "123", "role": "CA", "department": "Maintenance", "phone": "9704083464"},
        {"name": "Srinivas Maintenance", "email": "srinivas.maint@snist.edu.in", "password": "123", "role": "CA", "department": "Maintenance", "phone": "9704083464"},
        {"name": "Prasad Rao", "email": "prasad.maint@snist.edu.in", "password": "123", "role": "FACULTY", "department": "Maintenance", "phone": "9704083464"},

        # Human Capital Management (HCM) (Real in-charge from sys_administrators)
        {"name": "Ram Kumar", "email": "ramkumar.b@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "HCM", "phone": "7989432617"},
        {"name": "HCM CA", "email": "hcm.ca@gmail.com", "password": "123", "role": "CA", "department": "HCM", "phone": "9704083464"},
        {"name": "Lakshmi HCM", "email": "lakshmi.hcm@snist.edu.in", "password": "123", "role": "CA", "department": "HCM", "phone": "9704083464"},
        {"name": "Raghu HCM", "email": "raghu.hcm@snist.edu.in", "password": "123", "role": "FACULTY", "department": "HCM", "phone": "9704083464"},

        # Materials Management (MM) (Real in-charge from sys_administrators)
        {"name": "Nakketla Chakradhar", "email": "chakradhar.n@sreenidhi.edu.in", "password": "123", "role": "CA", "department": "MM", "phone": "9000844325"},
        {"name": "MM CA", "email": "mm.ca@gmail.com", "password": "123", "role": "CA", "department": "MM", "phone": "9704083464"},
        {"name": "Govind MM", "email": "govind.mm@snist.edu.in", "password": "123", "role": "CA", "department": "MM", "phone": "9704083464"},
        {"name": "Sunita MM", "email": "sunita.mm@snist.edu.in", "password": "123", "role": "FACULTY", "department": "MM", "phone": "9704083464"},

        # Project Management & Transport (PM) (Real in-charge from sys_administrators)
        {"name": "Bhagi Babu", "email": "nt0070@snist.edu.in", "password": "123", "role": "CA", "department": "PM", "phone": "9848019414"},
        {"name": "PM CA", "email": "pm.ca@gmail.com", "password": "123", "role": "CA", "department": "PM", "phone": "9704083464"},
        {"name": "Krishna PM", "email": "krishna.pm@snist.edu.in", "password": "123", "role": "CA", "department": "PM", "phone": "9704083464"},
        {"name": "Anand PM", "email": "anand.pm@snist.edu.in", "password": "123", "role": "FACULTY", "department": "PM", "phone": "9704083464"},

        # Logistics & Services Management (LSM)
        {"name": "LSM CA", "email": "lsm.ca@gmail.com", "password": "123", "role": "CA", "department": "LSM", "phone": "9704083464"},
        {"name": "Madhav LSM", "email": "madhav.lsm@snist.edu.in", "password": "123", "role": "CA", "department": "LSM", "phone": "9704083464"},
        {"name": "Kavitha LSM", "email": "kavitha.lsm@snist.edu.in", "password": "123", "role": "FACULTY", "department": "LSM", "phone": "9704083464"},
    ]
    seen_emails = {u["email"].lower() for u in users}

    # Fetch real users from teacher_info
    print("Fetching users from teacher_info...")
    try:
        live_users = live_service.fetch_reference_users(limit=10000)
        for u in live_users:
            email = u.get("EMAIL_ID")
            if email and email.strip() and email.lower() not in seen_emails:
                seen_emails.add(email.lower())
                dept = u.get("department_code") or u.get("department_name") or "Facilities"
                users.append({
                    "name": u.get("TEACHER_NAME") or "Unknown Teacher",
                    "email": email.strip(),
                    "password": "123",
                    "role": "FACULTY",
                    "department": dept,
                    "phone": u.get("MOBILE_PHONE") or None,
                })
    except Exception as exc:
        print(f"Note: teacher_info not available ({exc}), proceeding with default seed users.")

    print(f"Total users to seed: {len(users)}")
    demo_service.seed_defaults(
        users,
        [
            # Original legacy categories
            {"category_name": "Internet", "department": "CSE", "authority_email": "ca@gmail.com"},
            {"category_name": "Projector", "department": "CSE", "authority_email": "ca@gmail.com"},
            {"category_name": "Plumbing", "department": "Facilities", "authority_email": "bhaskar.ca@gmail.com"},
            {"category_name": "Electrical", "department": "Maintenance", "authority_email": "bhaskar.ca@gmail.com"},

            # ICT categories
            {"category_name": "Desktop", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Desktop instalation", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "LCD projector", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Laptop", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Printer", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Scanner", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Mouse", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Software", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Configuration", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Wi-fi", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "LAN", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Internet", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Key Board", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Monitor", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "CPU", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Operating System", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Class Room Speakers", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Biometric", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Technical Support", "department": "ICT", "authority_email": "ict.ca@gmail.com"},
            {"category_name": "Others", "department": "ICT", "authority_email": "ict.ca@gmail.com"},

            # HCM categories
            {"category_name": "Payroll", "department": "HCM", "authority_email": "hcm.ca@gmail.com"},
            {"category_name": "Leaves", "department": "HCM", "authority_email": "hcm.ca@gmail.com"},
            {"category_name": "SF", "department": "HCM", "authority_email": "hcm.ca@gmail.com"},
            {"category_name": "Others", "department": "HCM", "authority_email": "hcm.ca@gmail.com"},

            # Fecilities categories
            {"category_name": "Electrical issues (lights, outlets, fans)", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "Plumbing (leaks, water supply, washrooms)", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "Furniture repair or replacement(Staff chairs, plastic chair)", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "HVAC (heating, ventilation, air conditioning)", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "Housekeeping and general cleanliness", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "Washroom cleanliness", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "Classroom setup or examination arrangement", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "Event logistics and on-site support", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},
            {"category_name": "Lost & Found, Safety Concerns or Incidents", "department": "Fecilities", "authority_email": "facilities.ca@gmail.com"},

            # PM categories
            {"category_name": "PM", "department": "PM", "authority_email": "pm.ca@gmail.com"},

            # MM categories
            {"category_name": "MM", "department": "MM", "authority_email": "mm.ca@gmail.com"},

            # LSM categories
            {"category_name": "LSM", "department": "LSM", "authority_email": "lsm.ca@gmail.com"},
        ],
    )
    print("demo schema initialized")


if __name__ == "__main__":
    main()
