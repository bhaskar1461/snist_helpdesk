import unittest
from unittest.mock import patch, MagicMock
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
import json
import jwt
from app.config import METABASE_SECRET_KEY
from app.helpers import departments_with_active_hods, active_category_departments, departments_for_impersonation

class TestPendingFixes(HelpdeskTestCase):

    def test_category_edit_modal_rendering(self):
        """Issue 1: Edit button passes only cat id and modal_departments is used."""
        self.login_as("admin@gmail.com")
        res = self.client.get("/management/category-assignments")
        self.assertEqual(res.status_code, 200)
        # Verify Edit button renders openEditModal(<id>) without broken data-blocks
        self.assertIn(b"openEditModal(1)", res.data)
        self.assertNotIn(b"data-blocks=", res.data)

    def test_hod_ticket_management_dual_id_matching(self):
        """Issue 2: get_ca_open_tickets resolves tickets assigned by staff role ID or teacher ID."""
        from app import get_demo_db
        demo_db = get_demo_db()

        # Seed staff role with id 55 and teacher_id 457
        GLOBAL_DB_STATE.tables["helpdesk_staff_roles"].append({
            "id": 55,
            "teacher_id": 457,
            "name": "Jitta Chandra Shekar Reddy",
            "email": "chandrashekarreddy.j@sreenidhi.edu.in",
            "role": "CA",
            "department": "ICT",
            "phone": "9876543210",
            "is_active": 1,
        })
        # Seed ticket assigned to 457 (teacher_id)
        GLOBAL_DB_STATE.tables["helpdesk_tickets"].append({
            "id": 888,
            "title": "Network switch failure",
            "description": "Switch offline in Block 1",
            "category_id": 1,
            "created_by": 10,
            "assigned_to": 457,
            "status": "IN_PROGRESS",
            "org_id": "2000",
            "location_id": 1,
        })

        # Calling get_ca_open_tickets with staff role id 55 should match ticket assigned to 457
        tickets = demo_db.get_ca_open_tickets(55)
        ticket_ids = [t["id"] for t in tickets]
        self.assertIn(888, ticket_ids)

    def test_user_role_update_persistence(self):
        """Issue 3: Updating user role upserts into helpdesk_staff_roles for institutional teachers."""
        from app import get_demo_db
        demo_db = get_demo_db()

        # User 10 is 'seeded@sreenidhi.edu.in' in teacher_info
        demo_db.update_user(10, {
            "name": "Seeded Teacher",
            "email": "seeded@sreenidhi.edu.in",
            "role": "HOD",
            "department": "CSE",
            "phone": "9876543210",
        })

        staff_entry = next((s for s in GLOBAL_DB_STATE.tables["helpdesk_staff_roles"] if s.get("teacher_id") == 10 or s.get("email") == "seeded@sreenidhi.edu.in"), None)
        self.assertIsNotNone(staff_entry)
        self.assertEqual(staff_entry["role"], "HOD")

    def test_sso_inactive_teacher_blocked(self):
        """Issue 4: Inactive institutional teachers (ACTIVE == 0) are blocked with access restricted flash."""
        # Set teacher 13 to inactive (ACTIVE = 0)
        teacher = next(t for t in GLOBAL_DB_STATE.tables["teacher_info"] if t["TEACHER_ID"] == 13)
        teacher["ACTIVE"] = 0
        teacher["is_active"] = 0

        # Attempt mock SSO login
        res = self.client.post("/sso/login", data={
            "email": "faculty.ece@sreenidhi.edu.in",
            "name": "Suresh Faculty ECE",
            "department": "ECE",
            "role": "FACULTY",
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Access restricted", res.data)
        self.assertIn(b"inactive in the staff directory", res.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

        # Restore ACTIVE
        teacher["ACTIVE"] = 1
        teacher["is_active"] = 1

    def test_metabase_embed_department_filtering(self):
        """Issue 5: Metabase embed endpoint encodes department in JWT parameters."""
        self.login_as("admin@gmail.com")
        with patch("app.analytics.METABASE_SITE_URL", "http://metabase:3000"), \
             patch("app.analytics.METABASE_SECRET_KEY", "test_metabase_secret_key_12345678"):
            res = self.client.get("/api/analytics/metabase-embed?dashboard=overview&department=ICT")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("embed_url", data)
            token = data["embed_url"].split("/embed/dashboard/")[1].split("#")[0]
            decoded = jwt.decode(token, "test_metabase_secret_key_12345678", algorithms=["HS256"])
            self.assertEqual(decoded["params"].get("department"), "ICT")

    def test_departments_with_active_hods(self):
        """Issue 6: departments_with_active_hods returns only departments with active HOD users."""
        from app import get_demo_db
        demo_db = get_demo_db()
        depts = departments_with_active_hods(demo_db, org_id="2000")
        dept_codes = [d["code"] for d in depts]
        # Dr. Kavya is HOD of CSE in test seed
        self.assertIn("CSE", dept_codes)

        # Super admin dashboard includes impersonation_departments
        self.login_as("admin@gmail.com")
        res = self.client.get("/super-admin/dashboard")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Department HOD Impersonation", res.data)

    def test_fallback_analytics_endpoints(self):
        """Issue 7: Fallback analytics API endpoints return populated structures."""
        self.login_as("admin@gmail.com")
        # 1. Trends
        res_trends = self.client.get("/api/analytics/trends?period=monthly")
        self.assertEqual(res_trends.status_code, 200)
        self.assertIn("trends", res_trends.get_json())

        # 2. CA Performance
        res_ca = self.client.get("/api/analytics/ca-performance")
        self.assertEqual(res_ca.status_code, 200)
        self.assertIn("ca_performance", res_ca.get_json())

        # 3. Resolution Time
        res_rt = self.client.get("/api/analytics/resolution-time")
        self.assertEqual(res_rt.status_code, 200)
        self.assertIn("resolution_time", res_rt.get_json())

    def test_departments_for_impersonation_union(self):
        """Union of departments: allow impersonating any department with active categories OR active HOD."""
        from app import get_demo_db
        demo_db = get_demo_db()
        depts = departments_for_impersonation(demo_db, org_id="2000")
        dept_codes = [d["code"] for d in depts]
        # Active category department
        self.assertIn("Facilities", dept_codes)
        # HOD department
        self.assertIn("CSE", dept_codes)

        # Login and impersonate
        self.login_as("admin@gmail.com")
        res = self.client.post("/impersonate-hod", data={"department": "Facilities"}, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("acting_role"), "HOD")
            self.assertEqual(sess.get("acting_department"), "Facilities")
            # Both Facilities and CSE should be present in available_departments
            avail = sess.get("available_departments", [])
            self.assertIn("Facilities", avail)
            self.assertIn("CSE", avail)
