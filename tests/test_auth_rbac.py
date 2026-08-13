import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from flask import session
import time

class TestAuthRbac(HelpdeskTestCase):
    def test_login_pages_render(self):
        # Anonymous GET / should render login page
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SNIST", response.data)
        self.assertIn(b"Sign In", response.data)

    def test_successful_logins(self):
        # Super Admin
        response = self.login_as("admin@gmail.com")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["role"], "SUPER_ADMIN")
            self.assertEqual(sess["org_id"], "2000")
        
        # Logout
        self.logout()
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

        # HOD
        response = self.login_as("hod@gmail.com")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["role"], "HOD")
            self.assertEqual(sess["department"], "CSE")

        # CA
        self.logout()
        response = self.login_as("ca@gmail.com")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["role"], "CA")

        # Faculty
        self.logout()
        response = self.login_as("faculty@gmail.com")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["role"], "FACULTY")

    def test_invalid_logins(self):
        # Wrong password
        response = self.client.post("/", data={"email": "admin@gmail.com", "password": "wrong"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid email or password", response.data)
        
        # Non-existent user
        response2 = self.client.post("/", data={"email": "nonexistent@gmail.com", "password": "123"}, follow_redirects=True)
        self.assertEqual(response2.status_code, 200)
        self.assertIn(b"Invalid email or password", response2.data)

    def test_login_rate_limiting(self):
        # Clean rate limit list for test isolation
        import app
        app.LOGIN_ATTEMPTS.clear()

        # Perform 5 failed login attempts
        for _ in range(5):
            self.client.post("/", data={"email": "admin@gmail.com", "password": "wrong"})
        
        # 6th attempt should be blocked by rate limit
        response = self.client.post("/", data={"email": "admin@gmail.com", "password": "wrong"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Too many failed login attempts", response.data)

    def test_auto_provisioning_flow(self):
        # Check that user 'seeded@sreenidhi.edu.in' does not exist in demo_users initially
        GLOBAL_DB_STATE.tables["helpdesk_users"] = [u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] if u["email"] != "seeded@sreenidhi.edu.in"]
        
        # Try to login with email = 'seeded@sreenidhi.edu.in' and password = '10001' (SAP_ID from teacher_info)
        response = self.client.post("/", data={"email": "seeded@sreenidhi.edu.in", "password": "10001"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200) # Returns dashboard on success
        
        # Verify user was automatically created in the database and logged in
        created_user = next((u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] if u["email"] == "seeded@sreenidhi.edu.in"), None)
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user["role"], "FACULTY")
        self.assertEqual(created_user["name"], "Seeded Teacher")
        self.assertEqual(created_user["department"], "CSE")

    def test_organization_resolution(self):
        from app import resolve_user_org
        # Test SNIST domains
        self.assertEqual(resolve_user_org("test@sreenidhi.edu.in", "CSE"), "2000")
        self.assertEqual(resolve_user_org("admin@gmail.com", "Administration"), "2000")
        
        # Test SNU domains
        self.assertEqual(resolve_user_org("test@suh.edu.in", "CSE"), "3000")
        self.assertEqual(resolve_user_org("test@snu.edu.in", "CSE"), "3000")
        self.assertEqual(resolve_user_org("snu.admin@gmail.com", "Administration"), "3000")
        
        # Fallback org
        self.assertEqual(resolve_user_org("unknown@yahoo.com", "Facilities"), "2000")

    def test_rbac_protections(self):
        # 1. Anonymous Access to restricted routes
        restricted_routes = [
            "/super-admin/dashboard", "/admin/dashboard", "/hod/dashboard",
            "/authority/tickets", "/user/dashboard", "/user-management",
            "/management/category-management", "/api/locations"
        ]
        for route in restricted_routes:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 302) # Redirect to login
            self.assertIn("login", response.location)

        # 2. Faculty Access Restrictions
        self.login_as("faculty@gmail.com")
        
        # Should access Faculty dashboard
        res_fac = self.client.get("/user/dashboard")
        self.assertEqual(res_fac.status_code, 200)

        # Should NOT access admin/hod/ca pages
        for route in ["/super-admin/dashboard", "/admin/dashboard", "/hod/dashboard", "/authority/tickets", "/user-management"]:
            res = self.client.get(route, follow_redirects=True)
            self.assertIn(b"You do not have access to that page", res.data)
        self.logout()

        # 3. HOD Access Restrictions
        self.login_as("hod@gmail.com")
        res_hod = self.client.get("/hod/dashboard")
        self.assertEqual(res_hod.status_code, 200)

        # Should NOT access Super Admin/Admin dashboards
        for route in ["/super-admin/dashboard", "/admin/dashboard"]:
            res = self.client.get(route, follow_redirects=True)
            self.assertIn(b"You do not have access to that page", res.data)

        # HOD CAN access user-management (restricted to CA/FACULTY)
        res_hod_um = self.client.get("/user-management")
        self.assertEqual(res_hod_um.status_code, 200)
        self.logout()

        # 4. Super Admin Full Access
        self.login_as("admin@gmail.com")
        res_sa = self.client.get("/super-admin/dashboard")
        self.assertEqual(res_sa.status_code, 200)
        res_um = self.client.get("/user-management")
        self.assertEqual(res_um.status_code, 200)

    def test_hod_impersonation(self):
        # Login as Super Admin
        self.login_as("admin@gmail.com")

        # Impersonate HOD of CSE (ID 3)
        impersonate_response = self.client.post("/impersonate-hod", data={
            "department": "CSE"
        }, follow_redirects=True)
        self.assertEqual(impersonate_response.status_code, 200)
        self.assertIn(b"Now acting as HOD for CSE", impersonate_response.data)

        # Verify session changes
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["acting_role"], "HOD")
            self.assertEqual(sess["acting_department"], "CSE")

        # Now access the HOD dashboard, it should render successfully
        hod_dashboard_response = self.client.get("/hod/dashboard")
        self.assertEqual(hod_dashboard_response.status_code, 200)

        # Stop impersonation
        stop_response = self.client.get("/exit-hod-mode", follow_redirects=True)
        self.assertEqual(stop_response.status_code, 200)
        self.assertIn(b"Stopped impersonating HOD", stop_response.data)

        # Verify session variables cleared
        with self.client.session_transaction() as sess:
            self.assertNotIn("acting_role", sess)
            self.assertNotIn("acting_department", sess)

        # Audit event created
        audit_events = GLOBAL_DB_STATE.tables["helpdesk_audit_events"]
        self.assertTrue(any(e["event_type"] == "IMPERSONATION_START" for e in audit_events))
        self.assertTrue(any(e["event_type"] == "IMPERSONATION_STOP" for e in audit_events))

    def test_assignee_role_access(self):
        # Test that users with role ASSIGNEE can log in and access /authority/tickets without redirect loops
        self.login_as("ca@gmail.com")
        res = self.client.get("/authority/tickets", follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Assignee Dashboard", res.data)
        
        # Test login redirect when already logged in as ASSIGNEE
        res_login = self.client.get("/login", follow_redirects=True)
        self.assertEqual(res_login.status_code, 200)
        self.logout()

