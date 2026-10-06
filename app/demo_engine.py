"""Standalone In-Memory Mock Database & Service Engine for SNIST Helpdesk.

Enables the application to run completely standalone with ZERO external connections:
- No MySQL server required
- No SMS gateway or external network required
- No Metabase or SMTP required
- Fully interactive with pre-seeded users, categories, locations, tickets, and audit trails.
"""
from __future__ import annotations

import os
import re
import copy
import json
import logging
from pathlib import Path
from datetime import datetime
from werkzeug.security import generate_password_hash

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DEMO_STATE_PATH = BASE_DIR / "demo_state.json"


class MockDbState:
    def __init__(self, enable_persistence: bool = True):
        self.enable_persistence = enable_persistence
        self.tables = {}
        self.next_ids = {}
        self.reset()

    def reset(self):
        self.tables = {
            "helpdesk_users": [],
            "helpdesk_categories": [],
            "helpdesk_tickets": [],
            "helpdesk_ticket_activity": [],
            "helpdesk_ticket_notes": [],
            "helpdesk_ca_assignments": [],
            "helpdesk_staff_roles": [],
            "helpdesk_problem_types": [],
            "helpdesk_audit_events": [],
            "helpdesk_login_attempts": [],
            "helpdesk_attachments": [],
            "branch_detail": [],
            "teacher_info": [],
            "location": [],
        }
        self.next_ids = {k: 1 for k in self.tables.keys()}
        self.seed_defaults()

    def seed_defaults(self):
        # 1. Seed departments (branch_detail) - Base 6 departments for test assertions
        depts = [
            {"BRANCH_ID": 1, "BRANCH_CODE": "CSE", "department_code": "CSE", "BRANCH_NAME": "Computer Science", "department_name": "Computer Science", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": 3},
            {"BRANCH_ID": 2, "BRANCH_CODE": "ECE", "department_code": "ECE", "BRANCH_NAME": "Electronics", "department_name": "Electronics", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 3, "BRANCH_CODE": "Facilities", "department_code": "Facilities", "BRANCH_NAME": "Facilities & Estates", "department_name": "Facilities & Estates", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 4, "BRANCH_CODE": "Maintenance", "department_code": "Maintenance", "BRANCH_NAME": "Maintenance", "department_name": "Maintenance", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 5, "BRANCH_CODE": "Administration", "department_code": "Administration", "BRANCH_NAME": "Administration", "department_name": "Administration", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 6, "BRANCH_CODE": "CSE_SNU", "department_code": "CSE_SNU", "BRANCH_NAME": "CSE SNU", "department_name": "CSE SNU", "ORG_ID": "3000", "org_id": "3000", "is_archived": 0, "HOD_ID": None},
        ]
        self.tables["branch_detail"] = depts
        self.next_ids["branch_detail"] = 7

        # 2. Seed default users (Both test suite IDs 1-8 and institutional demo users)
        pwd_hash = generate_password_hash("123")
        users = [
            # Standard test & demo users
            {"id": 1, "name": "Super Admin", "email": "admin@gmail.com", "password": pwd_hash, "role": "SUPER_ADMIN", "department": "Administration", "phone": "9876543210", "org_id": "2000"},
            {"id": 2, "name": "Campus Admin", "email": "campus.admin@gmail.com", "password": pwd_hash, "role": "ADMIN", "department": "Administration", "phone": "9876543210", "org_id": "2000"},
            {"id": 3, "name": "Dr. Kavya", "email": "hod@gmail.com", "password": pwd_hash, "role": "HOD", "department": "CSE", "phone": "9876543210", "org_id": "2000"},
            {"id": 4, "name": "Chandini CA", "email": "ca@gmail.com", "password": pwd_hash, "role": "CA", "department": "CSE", "phone": "9876543210", "org_id": "2000"},
            {"id": 5, "name": "Sravan CA", "email": "sravan.ca@gmail.com", "password": pwd_hash, "role": "CA", "department": "Facilities", "phone": "9876543210", "org_id": "2000"},
            {"id": 6, "name": "Bhaskar CA", "email": "bhaskar.ca@gmail.com", "password": pwd_hash, "role": "CA", "department": "Maintenance", "phone": "9876543210", "org_id": "2000"},
            {"id": 7, "name": "Demo Faculty", "email": "faculty@gmail.com", "password": pwd_hash, "role": "FACULTY", "department": "CSE", "phone": "9876543210", "org_id": "2000"},
            {"id": 8, "name": "SNU Admin", "email": "snu.admin@gmail.com", "password": pwd_hash, "role": "SUPER_ADMIN", "department": "Administration", "phone": "9876543210", "org_id": "3000"},
            # Institutional demo accounts from DEMO_CREDENTIALS.md
            {"id": 20, "name": "ICT Manager", "email": "managerict@sreenidhi.edu.in", "password": pwd_hash, "role": "CA", "department": "ICT", "phone": "9876543220", "org_id": "2000"},
            {"id": 21, "name": "Facilities Manager", "email": "managerfs@sreenidhi.edu.in", "password": pwd_hash, "role": "CA", "department": "Facilities", "phone": "9876543221", "org_id": "2000"},
            {"id": 22, "name": "Dr. Kakarla Shirisha", "email": "shirisha.k@sreenidhi.edu.in", "password": pwd_hash, "role": "HOD", "department": "CSE", "phone": "9876543222", "org_id": "2000"},
            {"id": 23, "name": "Varanasi Aruna", "email": "aruna.v@sreenidhi.edu.in", "password": pwd_hash, "role": "FACULTY", "department": "CSE", "phone": "9876543223", "org_id": "2000"},
            {"id": 24, "name": "Kandula Damodhar Rao", "email": "damodhar.k@sreenidhi.edu.in", "password": pwd_hash, "role": "FACULTY", "department": "CSE", "phone": "9876543224", "org_id": "2000"},
            {"id": 25, "name": "CTO Admin", "email": "cto@sreenidhi.edu.in", "password": pwd_hash, "role": "SUPER_ADMIN", "department": "CTO", "phone": "9876543225", "org_id": "2000"},
            {"id": 26, "name": "HCM Executive", "email": "ramkumar.b@sreenidhi.edu.in", "password": pwd_hash, "role": "CA", "department": "Administration", "phone": "9876543226", "org_id": "2000"},
            {"id": 27, "name": "MM Executive", "email": "chakradhar.n@sreenidhi.edu.in", "password": pwd_hash, "role": "CA", "department": "Administration", "phone": "9876543227", "org_id": "2000"},
            {"id": 28, "name": "Dr. Bhutada Sunil", "email": "sunil.b@sreenidhi.edu.in", "password": pwd_hash, "role": "HOD", "department": "IT", "phone": "9876543228", "org_id": "2000"},
            {"id": 2823, "name": "Dr. Chukkaluru Ravi shankar Reddy", "email": "ravishankar.c@sreenidhi.edu.in", "password": pwd_hash, "role": "CA", "department": "ECE", "phone": "9876543299", "org_id": "2000", "is_active": 1},
        ]
        self.tables["helpdesk_users"] = users
        self.next_ids["helpdesk_users"] = 2824

        # Seed staff roles for fast lookup
        staff_roles = []
        for u in users:
            staff_roles.append({
                "id": u["id"],
                "teacher_id": u["id"],
                "name": u["name"],
                "email": u["email"],
                "password_hash": u["password"],
                "role": u["role"],
                "department": u["department"],
                "phone": u.get("phone", ""),
                "is_active": 1,
                "org_id": u.get("org_id", "2000")
            })
        self.tables["helpdesk_staff_roles"] = staff_roles
        self.next_ids["helpdesk_staff_roles"] = 2824

        # 3. Seed default categories (Keep 1-4 strictly identical to test suite)
        categories = [
            {"id": 1, "category_name": "Internet", "department": "CSE", "assigned_ca_id": 4, "is_active": 1, "org_id": "2000"},
            {"id": 2, "category_name": "Projector", "department": "CSE", "assigned_ca_id": 4, "is_active": 1, "org_id": "2000"},
            {"id": 3, "category_name": "Plumbing", "department": "Facilities", "assigned_ca_id": 5, "is_active": 1, "org_id": "2000"},
            {"id": 4, "category_name": "Electrical", "department": "Maintenance", "assigned_ca_id": 6, "is_active": 1, "org_id": "2000"},
            {"id": 5, "category_name": "Lab Equipment", "department": "ECE", "assigned_ca_id": 2823, "is_active": 1, "org_id": "2000"},
        ]
        self.tables["helpdesk_categories"] = categories
        self.next_ids["helpdesk_categories"] = 6

        # 4. Seed location table
        locations = [
            {"id": 1, "block": "Block A", "floor": "1st Floor", "room_no": "101", "name": "CSE Lab 1", "org_id": "2000"},
            {"id": 2, "block": "Block A", "floor": "1st Floor", "room_no": "102", "name": "Classroom 102", "org_id": "2000"},
            {"id": 3, "block": "SNU Block 1", "floor": "Ground Floor", "room_no": "001", "name": "Office", "org_id": "3000"},
        ]
        self.tables["location"] = locations
        self.next_ids["location"] = 4

        # 5. Seed teacher_info for institutional identity
        teachers = [
            {"TEACHER_ID": 10, "id": 10, "sap_id": "10001", "SAP_ID": "10001", "name": "Seeded Teacher", "TEACHER_NAME": "Seeded Teacher", "EMAIL_ID": "seeded@sreenidhi.edu.in", "email_id": "seeded@sreenidhi.edu.in", "MOBILE_PHONE": "9876543210", "ACTIVE": 1, "BRANCH_CODE": "CSE", "BRANCH_ID": 1, "ORG_ID": "2000", "org_id": "2000", "department": "CSE", "TEACHER_CODE": "TC001", "DESIGNATION": "Asst Prof"},
            {"TEACHER_ID": 11, "id": 11, "sap_id": "20001", "SAP_ID": "20001", "name": "SNU Teacher", "TEACHER_NAME": "SNU Teacher", "EMAIL_ID": "snuteacher@snu.edu.in", "email_id": "snuteacher@snu.edu.in", "MOBILE_PHONE": "9876543210", "ACTIVE": 1, "BRANCH_CODE": "CSE_SNU", "BRANCH_ID": 6, "ORG_ID": "3000", "org_id": "3000", "department": "CSE_SNU", "TEACHER_CODE": "TC002", "DESIGNATION": "Asst Prof"},
            {"TEACHER_ID": 12, "id": 12, "sap_id": "10002", "SAP_ID": "10002", "name": "Dr. Ramesh HOD", "TEACHER_NAME": "Dr. Ramesh HOD", "EMAIL_ID": "hod.ece@sreenidhi.edu.in", "email_id": "hod.ece@sreenidhi.edu.in", "MOBILE_PHONE": "9876543211", "ACTIVE": 1, "BRANCH_CODE": "ECE", "BRANCH_ID": 2, "ORG_ID": "2000", "org_id": "2000", "department": "ECE", "TEACHER_CODE": "TC003", "DESIGNATION": "Professor & HOD"},
            {"TEACHER_ID": 13, "id": 13, "sap_id": "10003", "SAP_ID": "10003", "name": "Suresh Faculty ECE", "TEACHER_NAME": "Suresh Faculty ECE", "EMAIL_ID": "faculty.ece@sreenidhi.edu.in", "email_id": "faculty.ece@sreenidhi.edu.in", "MOBILE_PHONE": "9876543212", "ACTIVE": 1, "BRANCH_CODE": "ECE", "BRANCH_ID": 2, "ORG_ID": "2000", "org_id": "2000", "department": "ECE", "TEACHER_CODE": "TC004", "DESIGNATION": "Assistant Professor"},
            {"TEACHER_ID": 14, "id": 14, "sap_id": "10004", "SAP_ID": "10004", "name": "Priya CA CSE", "TEACHER_NAME": "Priya CA CSE", "EMAIL_ID": "priya.ca@sreenidhi.edu.in", "email_id": "priya.ca@sreenidhi.edu.in", "MOBILE_PHONE": "9876543213", "ACTIVE": 1, "BRANCH_CODE": "CSE", "BRANCH_ID": 1, "ORG_ID": "2000", "org_id": "2000", "department": "CSE", "TEACHER_CODE": "TC005", "DESIGNATION": "Assistant Professor"},
            # Key institutional demo faculty & HOD
            {"TEACHER_ID": 22, "id": 22, "sap_id": "10000108", "SAP_ID": "10000108", "name": "Dr. Kakarla Shirisha", "TEACHER_NAME": "Dr. Kakarla Shirisha", "EMAIL_ID": "shirisha.k@sreenidhi.edu.in", "email_id": "shirisha.k@sreenidhi.edu.in", "MOBILE_PHONE": "9876543222", "ACTIVE": 1, "BRANCH_CODE": "CSE", "BRANCH_ID": 1, "ORG_ID": "2000", "org_id": "2000", "department": "CSE", "TEACHER_CODE": "TC108", "DESIGNATION": "Professor & HOD"},
            {"TEACHER_ID": 23, "id": 23, "sap_id": "10000084", "SAP_ID": "10000084", "name": "Varanasi Aruna", "TEACHER_NAME": "Varanasi Aruna", "EMAIL_ID": "aruna.v@sreenidhi.edu.in", "email_id": "aruna.v@sreenidhi.edu.in", "MOBILE_PHONE": "9876543223", "ACTIVE": 1, "BRANCH_CODE": "CSE", "BRANCH_ID": 1, "ORG_ID": "2000", "org_id": "2000", "department": "CSE", "TEACHER_CODE": "TC084", "DESIGNATION": "Assistant Professor"},
            {"TEACHER_ID": 24, "id": 24, "sap_id": "10000058", "SAP_ID": "10000058", "name": "Kandula Damodhar Rao", "TEACHER_NAME": "Kandula Damodhar Rao", "EMAIL_ID": "damodhar.k@sreenidhi.edu.in", "email_id": "damodhar.k@sreenidhi.edu.in", "MOBILE_PHONE": "9876543224", "ACTIVE": 1, "BRANCH_CODE": "CSE", "BRANCH_ID": 1, "ORG_ID": "2000", "org_id": "2000", "department": "CSE", "TEACHER_CODE": "TC058", "DESIGNATION": "Assistant Professor"},
            {"TEACHER_ID": 28, "id": 28, "sap_id": "10000072", "SAP_ID": "10000072", "name": "Dr. Bhutada Sunil", "TEACHER_NAME": "Dr. Bhutada Sunil", "EMAIL_ID": "sunil.b@sreenidhi.edu.in", "email_id": "sunil.b@sreenidhi.edu.in", "MOBILE_PHONE": "9876543228", "ACTIVE": 1, "BRANCH_CODE": "IT", "BRANCH_ID": 8, "ORG_ID": "2000", "org_id": "2000", "department": "IT", "TEACHER_CODE": "TC072", "DESIGNATION": "Professor & HOD"},
            {"TEACHER_ID": 2823, "id": 2823, "sap_id": "10002823", "SAP_ID": "10002823", "name": "Dr. Chukkaluru Ravi shankar Reddy", "TEACHER_NAME": "Dr. Chukkaluru Ravi shankar Reddy", "EMAIL_ID": "ravishankar.c@sreenidhi.edu.in", "email_id": "ravishankar.c@sreenidhi.edu.in", "MOBILE_PHONE": "9876543299", "ACTIVE": 1, "BRANCH_CODE": "ECE", "BRANCH_ID": 3, "ORG_ID": "2000", "org_id": "2000", "department": "ECE", "TEACHER_CODE": "TC2823", "DESIGNATION": "Associate Professor"},
        ]
        self.tables["teacher_info"] = teachers
        self.next_ids["teacher_info"] = 2824

        # 6. Seed CA Assignments
        ca_assignments = [
            {"id": 1, "category_id": 1, "ca_id": 4, "block": "Block A", "org_id": "2000"},
            {"id": 2, "category_id": 1, "ca_id": 14, "block": "Block A", "org_id": "2000"},
            {"id": 3, "category_id": 5, "ca_id": 2823, "block": "All Blocks", "org_id": "2000"},
        ]
        self.tables["helpdesk_ca_assignments"] = ca_assignments
        self.next_ids["helpdesk_ca_assignments"] = 4

        # 7. Seed problem types
        problem_types = [
            {"id": 1, "category_id": 1, "problem_name": "WiFi Down", "is_active": 1, "org_id": "2000"},
            {"id": 2, "category_id": 1, "problem_name": "Slow Speed", "is_active": 1, "org_id": "2000"},
            {"id": 3, "category_id": 2, "problem_name": "Projector HDMI Cable Fault", "is_active": 1, "org_id": "2000"},
            {"id": 4, "category_id": 3, "problem_name": "Water Leakage", "is_active": 1, "org_id": "2000"},
            {"id": 5, "category_id": 4, "problem_name": "Power Socket / Fan Failure", "is_active": 1, "org_id": "2000"},
        ]
        self.tables["helpdesk_problem_types"] = problem_types
        self.next_ids["helpdesk_problem_types"] = 6

        # 8. Start with empty tickets on reset() for test compatibility
        self.tables["helpdesk_tickets"] = []
        self.next_ids["helpdesk_tickets"] = 1
        self.tables["helpdesk_ticket_activity"] = []
        self.next_ids["helpdesk_ticket_activity"] = 1
        self.tables["helpdesk_ticket_notes"] = []
        self.next_ids["helpdesk_ticket_notes"] = 1

        # 9. Empty initial tables
        self.tables["helpdesk_login_attempts"] = []
        self.next_ids["helpdesk_login_attempts"] = 1
        self.tables["helpdesk_attachments"] = []
        self.next_ids["helpdesk_attachments"] = 1
        self.tables["helpdesk_audit_events"] = []
        self.next_ids["helpdesk_audit_events"] = 1

    def seed_demo_enrichments(self):
        """Enrich database state with institutional departments, categories, locations, and sample tickets for the interactive demo."""
        # 1. Enrich departments
        existing_dept_codes = {d["department_code"] for d in self.tables.get("branch_detail", [])}
        extra_depts = [
            {"BRANCH_ID": 7, "BRANCH_CODE": "ICT", "department_code": "ICT", "BRANCH_NAME": "Information & Communication Technology", "department_name": "Information & Communication Technology", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 8, "BRANCH_CODE": "IT", "department_code": "IT", "BRANCH_NAME": "Information Technology", "department_name": "Information Technology", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": 28},
            {"BRANCH_ID": 9, "BRANCH_CODE": "CTO", "department_code": "CTO", "BRANCH_NAME": "Technology Office", "department_name": "Technology Office", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
        ]
        for d in extra_depts:
            if d["department_code"] not in existing_dept_codes:
                self.tables["branch_detail"].append(d)
        self.next_ids["branch_detail"] = max(self.next_ids.get("branch_detail", 1), 10)

        # 2. Enrich categories
        existing_cat_ids = {c["id"] for c in self.tables.get("helpdesk_categories", [])}
        extra_categories = [
            {"id": 5, "category_name": "Internet & Wi-Fi", "department": "ICT", "assigned_ca_id": 20, "is_active": 1, "org_id": "2000"},
            {"id": 6, "category_name": "Projector & AV Equipment", "department": "ICT", "assigned_ca_id": 20, "is_active": 1, "org_id": "2000"},
            {"id": 7, "category_name": "Air Conditioning & HVAC", "department": "Facilities", "assigned_ca_id": 21, "is_active": 1, "org_id": "2000"},
        ]
        for c in extra_categories:
            if c["id"] not in existing_cat_ids:
                self.tables["helpdesk_categories"].append(c)
        self.next_ids["helpdesk_categories"] = max(self.next_ids.get("helpdesk_categories", 1), 8)

        # 3. Enrich locations
        existing_loc_ids = {l["id"] for l in self.tables.get("location", [])}
        extra_locations = [
            {"id": 4, "block": "Block-I", "floor": "Ground Floor", "room_no": "G-01", "name": "Main Seminar Hall", "org_id": "2000"},
            {"id": 5, "block": "Block-II", "floor": "2nd Floor", "room_no": "204", "name": "Lab 204", "org_id": "2000"},
            {"id": 6, "block": "Admin Block", "floor": "1st Floor", "room_no": "A-101", "name": "Principal Office", "org_id": "2000"},
            {"id": 7, "block": "Central Library", "floor": "Ground Floor", "room_no": "LIB-01", "name": "Digital Library", "org_id": "2000"},
        ]
        for loc in extra_locations:
            if loc["id"] not in existing_loc_ids:
                self.tables["location"].append(loc)
        self.next_ids["location"] = max(self.next_ids.get("location", 1), 8)

        # 4. Enrich CA assignments
        existing_ca_ids = {a["id"] for a in self.tables.get("helpdesk_ca_assignments", [])}
        extra_ca_assignments = [
            {"id": 3, "category_id": 5, "ca_id": 20, "block": "All Blocks", "org_id": "2000"},
            {"id": 4, "category_id": 6, "ca_id": 20, "block": "All Blocks", "org_id": "2000"},
            {"id": 5, "category_id": 3, "ca_id": 21, "block": "All Blocks", "org_id": "2000"},
            {"id": 6, "category_id": 4, "ca_id": 6, "block": "All Blocks", "org_id": "2000"},
            {"id": 7, "category_id": 7, "ca_id": 21, "block": "All Blocks", "org_id": "2000"},
        ]
        for a in extra_ca_assignments:
            if a["id"] not in existing_ca_ids:
                self.tables["helpdesk_ca_assignments"].append(a)
        self.next_ids["helpdesk_ca_assignments"] = max(self.next_ids.get("helpdesk_ca_assignments", 1), 8)

        # 5. Enrich problem types
        existing_prob_ids = {p["id"] for p in self.tables.get("helpdesk_problem_types", [])}
        extra_prob_types = [
            {"id": 6, "category_id": 7, "problem_name": "AC Not Cooling", "is_active": 1, "org_id": "2000"},
        ]
        for p in extra_prob_types:
            if p["id"] not in existing_prob_ids:
                self.tables["helpdesk_problem_types"].append(p)
        self.next_ids["helpdesk_problem_types"] = max(self.next_ids.get("helpdesk_problem_types", 1), 7)

        # 6. Seed sample tickets
        self.seed_sample_tickets()

    def seed_sample_tickets(self):
        """Seed realistic sample tickets, notes, and activity for the interactive demo."""
        if len(self.tables.get("helpdesk_tickets", [])) > 0:
            return

        sample_tickets = [
            {
                "id": 1,
                "title": "Lab Switch Port Failure in Room 204",
                "description": "Switch port 12 is flickering and dropping packets intermittently during student practical exams.",
                "category_id": 5,  # Internet & Wi-Fi (ICT)
                "created_by": 23,  # Aruna Varanasi
                "assigned_to": 20,  # ICT Manager
                "status": "PENDING",
                "org_id": "2000",
                "location_id": 5,
                "problem_type_id": 1,
                "created_at": "2026-10-02 09:15:00",
                "updated_at": "2026-10-02 09:15:00",
            },
            {
                "id": 2,
                "title": "Ceiling Fan Regulator Broken in Room 102",
                "description": "Fan knob is jammed at high speed with buzzing electrical sound.",
                "category_id": 4,  # Electrical (Maintenance)
                "created_by": 7,   # Demo Faculty
                "assigned_to": 6,   # Bhaskar CA
                "status": "IN_PROGRESS",
                "org_id": "2000",
                "location_id": 2,
                "problem_type_id": 5,
                "created_at": "2026-10-01 11:30:00",
                "updated_at": "2026-10-02 10:00:00",
            },
            {
                "id": 3,
                "title": "Projector Display Flickering in Seminar Hall",
                "description": "HDMI signal disconnects every few minutes during presentations.",
                "category_id": 2,  # Projector (CSE)
                "created_by": 24,  # Damodhar Rao
                "assigned_to": 4,   # Chandini CA
                "status": "RESOLVED",
                "org_id": "2000",
                "location_id": 4,
                "problem_type_id": 3,
                "created_at": "2026-09-30 14:00:00",
                "updated_at": "2026-10-01 16:45:00",
            },
            {
                "id": 4,
                "title": "Water Leakage in 2nd Floor Restroom",
                "description": "Drain pipe under sink is leaking steadily, creating a wet hazard.",
                "category_id": 3,  # Plumbing (Facilities)
                "created_by": 23,  # Aruna Varanasi
                "assigned_to": 21,  # Facilities Manager
                "status": "ON_HOLD",
                "org_id": "2000",
                "location_id": 5,
                "problem_type_id": 4,
                "created_at": "2026-10-01 08:30:00",
                "updated_at": "2026-10-01 12:00:00",
            },
            {
                "id": 5,
                "title": "WiFi Signal Weak in Central Library",
                "description": "Signal drops completely near the journal reading section.",
                "category_id": 1,  # Internet (CSE)
                "created_by": 7,   # Demo Faculty
                "assigned_to": 4,   # Chandini CA
                "status": "REOPENED",
                "org_id": "2000",
                "location_id": 7,
                "problem_type_id": 2,
                "created_at": "2026-09-28 10:00:00",
                "updated_at": "2026-10-02 08:30:00",
            },
            {
                "id": 6,
                "title": "AC Cooling Insufficient in Server Room",
                "description": "Temperature gauge reading 27C, dual units need compressor check.",
                "category_id": 7,  # AC (Facilities)
                "created_by": 24,  # Damodhar Rao
                "assigned_to": 21,  # Facilities Manager
                "status": "IN_PROGRESS",
                "org_id": "2000",
                "location_id": 5,
                "problem_type_id": 6,
                "created_at": "2026-10-02 07:45:00",
                "updated_at": "2026-10-02 08:15:00",
            },
        ]
        self.tables["helpdesk_tickets"] = sample_tickets
        self.next_ids["helpdesk_tickets"] = 7

        self.tables["helpdesk_ticket_activity"] = [
            {
                "id": 1,
                "ticket_id": 2,
                "action_by": 6,
                "from_status": "PENDING",
                "to_status": "IN_PROGRESS",
                "remarks": "Assigned technician with replacement 5-step regulator switch.",
                "time_taken": "15 mins",
                "attachment_path": "",
                "created_at": "2026-10-02 10:00:00",
            },
            {
                "id": 2,
                "ticket_id": 3,
                "action_by": 20,
                "from_status": "PENDING",
                "to_status": "IN_PROGRESS",
                "remarks": "Investigating signal degradation.",
                "time_taken": "20 mins",
                "attachment_path": "",
                "created_at": "2026-09-30 15:00:00",
            },
            {
                "id": 3,
                "ticket_id": 3,
                "action_by": 20,
                "from_status": "IN_PROGRESS",
                "to_status": "RESOLVED",
                "remarks": "Replaced faulty 10m high-speed HDMI cable and tested for 30 minutes at 1080p.",
                "time_taken": "45 mins",
                "attachment_path": "",
                "created_at": "2026-10-01 16:45:00",
            },
            {
                "id": 4,
                "ticket_id": 4,
                "action_by": 21,
                "from_status": "PENDING",
                "to_status": "ON_HOLD",
                "remarks": "Awaiting procurement of 2-inch PVC junction elbow from store.",
                "time_taken": "30 mins",
                "attachment_path": "",
                "created_at": "2026-10-01 12:00:00",
            },
        ]
        self.next_ids["helpdesk_ticket_activity"] = 5

        self.tables["helpdesk_ticket_notes"] = [
            {
                "id": 1,
                "ticket_id": 2,
                "user_id": 6,
                "note": "Replaced fuse, mounting bracket inspected and secure.",
                "created_at": "2026-10-02 10:15:00",
            },
            {
                "id": 2,
                "ticket_id": 3,
                "user_id": 20,
                "note": "Verified with presenter, audio and video pass cleanly.",
                "created_at": "2026-10-01 16:30:00",
            },
        ]
        self.next_ids["helpdesk_ticket_notes"] = 3

    def save_to_file(self, filepath: Path = DEMO_STATE_PATH):
        if not self.enable_persistence:
            return
        try:
            data = {
                "tables": self.tables,
                "next_ids": self.next_ids,
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            log.debug("Demo state saved to %s", filepath)
        except Exception as exc:
            log.warning("Could not persist demo state: %s", exc)

    def load_from_file(self, filepath: Path = DEMO_STATE_PATH) -> bool:
        if not self.enable_persistence or not filepath.exists():
            return False
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "tables" in data and "next_ids" in data:
                self.tables = data["tables"]
                self.next_ids = data["next_ids"]
                log.info("Loaded persisted demo state from %s", filepath)
                return True
        except Exception as exc:
            log.warning("Failed to load demo state from %s: %s", filepath, exc)
        return False


GLOBAL_DB_STATE = MockDbState(enable_persistence=True)


class MockCursor:
    def __init__(self, state: MockDbState):
        self.state = state
        self.lastrowid = None
        self.rowcount = 0
        self._results = []
        self._index = 0
        self.description = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def __iter__(self):
        return iter(self.fetchall())

    def executemany(self, sql, seq_of_params):
        count = 0
        for params in seq_of_params:
            self.execute(sql, params)
            count += self.rowcount
        self.rowcount = count

    def execute(self, sql, params=None):
        params = params or ()
        sql_norm = " ".join(sql.split()).strip()
        sql_lower_stripped = sql_norm.lower()

        self._results = []
        self._index = 0
        self.rowcount = 0

        def split_top_level(text, delimiter):
            parts = []
            depth = 0
            del_str = f" {delimiter} "
            del_len = len(del_str)
            start = 0
            i = 0
            while i < len(text):
                ch = text[i]
                if ch == '(':
                    depth += 1
                elif ch == ')':
                    depth = max(0, depth - 1)
                elif depth == 0 and text[i:i+del_len] == del_str:
                    parts.append(text[start:i].strip())
                    start = i + del_len
                    i = start - 1
                i += 1
            parts.append(text[start:].strip())
            return [p for p in parts if p]

        def get_row_val(row, col):
            c = col.lower().strip()
            v = row.get(c)
            if v is None:
                v = row.get(c.upper())
            if v is None:
                if c == "sap_id": v = row.get("SAP_ID")
                elif c == "email_id": v = row.get("EMAIL_ID")
                elif c in ("branch_code", "department_code"): v = row.get("department") or row.get("BRANCH_CODE")
                elif c == "teacher_name": v = row.get("name") or row.get("TEACHER_NAME")
                elif c == "mobile_phone": v = row.get("phone") or row.get("MOBILE_PHONE")
                elif c == "is_active": v = row.get("is_active", 1)
                elif c == "teacher_id": v = row.get("teacher_id") or row.get("id")
            return v

        def eval_atomic(row, expr, expr_params):
            expr = expr.strip()
            while expr.startswith("(") and expr.endswith(")"):
                d = 0
                balanced = True
                for ch in expr[:-1]:
                    if ch == '(': d += 1
                    elif ch == ')': d -= 1
                    if d == 0:
                        balanced = False
                        break
                if balanced:
                    expr = expr[1:-1].strip()
                else:
                    break

            if not expr or expr == "1=1":
                return True
            if expr == "1=0":
                return False

            or_parts = split_top_level(expr, "or")
            if len(or_parts) > 1:
                curr_p = 0
                for op in or_parts:
                    p_count = op.count("%s")
                    sub_p = expr_params[curr_p : curr_p + p_count]
                    curr_p += p_count
                    if eval_atomic(row, op, sub_p):
                        return True
                return False

            ignored_words = {
                "lower", "upper", "coalesce", "cast", "as", "char", "find_in_set", "date",
                "not", "in", "like", "is", "null", "select", "from", "where", "trim"
            }
            words = re.findall(r"\b[\w_.]+\b", expr)
            target_col = None
            for w in words:
                base = w.split(".")[-1].lower()
                if base not in ignored_words and not base.isdigit():
                    target_col = base
                    break

            row_val = get_row_val(row, target_col) if target_col else None
            row_str = "" if row_val is None else str(row_val).strip()

            if " in (" in expr or " in(" in expr:
                if expr_params:
                    allowed = {str(p).strip().lower() for p in expr_params}
                    return row_str.lower() in allowed
                in_match = re.search(r"in\s*\((.*?)\)", expr, re.IGNORECASE)
                if in_match:
                    literals = {
                        item.strip().strip("'\"").lower()
                        for item in in_match.group(1).split(",")
                    }
                    return row_str.lower() in literals
                return False

            if " like " in expr:
                pattern = str(expr_params[0]).strip("%").lower() if expr_params else ""
                if not pattern:
                    return True
                return pattern in row_str.lower()

            if "!=" in expr or "<>" in expr:
                if expr_params:
                    return row_str.lower() != str(expr_params[0]).strip().lower()
                lit = expr.split("!=")[-1].split("<>")[-1].strip().strip("'\"")
                return row_str.lower() != lit.lower()

            if "=" in expr:
                if expr_params:
                    target_v = str(expr_params[0]).strip().lower()
                    if target_col == "org_id" and ("org_id is null" in expr or "org_id = ''" in expr):
                        if row_val is None or row_str == "" or row_str.lower() == target_v:
                            return True
                    return row_str.lower() == target_v
                lit = expr.split("=")[-1].strip().strip("'\"")
                if target_col == "is_archived" and row_val is None:
                    row_str = "0"
                return row_str.lower() == lit.lower()

            if "is null" in expr:
                return row_val is None or row_str == ""
            if "is not null" in expr:
                return row_val is not None and row_str != ""

            return True

        def match_row(row, where_clause_lower, where_params):
            where_params = list(where_params)
            for keyw in ["order by", "group by", "limit", "offset"]:
                if keyw in where_clause_lower:
                    where_clause_lower = where_clause_lower[:where_clause_lower.index(keyw)].strip()

            for sub_target in [
                "c.department in (select branch_code from branch_detail where cast(org_id as char) = %s)",
                "u.department in (select branch_code from branch_detail where cast(org_id as char) = %s)",
            ]:
                if sub_target in where_clause_lower:
                    sub_pos = where_clause_lower.index(sub_target)
                    param_idx = where_clause_lower[:sub_pos].count("%s")
                    if param_idx < len(where_params):
                        target_org = str(where_params[param_idx])
                        valid_branches = {
                            b.get("BRANCH_CODE") or b.get("department_code")
                            for b in self.state.tables["branch_detail"]
                            if str(b.get("ORG_ID") or b.get("org_id")) == target_org
                        }
                        row_dept = row.get("department") or row.get("department_code") or row.get("BRANCH_CODE")
                        if row_dept not in valid_branches:
                            return False
                        where_clause_lower = where_clause_lower[:sub_pos] + where_clause_lower[sub_pos + len(sub_target):]
                        where_params = where_params[:param_idx] + where_params[param_idx+1:]

            if "is_archived" in where_clause_lower:
                if "is_archived, 0) = 0" in where_clause_lower or "is_archived = 0" in where_clause_lower:
                    is_archived_val = row.get("is_archived")
                    if is_archived_val is None:
                        is_archived_val = row.get("is_archived".upper())
                    if is_archived_val is not None and str(is_archived_val) != "0":
                        return False

            and_parts = split_top_level(where_clause_lower, "and")
            curr_param_idx = 0
            for part in and_parts:
                count_p = part.count("%s")
                part_p = where_params[curr_param_idx : curr_param_idx + count_p]
                curr_param_idx += count_p
                if not eval_atomic(row, part, part_p):
                    return False
            return True

        # Handle INSERT
        if sql_lower_stripped.startswith("insert into"):
            table_match = re.search(r"insert into\s+(\w+)", sql_lower_stripped)
            if table_match:
                table_name = table_match.group(1)
                cols_part = re.search(r"\((.*?)\)", sql_norm)
                if cols_part:
                    columns = [c.strip().strip("`") for c in cols_part.group(1).split(",")]
                    row_data = {}
                    val_part_match = re.search(r"values\s*\((.*)\)", sql_norm, re.IGNORECASE)
                    if val_part_match:
                        exprs = [e.strip() for e in val_part_match.group(1).split(",")]
                        param_idx = 0
                        for col, expr in zip(columns, exprs):
                            if expr == "%s":
                                row_data[col] = params[param_idx] if param_idx < len(params) else None
                                param_idx += 1
                            else:
                                val = expr
                                if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                                    val = val[1:-1]
                                elif val.isdigit():
                                    val = int(val)
                                row_data[col] = val
                    else:
                        for col, val in zip(columns, params):
                            row_data[col] = val

                    # Generate new ID if not present
                    if "id" not in row_data:
                        new_id = self.state.next_ids.get(table_name, 1)
                        row_data["id"] = new_id
                        self.state.next_ids[table_name] = new_id + 1
                        self.lastrowid = new_id
                    else:
                        self.lastrowid = row_data["id"]

                    if table_name == "helpdesk_categories":
                        if "is_active" not in row_data:
                            row_data["is_active"] = 1
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    if "created_at" not in row_data:
                        row_data["created_at"] = now_str
                    if "updated_at" not in row_data:
                        row_data["updated_at"] = now_str

                    self.state.tables.setdefault(table_name, []).append(row_data)
                    self.rowcount = 1
                    self.state.save_to_file()
            return

        # Handle UPDATE
        if sql_lower_stripped.startswith("update"):
            table_match = re.search(r"update\s+(\w+)", sql_lower_stripped)
            if table_match:
                table_name = table_match.group(1)

                where_clause_lower = ""
                if "where" in sql_lower_stripped:
                    where_clause_lower = sql_lower_stripped[sql_lower_stripped.index("where") + 5:].strip()

                set_part = sql_norm[sql_lower_stripped.index("set") + 3 : (sql_lower_stripped.index("where") if "where" in sql_lower_stripped else len(sql_norm))].strip()
                set_exprs = [s.strip() for s in set_part.split(",")]

                num_set_params = set_part.count("%s")
                set_vals = params[:num_set_params]
                where_vals = params[num_set_params:]

                updated_count = 0
                for row in self.state.tables.get(table_name, []):
                    if not where_clause_lower or match_row(row, where_clause_lower, where_vals):
                        param_idx = 0
                        for expr in set_exprs:
                            col_name = expr.split("=")[0].strip().strip("`")
                            val_part = expr.split("=")[1].strip() if "=" in expr else ""
                            if val_part == "%s":
                                row[col_name] = set_vals[param_idx] if param_idx < len(set_vals) else None
                                param_idx += 1
                            elif val_part.isdigit():
                                row[col_name] = int(val_part)
                            elif (val_part.startswith("'") and val_part.endswith("'")) or (val_part.startswith('"') and val_part.endswith('"')):
                                row[col_name] = val_part[1:-1]
                            else:
                                row[col_name] = set_vals[param_idx] if param_idx < len(set_vals) else None
                                param_idx += 1
                        if "updated_at" in row:
                            row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        updated_count += 1
                self.rowcount = updated_count
                if updated_count > 0:
                    self.state.save_to_file()
            return

        # Handle DELETE
        if sql_lower_stripped.startswith("delete"):
            table_match = re.search(r"from\s+(\w+)", sql_lower_stripped)
            if table_match:
                table_name = table_match.group(1)
                where_clause_lower = ""
                if "where" in sql_lower_stripped:
                    where_clause_lower = sql_lower_stripped[sql_lower_stripped.index("where") + 5:].strip()

                before_len = len(self.state.tables.get(table_name, []))
                if where_clause_lower:
                    self.state.tables[table_name] = [
                        r for r in self.state.tables.get(table_name, [])
                        if not match_row(r, where_clause_lower, params)
                    ]
                else:
                    self.state.tables[table_name] = []
                self.rowcount = before_len - len(self.state.tables.get(table_name, []))
                if self.rowcount > 0:
                    self.state.save_to_file()
            return

        # Handle SELECT queries
        if "show columns" in sql_lower_stripped:
            col_to_check = params[0] if params else ""
            is_active = ("is_active" in sql_lower_stripped) or ("is_active" in col_to_check)
            status = ("status" in sql_lower_stripped) or ("status" in col_to_check)
            problem_type_id = ("problem_type_id" in sql_lower_stripped) or ("problem_type_id" in col_to_check)
            is_archived = ("is_archived" in sql_lower_stripped) or ("is_archived" in col_to_check)
            org_id = ("org_id" in sql_lower_stripped) or ("org_id" in col_to_check.lower())

            if is_active:
                self._results = [{"Field": "is_active", "Type": "tinyint(1)"}]
            elif status:
                self._results = [{"Field": "status", "Type": "enum('PENDING','IN_PROGRESS','ON_HOLD','RESOLVED','REOPENED')"}]
            elif problem_type_id:
                self._results = [{"Field": "problem_type_id", "Type": "int(10) unsigned"}]
            elif is_archived:
                self._results = [{"Field": "is_archived", "Type": "tinyint(1)"}]
            elif org_id:
                self._results = [{"Field": "ORG_ID", "Type": "varchar(255)"}]
            self.rowcount = len(self._results)
            return

        table_name = None
        for t in sorted(self.state.tables.keys(), key=len, reverse=True):
            if f"from {t}" in sql_lower_stripped or f"from `{t}`" in sql_lower_stripped:
                table_name = t
                break

        if "show index" in sql_lower_stripped:
            self._results = [{"Key_name": "uq_activity_dedup"}]
            self.rowcount = len(self._results)
            return

        if "show tables" in sql_lower_stripped:
            col_name = "Tables_in_helpdesk (helpdesk_%)"
            if "like 'helpdesk_%'" in sql_lower_stripped or 'like "helpdesk_%"' in sql_lower_stripped:
                self._results = [{col_name: t} for t in sorted(self.state.tables.keys()) if t.startswith("helpdesk_")]
            else:
                self._results = [{col_name: t} for t in sorted(self.state.tables.keys())]
            self.rowcount = len(self._results)
            return

        if sql_lower_stripped == "select 1" or sql_lower_stripped.startswith("select 1 "):
            self._results = [{"1": 1}]
            self.rowcount = 1
            return

        rows = self.state.tables.get(table_name, []) if table_name else []
        filtered_rows = []

        if "where" in sql_lower_stripped:
            where_clause_lower = sql_lower_stripped[sql_lower_stripped.index("where") + 5:].strip()
            for row in rows:
                if match_row(row, where_clause_lower, params):
                    filtered_rows.append(row)
        else:
            filtered_rows = list(rows)

        # Handle ORDER BY, LIMIT, OFFSET if simple
        if "limit 1" in sql_lower_stripped:
            filtered_rows = filtered_rows[:1]

        # Handle GROUP BY with COUNT for multi-CA least loaded routing
        if "group by u.id" in sql_lower_stripped:
            res = []
            for cid in params:
                cnt = sum(
                    1 for t in self.state.tables.get("helpdesk_tickets", [])
                    if t.get("assigned_to") == cid and t.get("status") in ('PENDING', 'IN_PROGRESS', 'REOPENED')
                )
                res.append({"id": cid, "active_count": cnt})
            self._results = res
            self.rowcount = len(res)
            return

        # Handle helpdesk_login_attempts count
        if table_name == "helpdesk_login_attempts" and "count(" in sql_lower_stripped:
            identifier_val = str(params[0]).lower() if len(params) > 0 else ""
            is_ip = "ip_address =" in sql_lower_stripped
            cnt = 0
            for r in self.state.tables.get("helpdesk_login_attempts", []):
                if str(r.get("outcome", "")).upper() != "FAILURE":
                    continue
                if is_ip:
                    if str(r.get("ip_address", "")) == identifier_val:
                        cnt += 1
                else:
                    if str(r.get("identifier", "")).lower() == identifier_val:
                        cnt += 1
            self._results = [{"total": cnt, "count": cnt, "cnt": cnt}]
            self.rowcount = 1
            return

        # Handle SELECT COUNT(*)
        if "count(" in sql_lower_stripped:
            self._results = [{"total": len(filtered_rows), "count": len(filtered_rows), "cnt": len(filtered_rows)}]
            self.rowcount = 1
            return

        # Simple SELECT alias and projection parsing
        select_cols = []
        select_part = "*"
        if sql_lower_stripped.startswith("select "):
            from_match = re.search(r"\bfrom\b", sql_lower_stripped)
            from_idx = from_match.start() if from_match else -1
            if from_idx != -1:
                select_part = sql_lower_stripped[7:from_idx].strip()
                if select_part.lower().startswith("distinct "):
                    select_part = select_part[9:].strip()
                parts = []
                curr = []
                paren_depth = 0
                for ch in select_part:
                    if ch == '(':
                        paren_depth += 1
                    elif ch == ')':
                        paren_depth -= 1
                    if ch == ',' and paren_depth == 0:
                        parts.append(''.join(curr).strip())
                        curr = []
                    else:
                        curr.append(ch)
                if curr:
                    parts.append(''.join(curr).strip())
                for p in parts:
                    p = p.strip()
                    as_match = re.search(r'\s+as\s+(\w+)\s*$', p, re.IGNORECASE)
                    if as_match:
                        alias = as_match.group(1).strip()
                        expr = p[:as_match.start()].strip()
                        select_cols.append((expr, alias))
                    else:
                        name = p.split(".")[-1].strip().strip("`")
                        select_cols.append((p, name))

        # Return copies of dicts to isolate state mutations
        results_copies = []
        for row in filtered_rows:
            new_row = {}
            if select_cols and "*" not in select_part:
                for expr, alias in select_cols:
                    if (expr.startswith("'") and expr.endswith("'")) or (expr.startswith('"') and expr.endswith('"')):
                        val = expr[1:-1]
                    else:
                        words = re.findall(r"\b[a-zA-Z_0-9]+\b", expr)
                        val = None
                        for w in words:
                            if w.lower() == "coalesce":
                                continue
                            for k, v in row.items():
                                if k.lower() == w.lower():
                                    val = v
                                    break
                            if val is not None:
                                break
                        if val is None and "coalesce(" in expr.lower():
                            c_match = re.search(r"coalesce\s*\([^,]+,\s*([^)]+)\)", expr, re.IGNORECASE)
                            if c_match:
                                fb = c_match.group(1).strip().strip("'\"")
                                val = int(fb) if fb.isdigit() else fb
                    new_row[alias] = val
            else:
                new_row = copy.deepcopy(row)

            # Map both lowercase and uppercase keys for test and app compatibility
            for k, v in list(new_row.items()):
                new_row[k.lower()] = v
                new_row[k.upper()] = v
            results_copies.append(new_row)

        for r in results_copies:
            for k in ["created_at", "updated_at"]:
                if k in r or (table_name and table_name in ["helpdesk_tickets", "helpdesk_ticket_history"]):
                    val = r.get(k)
                    if not val:
                        r[k] = datetime(2026, 7, 7, 12, 0, 0)
                    elif isinstance(val, str):
                        try:
                            r[k] = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            r[k] = datetime(2026, 7, 7, 12, 0, 0)

        for r in results_copies:
            if table_name == "helpdesk_tickets":
                creator = next((u for u in self.state.tables["helpdesk_users"] if u["id"] == r.get("created_by")), None)
                assignee = next((u for u in self.state.tables["helpdesk_users"] if u["id"] == r.get("assigned_to")), None)
                cat = next((c for c in self.state.tables["helpdesk_categories"] if c["id"] == r.get("category_id")), None)
                loc_room = next((rm for rm in self.state.tables["location"] if rm["id"] == r.get("location_id")), None)
                prob_type = next((p for p in self.state.tables["helpdesk_problem_types"] if p["id"] == r.get("problem_type_id")), None)

                r["created_by_name"] = creator["name"] if creator else "Unknown Faculty"
                r["created_by_email"] = creator["email"] if creator else ""
                r["created_by_phone"] = creator.get("phone", "") if creator else ""
                r["assigned_to_name"] = assignee["name"] if assignee else "Unassigned CA"
                r["assigned_to_email"] = assignee["email"] if assignee else ""
                r["assigned_to_phone"] = assignee.get("phone", "") if assignee else ""
                r["category_name"] = cat["category_name"] if cat else "Uncategorized"
                r["department"] = cat["department"] if cat else "General"
                r["room_no"] = loc_room["room_no"] if loc_room else ""
                r["block_name"] = loc_room["block"] if loc_room else ""
                r["location_block"] = loc_room["block"] if loc_room else ""
                r["location_floor"] = loc_room.get("floor", "") if loc_room else ""
                r["location_room_no"] = loc_room.get("room_no", "") if loc_room else ""
                r["location_room_name"] = loc_room.get("name", "") if loc_room else ""
                r["problem_name"] = prob_type["problem_name"] if prob_type else ""

            elif table_name == "helpdesk_categories":
                assignee = next((u for u in self.state.tables["helpdesk_users"] if u["id"] == r.get("assigned_ca_id")), None)
                r["assigned_ca_name"] = assignee["name"] if assignee else "Unassigned CA"
                r["assigned_ca_email"] = assignee["email"] if assignee else ""

            elif table_name == "helpdesk_ticket_activity":
                action_by = next((u for u in self.state.tables["helpdesk_users"] if u["id"] == r.get("action_by")), None)
                r["action_by_name"] = action_by["name"] if action_by else "System"

            elif table_name == "helpdesk_ticket_notes":
                author = next((u for u in self.state.tables["helpdesk_users"] if u["id"] == r.get("user_id")), None)
                r["author_name"] = author["name"] if author else "Assignee"
                r["author_email"] = author["email"] if author else ""

        self._results = results_copies
        self.rowcount = len(self._results)

    def fetchone(self):
        if self._index < len(self._results):
            row = self._results[self._index]
            self._index += 1
            return row
        return None

    def fetchall(self):
        res = self._results[self._index:]
        self._index = len(self._results)
        return res

    def fetchmany(self, size=None):
        if size is None:
            size = 1
        res = self._results[self._index : self._index + size]
        self._index += len(res)
        return res

    def close(self):
        pass


class MockConnection:
    def __init__(self, state: MockDbState):
        self.state = state
        self._in_transaction = False
        self._state_backup = None

    def autocommit(self, val):
        if not val:
            self._in_transaction = True
            self._state_backup = copy.deepcopy(self.state.tables)
        else:
            self._in_transaction = False

    def commit(self):
        self._in_transaction = False
        self._state_backup = None
        self.state.save_to_file()

    def rollback(self):
        if self._state_backup is not None:
            self.state.tables = self._state_backup
        self._in_transaction = False

    def cursor(self, *args, **kwargs):
        return MockCursor(self.state)

    def close(self):
        pass

    def ping(self, reconnect=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def activate_standalone_demo(reset: bool = False):
    """
    Activate self-contained standalone demo mode.
    Sets all environment flags to bypass external servers,
    hooks the in-memory mock engine into BaseMySQLService,
    and redirects SMS/Email dispatches to console logging.
    """
    os.environ["DEMO_MODE"] = "true"
    os.environ["OFFLINE_DEMO"] = "true"
    os.environ["FLASK_ENV"] = "development"
    if not os.environ.get("SECRET_KEY") or os.environ.get("SECRET_KEY") == "change-me-in-production":
        os.environ["SECRET_KEY"] = "snist-helpdesk-standalone-demo-key-c69fc621e477"
    os.environ["MYSQL_HOST"] = "localhost"
    os.environ["MYSQL_PORT"] = "3306"
    os.environ["MYSQL_USER"] = "demo"
    os.environ["MYSQL_PASSWORD"] = "demo"
    os.environ["MYSQL_DATABASE"] = "helpdesk"
    os.environ["INIT_DEMO_DB"] = "false"
    os.environ["SSO_ENABLED"] = "false"
    os.environ["METABASE_SITE_URL"] = ""
    os.environ["METABASE_SECRET_KEY"] = ""
    os.environ["SMS_API_KEY"] = ""
    os.environ["WHATSAPP_ENABLED"] = "false"
    os.environ["SMTP_HOST"] = ""

    if reset and DEMO_STATE_PATH.exists():
        try:
            DEMO_STATE_PATH.unlink()
        except Exception:
            pass
        GLOBAL_DB_STATE.reset()
        GLOBAL_DB_STATE.seed_demo_enrichments()
        GLOBAL_DB_STATE.save_to_file(DEMO_STATE_PATH)
    elif DEMO_STATE_PATH.exists():
        GLOBAL_DB_STATE.load_from_file(DEMO_STATE_PATH)
    else:
        GLOBAL_DB_STATE.seed_demo_enrichments()
        GLOBAL_DB_STATE.save_to_file(DEMO_STATE_PATH)

    # Monkey-patch notifications to terminal simulation
    try:
        import sms_services
        def simulated_sms(phone, message):
            print(f"\n📱 [DEMO SIMULATION] SMS to {phone}: {message}\n")
        sms_services._send_sms_sync = simulated_sms
    except Exception:
        pass

    try:
        import email_services
        def simulated_email(to_email, subject, body):
            print(f"\n📧 [DEMO SIMULATION] Email to {to_email} | Subject: '{subject}'\n")
        email_services._send_email_sync = simulated_email
    except Exception:
        pass

    log.info("Standalone Demo Engine activated successfully (Zero external connections).")
