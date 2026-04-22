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
            {"category_name": "Internet", "department": "CSE", "authority_email": "ca@gmail.com"},
            {"category_name": "Projector", "department": "CSE", "authority_email": "ca@gmail.com"},
            {"category_name": "Plumbing", "department": "Facilities", "authority_email": "bhaskar.ca@gmail.com"},
            {"category_name": "Electrical", "department": "Maintenance", "authority_email": "bhaskar.ca@gmail.com"},
        ],
    )
    print("demo schema initialized")


if __name__ == "__main__":
    main()
