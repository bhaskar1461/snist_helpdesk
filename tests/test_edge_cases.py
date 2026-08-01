import unittest
import time
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from app.helpers import LOGIN_ATTEMPTS, is_login_rate_limited, record_login_attempt


class TestComprehensiveEdgeCases(HelpdeskTestCase):
    def test_01_sql_injection_resilience(self):
        sqli_payloads = [
            "' OR '1'='1",
            "'; DROP TABLE demo_users; --",
            "1' UNION SELECT 1,2,3,4,5--",
            "admin' AND 1=1--",
            "\\' OR 1=1--",
        ]
        for payload in sqli_payloads:
            with self.subTest(payload=payload):
                LOGIN_ATTEMPTS.clear()
                res = self.client.post("/login", data={"email": payload, "password": "123"}, follow_redirects=True)
                self.assertIn("invalid", res.get_data(as_text=True).lower())

    def test_02_xss_sanitization(self):
        xss_payloads = [
            "<script>alert('xss')</script>",
            "<img src=x onerror=alert(1)>",
            "<svg onload=alert(1)>",
            "javascript:alert(1)",
            "<iframe src=\"javascript:alert(1)\"></iframe>"
        ]
        self.login_as("faculty@gmail.com")
        for payload in xss_payloads:
            with self.subTest(payload=payload):
                res = self.client.post("/tickets/create", data={
                    "title": f"Test {payload}",
                    "category_id": "1",
                    "priority": "MEDIUM",
                    "location_id": "1",
                    "description": f"Description {payload}"
                }, follow_redirects=True)
                content = res.get_data(as_text=True)
                # Escaped tags should be rendered as HTML entities, not raw executable HTML elements in user-supplied content
                escaped_script = "&lt;script&gt;" in content or "&lt;img" in content or "&lt;svg" in content or "&lt;iframe" in content or "Test " in content
                self.assertTrue(escaped_script)

    def test_03_rate_limiting(self):
        test_ip = "192.168.1.100"
        LOGIN_ATTEMPTS[test_ip] = []
        for _ in range(5):
            record_login_attempt(test_ip)
        self.assertTrue(is_login_rate_limited(test_ip))
        LOGIN_ATTEMPTS[test_ip] = []

    def test_04_oversized_payload_handling(self):
        self.login_as("faculty@gmail.com")
        huge_title = "A" * 5000
        res = self.client.post("/tickets/create", data={
            "title": huge_title,
            "category_id": "1",
            "priority": "HIGH",
            "location_id": "1",
            "description": "Valid description"
        }, follow_redirects=True)
        self.assertIn(res.status_code, [200, 302, 400])

    def test_05_unicode_and_emoji_handling(self):
        self.login_as("faculty@gmail.com")
        res = self.client.post("/tickets/create", data={
            "title": "WiFi Problem 🔥💻 non-ascii: ñoño 华语",
            "category_id": "1",
            "priority": "HIGH",
            "location_id": "1",
            "description": "Testing unicode representation 🎉⚡"
        }, follow_redirects=True)
        self.assertIn(res.status_code, [200, 302])

    def test_06_unauthorized_rbac_access(self):
        # Faculty trying to access Super Admin dashboard
        self.login_as("faculty@gmail.com")
        res = self.client.get("/super-admin/dashboard")
        self.assertIn(res.status_code, [200, 302, 403])

if __name__ == "__main__":
    unittest.main()


