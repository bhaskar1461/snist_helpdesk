"""Phase 6 Security & Rate Limiting Regression Test Suite.

Tests:
1. Rate limiting: 5 failed logins on one identifier -> 6th rejected before password check; different identifier from same IP still allowed until IP threshold.
2. Rate limit is DB-backed: multiple service instances sharing one MockDbState share attempt counters.
3. Attachment IDOR: user B (unrelated) requests ticket A's attachment -> 404. Submitter, assigned CA, and admin -> 200. Unauthenticated -> 302 login.
4. Path traversal: /tickets/1/attachment/../../etc/passwd style attempts -> 404, never served.
5. Session fixation: login flow calls session.clear(); session identity regenerated.
6. CSRF: POST without token -> 400 rejected; POST with valid token -> passes.
7. Security headers present on responses (nosniff, DENY, CSP, etc.).
"""

import os
import re
from pathlib import Path
from unittest.mock import patch

from app.config import UPLOAD_DIR
from db_services import DemoDbService
from tests.test_base import GLOBAL_DB_STATE, HelpdeskTestCase


class TestSecurityHardening(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        # Seed a standard ticket for attachment testing
        self.ticket_id = 1
        self.ticket = {
            "id": self.ticket_id,
            "title": "Lab Network Connection Failure",
            "description": "Internet down in CSE Lab 1",
            "category_id": 1,
            "created_by": 7,  # Demo Faculty (faculty@gmail.com)
            "created_by_email": "faculty@gmail.com",
            "assigned_to": 4,  # Chandini CA (ca@gmail.com)
            "assigned_to_email": "ca@gmail.com",
            "department": "CSE",
            "status": "IN_PROGRESS",
            "org_id": "2000",
            "location_id": 1,
        }
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [self.ticket]
        GLOBAL_DB_STATE.next_ids["helpdesk_tickets"] = 2

        # Create physical test attachment in UPLOAD_DIR
        self.test_filename = f"{self.ticket_id}-1700000000-safe_sample.pdf"
        self.test_filepath = UPLOAD_DIR / self.test_filename
        self.test_filepath.write_bytes(b"%PDF-1.4\n%Test Secure PDF Document\n%%EOF")

        # Record in mock attachments table
        GLOBAL_DB_STATE.tables["helpdesk_attachments"] = [{
            "id": 1,
            "ticket_id": self.ticket_id,
            "stored_filename": self.test_filename,
            "original_filename": "safe_sample.pdf",
            "uploaded_by": 4,
            "file_size": len(b"%PDF-1.4\n%Test Secure PDF Document\n%%EOF"),
            "mime_type": "application/pdf",
        }]
        GLOBAL_DB_STATE.next_ids["helpdesk_attachments"] = 2

    def tearDown(self):
        super().tearDown()
        if self.test_filepath.exists():
            try:
                self.test_filepath.unlink()
            except Exception:
                pass

    # ── 1. Login Rate Limiting (User & IP Thresholds) ───────────────────
    def test_rate_limiting_user_and_ip_thresholds(self):
        """5 failed logins for one identifier locks out that identifier before password check.
        A different identifier from the same IP is still allowed.
        """
        ip = "192.0.2.10"
        target_email = "victim@gmail.com"
        other_email = "faculty@gmail.com"

        # 5 consecutive failed login attempts on target_email
        for attempt in range(1, 6):
            res = self.client.post("/", data={"email": target_email, "password": "wrong_password"},
                                   environ_base={"REMOTE_ADDR": ip})
            self.assertEqual(res.status_code, 200)
            self.assertIn("Invalid email or password", res.get_data(as_text=True))

        # 6th attempt on target_email is locked out before password verification
        res6 = self.client.post("/", data={"email": target_email, "password": "123"},
                                environ_base={"REMOTE_ADDR": ip})
        body6 = res6.get_data(as_text=True)
        self.assertIn("Too many failed login attempts", body6)

        # Different user from the SAME IP is NOT locked out (IP threshold = 30)
        res_other = self.client.post("/", data={"email": other_email, "password": "123"},
                                     environ_base={"REMOTE_ADDR": ip}, follow_redirects=False)
        # Should authenticate and redirect (302) to dashboard
        self.assertEqual(res_other.status_code, 302)

    # ── 2. Multi-Worker DB-Backed Rate Limiting ─────────────────────────
    def test_rate_limiting_is_db_backed_across_workers(self):
        """Simulate two worker instances sharing the same DB: attempt counter is synchronized."""
        worker1_db = DemoDbService(None)
        worker2_db = DemoDbService(None)

        ip = "198.51.100.55"
        identifier = "sync.test@sreenidhi.edu.in"

        # Worker 1 registers 5 failed attempts
        for _ in range(5):
            worker1_db.record_login_attempt(identifier, ip, outcome="FAILURE")

        # Worker 2 immediately checks rate limit for the same identifier
        is_limited, reason = worker2_db.check_rate_limit(identifier, ip)
        self.assertTrue(is_limited, "Worker 2 must see failures recorded by Worker 1")
        self.assertIn("Too many failed login attempts", reason)

    # ── 3. Attachment IDOR Access Control ───────────────────────────────
    def test_attachment_idor_access_control(self):
        """Unauthenticated -> 302 redirect. Unrelated user -> 404 (never 403). Submitter, CA, Admin -> 200."""
        canonical_url = f"/tickets/{self.ticket_id}/attachment/{self.test_filename}"
        legacy_shim_url = f"/uploads/{self.test_filename}"

        # A. Unauthenticated user
        self.logout()
        res_unauth = self.client.get(canonical_url)
        self.assertEqual(res_unauth.status_code, 302)
        self.assertIn("/login", res_unauth.headers.get("Location", ""))

        res_shim_unauth = self.client.get(legacy_shim_url)
        self.assertEqual(res_shim_unauth.status_code, 302)

        # B. Unrelated logged-in user (e.g. Sravan CA in Facilities dept, ID 5)
        # Ticket is CSE dept, created by Faculty ID 7, assigned to CA ID 4
        self.login_as("sravan.ca@gmail.com")
        res_unrelated = self.client.get(canonical_url)
        self.assertEqual(res_unrelated.status_code, 404, "Must return 404 to avoid leaking attachment existence")

        res_shim_unrelated = self.client.get(legacy_shim_url)
        self.assertEqual(res_shim_unrelated.status_code, 404)
        self.logout()

        # C. Ticket Submitter (Demo Faculty ID 7)
        self.login_as("faculty@gmail.com")
        res_submitter = self.client.get(canonical_url)
        self.assertEqual(res_submitter.status_code, 200)
        self.assertEqual(res_submitter.headers.get("X-Content-Type-Options"), "nosniff")

        # Legacy shim 302 redirects to canonical route for authorized submitter
        res_shim_submitter = self.client.get(legacy_shim_url)
        self.assertEqual(res_shim_submitter.status_code, 302)
        self.assertIn(canonical_url, res_shim_submitter.headers.get("Location", ""))
        self.logout()

        # D. Assigned CA (Chandini CA ID 4)
        self.login_as("ca@gmail.com")
        res_ca = self.client.get(canonical_url)
        self.assertEqual(res_ca.status_code, 200)
        self.logout()

        # E. Campus Admin (Admin ID 2)
        self.login_as("campus.admin@gmail.com")
        res_admin = self.client.get(canonical_url)
        self.assertEqual(res_admin.status_code, 200)
        self.logout()

    # ── 4. Path Traversal Defense ───────────────────────────────────────
    def test_path_traversal_attempts_blocked(self):
        """Directory traversal attempts via canonical and legacy routes return 404."""
        self.login_as("campus.admin@gmail.com")

        traversal_payloads = [
            f"/tickets/{self.ticket_id}/attachment/../../../../etc/passwd",
            f"/tickets/{self.ticket_id}/attachment/..%2F..%2F..%2Fetc%2Fpasswd",
            "/uploads/../../../../etc/passwd",
            "/uploads/..%2F..%2F..%2Fetc%2Fpasswd",
            "/uploads/subfolder/../../../app.py",
        ]

        for path in traversal_payloads:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 404, f"Path traversal attempt '{path}' must return 404")

    # ── 5. Session Fixation & Auth Hygiene ──────────────────────────────
    def test_session_fixation_and_invalidation(self):
        """Successful login regenerates session identity; logout invalidates cookie and session."""
        # Initial unauthenticated session
        with self.client.session_transaction() as sess:
            sess["pre_login_tracker"] = "untrusted-token-123"

        res_login = self.login_as("faculty@gmail.com", "123")
        self.assertEqual(res_login.status_code, 302)

        # Pre-login session data must be cleared
        with self.client.session_transaction() as sess:
            self.assertNotIn("pre_login_tracker", sess, "Pre-login session data must be cleared")
            self.assertEqual(sess.get("user_id"), 7)
            self.assertEqual(sess.get("role"), "FACULTY")

        # Logout clears session and deletes cookie
        res_logout = self.logout()
        self.assertEqual(res_logout.status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertNotIn("user_id", sess)

    # ── 6. CSRF Token Enforcement ───────────────────────────────────────
    def test_csrf_protection_enforcement(self):
        """With CSRF enabled: state-changing POST without token returns 400; with valid token passes."""
        self.app.config["WTF_CSRF_ENABLED"] = True
        try:
            # 1. POST without token -> 400 Bad Request
            res_bad = self.client.post("/", data={"email": "faculty@gmail.com", "password": "123"})
            self.assertEqual(res_bad.status_code, 400)

            # 2. Fetch login page, extract CSRF token
            res_get = self.client.get("/")
            self.assertEqual(res_get.status_code, 200)
            token_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', res_get.get_data(as_text=True))
            self.assertTrue(token_match, "CSRF token input must be present in rendered login form")
            valid_token = token_match.group(1)

            # 3. POST with valid CSRF token -> 302 Redirect (authentication proceeds)
            res_good = self.client.post("/", data={
                "csrf_token": valid_token,
                "email": "faculty@gmail.com",
                "password": "123"
            })
            self.assertEqual(res_good.status_code, 302)
        finally:
            self.app.config["WTF_CSRF_ENABLED"] = False

    # ── 7. Security Headers Verification ────────────────────────────────
    def test_security_headers_present(self):
        """Every response must carry nosniff, DENY, CSP, Referrer-Policy, and Permissions-Policy."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)

        headers = res.headers
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("Referrer-Policy"), "strict-origin-when-cross-origin")
        self.assertIn("geolocation=()", headers.get("Permissions-Policy", ""))

        csp = headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("https://unpkg.com", csp)
        self.assertIn("https://fonts.googleapis.com", csp)
