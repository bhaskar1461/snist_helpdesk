import unittest
import json
from unittest.mock import patch, MagicMock
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from flask import session

class TestInstitutionalArchitecture(HelpdeskTestCase):
    """
    Test suite verifying the new database architecture:
    1. Institutional teacher_info as authoritative source of truth (zero duplicate users in helpdesk_users).
    2. Dynamic role determination (HOD, CA, FACULTY, ADMIN).
    3. Strict department-based ticket assignment (rejection of cross-department assignment).
    4. Institutional location usage.
    """

    def test_faculty_login_zero_duplication(self):
        """Faculty authenticates directly from teacher_info; NO row is created in helpdesk_users."""
        # Ensure 'seeded@sreenidhi.edu.in' is not in helpdesk_users
        GLOBAL_DB_STATE.tables["helpdesk_users"] = [
            u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] 
            if u["email"] != "seeded@sreenidhi.edu.in"
        ]
        initial_user_count = len(GLOBAL_DB_STATE.tables["helpdesk_users"])

        # Login with email and SAP_ID from teacher_info
        response = self.login_as("seeded@sreenidhi.edu.in", password="10001", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # 1. Verify session was established directly from teacher_info
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 10)
            self.assertEqual(sess.get("role"), "FACULTY")
            self.assertEqual(sess.get("department"), "CSE")
            self.assertEqual(sess.get("user_name"), "Seeded Teacher")

        # 2. Verify ZERO rows were inserted into helpdesk_users
        current_user_count = len(GLOBAL_DB_STATE.tables["helpdesk_users"])
        self.assertEqual(current_user_count, initial_user_count)
        duplicate_user = next(
            (u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] if u["email"] == "seeded@sreenidhi.edu.in"), 
            None
        )
        self.assertIsNone(duplicate_user)

    def test_hod_dynamic_role_resolution(self):
        """HOD status dynamically resolved from DESIGNATION / HOD_ID without duplicate table rows."""
        # Ensure hod.ece is not in helpdesk_users
        GLOBAL_DB_STATE.tables["helpdesk_users"] = [
            u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] 
            if u["email"] != "hod.ece@sreenidhi.edu.in"
        ]
        
        # Login with Dr. Ramesh's SAP ID
        response = self.login_as("hod.ece@sreenidhi.edu.in", password="10002", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Session role is dynamically resolved to HOD
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 12)
            self.assertEqual(sess.get("role"), "HOD")
            self.assertEqual(sess.get("department"), "ECE")
            self.assertEqual(sess.get("user_name"), "Dr. Ramesh HOD")

        # Can access HOD dashboard
        res_hod = self.client.get("/hod/dashboard")
        self.assertEqual(res_hod.status_code, 200)

    def test_ca_dynamic_role_resolution(self):
        """CA status dynamically resolved from helpdesk_ca_assignments."""
        GLOBAL_DB_STATE.tables["helpdesk_users"] = [
            u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] 
            if u["email"] != "priya.ca@sreenidhi.edu.in"
        ]

        # Login with Priya CA's SAP ID
        response = self.login_as("priya.ca@sreenidhi.edu.in", password="10004", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Session role is dynamically resolved to CA
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 14)
            self.assertEqual(sess.get("role"), "CA")
            self.assertEqual(sess.get("department"), "CSE")

        # Can access CA tickets dashboard
        res_ca = self.client.get("/authority/tickets")
        self.assertEqual(res_ca.status_code, 200)

    def test_strict_department_assignment_success(self):
        """Assigning ticket to an assignee in the SAME department succeeds."""
        from app import get_demo_db
        demo_db = get_demo_db()

        # Category 1 is 'Internet' under department 'CSE'
        ticket_id = demo_db.create_ticket(
            title="Internet Down in Lab",
            description="Network switch not responding",
            category_id=1,
            created_by=10,  # Seeded Teacher (CSE)
            org_id="2000",
            location_id=1,
            assigned_to=14, # Priya CA (CSE)
        )
        self.assertIsNotNone(ticket_id)

        ticket = demo_db.get_ticket(ticket_id)
        self.assertEqual(ticket["assigned_to"], 14)
        self.assertEqual(ticket["category_name"], "Internet")

    def test_strict_cross_department_assignment_rejection(self):
        """Assigning a CSE category ticket to an ECE faculty is strictly rejected."""
        from app import get_demo_db
        demo_db = get_demo_db()

        # Category 1 is 'Internet' under department 'CSE'
        # Teacher 13 is 'Suresh Faculty ECE' under department 'ECE'
        with self.assertRaises(ValueError) as ctx:
            demo_db.create_ticket(
                title="Cross-Department Invalid Assignment",
                description="Attempting to assign CSE ticket to ECE teacher",
                category_id=1,
                created_by=10,
                org_id="2000",
                location_id=1,
                assigned_to=13,  # ECE teacher - MUST BE REJECTED
            )
        self.assertIn("department", str(ctx.exception).lower())

    def test_assignee_api_department_isolation(self):
        """API /api/users/assignees strictly filters teachers by the category department."""
        self.login_as("admin@gmail.com")

        # Request CSE assignees
        res_cse = self.client.get("/api/users/assignees?department=CSE")
        self.assertEqual(res_cse.status_code, 200)
        data_cse = res_cse.get_json()
        cse_emails = [u["email"].lower() for u in data_cse["results"]]
        
        # Verify CSE teachers are returned, but ECE teachers are NOT
        self.assertIn("seeded@sreenidhi.edu.in", cse_emails)
        self.assertNotIn("faculty.ece@sreenidhi.edu.in", cse_emails)
        self.assertNotIn("hod.ece@sreenidhi.edu.in", cse_emails)

        # Request ECE assignees
        res_ece = self.client.get("/api/users/assignees?department=ECE")
        self.assertEqual(res_ece.status_code, 200)
        data_ece = res_ece.get_json()
        ece_emails = [u["email"].lower() for u in data_ece["results"]]
        
        # Verify ECE teachers are returned, but CSE teachers are NOT
        self.assertIn("faculty.ece@sreenidhi.edu.in", ece_emails)
        self.assertNotIn("seeded@sreenidhi.edu.in", ece_emails)
        self.assertNotIn("priya.ca@sreenidhi.edu.in", ece_emails)

    def test_institutional_location_usage(self):
        """Tickets reference locations from the institutional location table directly."""
        self.login_as("faculty@gmail.com")
        
        # Locations API returns institutional locations
        res = self.client.get("/api/locations")
        self.assertEqual(res.status_code, 200)
        locations = res.get_json()
        self.assertTrue(len(locations) > 0)
        self.assertIn("Block A", locations)

    def test_reassign_tickets_cross_department_rejection(self):
        """reassign_tickets strictly prohibits reassigning to a teacher from another department."""
        from app import get_demo_db
        demo_db = get_demo_db()

        # Create a valid CSE ticket
        ticket_id = demo_db.create_ticket(
            title="Switch Port Issue",
            description="Port 5 flickering",
            category_id=1,
            created_by=10,
            org_id="2000",
            location_id=1,
            assigned_to=4, # CSE CA
        )

        # Attempt to reassign to ECE teacher (ID 13)
        with self.assertRaises(ValueError) as ctx:
            demo_db.reassign_tickets([ticket_id], source_ca_id=4, target_ca_id=13, actor={"id": 1, "name": "Super Admin", "role": "SUPER_ADMIN"})
        self.assertIn("department", str(ctx.exception).lower())

        # Valid reassign to Priya CA (CSE, ID 14) succeeds
        result = demo_db.reassign_tickets([ticket_id], source_ca_id=4, target_ca_id=14, actor={"id": 1, "name": "Super Admin", "role": "SUPER_ADMIN"})
        self.assertEqual(result.get("reassigned_count"), 1)
        updated_ticket = demo_db.get_ticket(ticket_id)
        self.assertEqual(updated_ticket["assigned_to"], 14)

    def test_sso_mock_login_institutional_resolution(self):
        """Simulate Google SSO login with institutional email; session established directly without duplicate users."""
        GLOBAL_DB_STATE.tables["helpdesk_users"] = [
            u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] 
            if u["email"] != "seeded@sreenidhi.edu.in"
        ]
        initial_user_count = len(GLOBAL_DB_STATE.tables["helpdesk_users"])

        # Post to /sso/login (mock SSO flow)
        res = self.client.post("/sso/login", data={
            "email": "seeded@sreenidhi.edu.in",
            "name": "Seeded Teacher",
            "department": "CSE",
            "role": "FACULTY"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # 1. Verify session was established directly from teacher_info
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 10)
            self.assertEqual(sess.get("role"), "FACULTY")
            self.assertEqual(sess.get("department"), "CSE")
            self.assertEqual(sess.get("user_name"), "Seeded Teacher")

        # 2. Verify zero rows inserted into helpdesk_users
        current_user_count = len(GLOBAL_DB_STATE.tables["helpdesk_users"])
        self.assertEqual(current_user_count, initial_user_count)

    def test_sso_callback_institutional_resolution(self):
        """Simulate Google OAuth2 callback; session established directly without duplicate users."""
        GLOBAL_DB_STATE.tables["helpdesk_users"] = [
            u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] 
            if u["email"] != "seeded@sreenidhi.edu.in"
        ]
        initial_user_count = len(GLOBAL_DB_STATE.tables["helpdesk_users"])

        with self.client.session_transaction() as sess:
            sess["sso_state"] = "mock_sso_state_123"

        token_cm = MagicMock()
        token_cm.read.return_value = json.dumps({"access_token": "mock_token"}).encode()
        token_mock = MagicMock()
        token_mock.__enter__.return_value = token_cm

        userinfo_cm = MagicMock()
        userinfo_cm.read.return_value = json.dumps({
            "email": "seeded@sreenidhi.edu.in",
            "name": "Seeded Teacher",
        }).encode()
        userinfo_mock = MagicMock()
        userinfo_mock.__enter__.return_value = userinfo_cm

        with patch("urllib.request.urlopen", side_effect=[token_mock, userinfo_mock]):
            res = self.client.get("/sso/callback?code=mock_code&state=mock_sso_state_123", follow_redirects=True)
            self.assertEqual(res.status_code, 200)

        # 1. Verify session was established directly from teacher_info
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("user_id"), 10)
            self.assertEqual(sess.get("role"), "FACULTY")
            self.assertEqual(sess.get("department"), "CSE")
            self.assertEqual(sess.get("user_name"), "Seeded Teacher")

        # 2. Verify zero rows inserted into helpdesk_users
        current_user_count = len(GLOBAL_DB_STATE.tables["helpdesk_users"])
        self.assertEqual(current_user_count, initial_user_count)

    def test_sso_unregistered_user_rejected(self):
        """SSO login is rejected if email is not present in institutional teacher_info or staff_roles."""
        # 1. Test via mock SSO login POST
        res_mock = self.client.post("/sso/login", data={
            "email": "unregistered.student@sreenidhi.edu.in",
            "name": "Random Student",
            "department": "CSE",
            "role": "FACULTY"
        }, follow_redirects=True)
        self.assertEqual(res_mock.status_code, 200)
        self.assertIn(b"Access restricted", res_mock.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

        # 2. Test via Google OAuth2 callback
        with self.client.session_transaction() as sess:
            sess["sso_state"] = "mock_sso_state_reject"

        token_cm = MagicMock()
        token_cm.read.return_value = json.dumps({"access_token": "mock_token"}).encode()
        token_mock = MagicMock()
        token_mock.__enter__.return_value = token_cm

        userinfo_cm = MagicMock()
        userinfo_cm.read.return_value = json.dumps({
            "email": "unregistered.student@sreenidhi.edu.in",
            "name": "Random Student",
        }).encode()
        userinfo_mock = MagicMock()
        userinfo_mock.__enter__.return_value = userinfo_cm

        with patch("urllib.request.urlopen", side_effect=[token_mock, userinfo_mock]):
            res_cb = self.client.get("/sso/callback?code=mock_code&state=mock_sso_state_reject", follow_redirects=True)
            self.assertEqual(res_cb.status_code, 200)
            self.assertIn(b"Access restricted", res_cb.data)

        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)
