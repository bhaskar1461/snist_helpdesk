import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from sms_services import _normalize_phone
from app import resolve_user_org
import re

class TestPermutationsAndFuzzing(HelpdeskTestCase):
    def test_phone_normalization_permutations(self):
        # We run 100 checks on phone number formats to verify normalization robustness
        test_cases = []
        
        # 1. 10-digit variations (should prepend 91)
        for i in range(20):
            num = f"98765{i:05d}"
            expected = f"9198765{i:05d}"
            test_cases.append((num, expected))
            
        # 2. 12-digit variations starting with 91 (should stay same)
        for i in range(20):
            num = f"9198765{i:05d}"
            expected = f"9198765{i:05d}"
            test_cases.append((num, expected))

        # 3. Formatting symbols variations (should clean and prepend 91 or keep 91)
        for i in range(20):
            num = f"+91-98765-{i:05d}"
            expected = f"9198765{i:05d}"
            test_cases.append((num, expected))
            
        for i in range(20):
            num = f" (987) 65{i:05d} "
            expected = f"9198765{i:05d}"
            test_cases.append((num, expected))

        # 4. Invalid alphabetic and empty variations (should return None)
        for i in range(20):
            num = "invalidphone" + "x" * i
            expected = None
            test_cases.append((num, expected))

        self.assertEqual(len(test_cases), 100)
        
        # Execute all 100 assertions
        for idx, (num, expected) in enumerate(test_cases):
            with self.subTest(idx=idx, num=num):
                self.assertEqual(_normalize_phone(num), expected)

    def test_org_resolution_permutations(self):
        # We run 150 checks on organization routing rules
        test_cases = []

        # 1. SNIST Org (2000) email variations
        for i in range(50):
            email = f"user.{i}@sreenidhi.edu.in"
            test_cases.append((email, "CSE", "2000"))

        # 2. SNU Org (3000) email variations
        for i in range(50):
            email = f"student.{i}@suh.edu.in"
            test_cases.append((email, "CSE", "3000"))

        # 3. SNU Org alternative domain variations
        for i in range(25):
            email = f"prof.{i}@snu.edu.in"
            test_cases.append((email, "ECE", "3000"))

        # 4. Fallback org check variations
        for i in range(25):
            email = f"external.{i}@gmail.com"
            test_cases.append((email, "Facilities", "2000"))

        self.assertEqual(len(test_cases), 150)

        # Execute all 150 assertions
        for idx, (email, dept, expected_org) in enumerate(test_cases):
            with self.subTest(idx=idx, email=email, dept=dept):
                self.assertEqual(resolve_user_org(email, dept), expected_org)

    def test_login_security_payload_fuzzing(self):
        # We test 100 boundary login inputs, including SQL injection signatures,
        # HTML tag injection patterns, long inputs, and special chars
        malicious_inputs = [
            # SQL Injection patterns
            "' OR '1'='1",
            "admin'--",
            "' UNION SELECT NULL--",
            "\" OR \"\"=\"",
            # HTML / XSS Injection patterns
            "<script>alert(1)</script>",
            "<img src=x onerror=alert(1)>",
            "javascript:alert(1)",
            "HOD <b>bold</b>",
            # Special chars
            "email!#$%&'*+-/=?^_`{|}~@gmail.com",
            # Empty / Whitespace variants
            "", "   ", "\n", "\t", " \n \t "
        ]
        
        # Build 100 check cases
        test_cases = []
        for i in range(100):
            payload_email = malicious_inputs[i % len(malicious_inputs)]
            # Add uniqueness to avoid rate limit grouping
            unique_email = f"test_{i}_{payload_email}"
            test_cases.append(unique_email)
            
        self.assertEqual(len(test_cases), 100)

        # Execute 100 check assertions
        for idx, email in enumerate(test_cases):
            with self.subTest(idx=idx, email=email):
                # Try logging in with the fuzzed email.
                # It should not crash the server (returns 200 with validation warning or invalid password message)
                response = self.client.post("/", data={"email": email, "password": "123"}, follow_redirects=True)
                self.assertEqual(response.status_code, 200)

    def test_ticket_creation_payload_fuzzing(self):
        # We test 50 variations of ticket creation payloads (various descriptions, boundaries, categories)
        self.login_as("faculty@gmail.com")
        
        test_cases = []
        for i in range(50):
            title = f"Problem #{i}"
            desc = "A" * (10 + i * 5) # growing size
            cat_id = "1" if i % 2 == 0 else "2"
            loc_id = "1" if i % 3 == 0 else "2"
            test_cases.append((title, desc, cat_id, loc_id))
            
        self.assertEqual(len(test_cases), 50)
        
        # Execute 50 ticket creation assertions
        for idx, (title, desc, cat_id, loc_id) in enumerate(test_cases):
            with self.subTest(idx=idx, title=title):
                # Check creation handles safely without 500 error
                response = self.client.post("/tickets/create", data={
                    "title": title,
                    "description": desc,
                    "category_id": cat_id,
                    "location_id": loc_id
                }, follow_redirects=True)
                self.assertEqual(response.status_code, 200)
