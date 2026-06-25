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
    
    # Base required users for system operation
    users = [
        {"name": "Super Admin", "email": "admin@gmail.com", "password": "123", "role": "SUPER_ADMIN", "department": "Administration"},
        {"name": "Campus Admin", "email": "campus.admin@gmail.com", "password": "123", "role": "ADMIN", "department": "Administration"},
        {"name": "Dr. Kavya", "email": "hod@gmail.com", "password": "123", "role": "HOD", "department": "CSE"},
        {"name": "Dr. Harini", "email": "hod.ece@gmail.com", "password": "123", "role": "HOD", "department": "ECE"},
        {"name": "Chandini", "email": "ca@gmail.com", "password": "123", "role": "CA", "department": "CSE"},
        {"name": "Sravan", "email": "sravan.ca@gmail.com", "password": "123", "role": "CA", "department": "Facilities"},
        {"name": "Bhaskar", "email": "bhaskar.ca@gmail.com", "password": "123", "role": "CA", "department": "Maintenance"},
        {"name": "ICT CA", "email": "ict.ca@gmail.com", "password": "123", "role": "CA", "department": "ICT"},
        {"name": "HCM CA", "email": "hcm.ca@gmail.com", "password": "123", "role": "CA", "department": "HCM"},
        {"name": "Facilities CA", "email": "facilities.ca@gmail.com", "password": "123", "role": "CA", "department": "Fecilities"},
        {"name": "PM CA", "email": "pm.ca@gmail.com", "password": "123", "role": "CA", "department": "PM"},
        {"name": "MM CA", "email": "mm.ca@gmail.com", "password": "123", "role": "CA", "department": "MM"},
        {"name": "LSM CA", "email": "lsm.ca@gmail.com", "password": "123", "role": "CA", "department": "LSM"},
    ]
    seen_emails = {u["email"].lower() for u in users}

    # Fetch real users from teacher_info
    print("Fetching users from teacher_info...")
    live_users = live_service.fetch_reference_users(limit=5000)
    for u in live_users:
        email = u.get("EMAIL_ID")
        if email and email.strip() and email.lower() not in seen_emails:
            seen_emails.add(email.lower())
            users.append({
                "name": u.get("TEACHER_NAME") or "Unknown Teacher",
                "email": email.strip(),
                "password": "123",
                "role": "FACULTY",
                "department": u.get("department_name") or "Unassigned"
            })

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
