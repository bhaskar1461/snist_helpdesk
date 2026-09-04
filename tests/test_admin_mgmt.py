import unittest
from unittest.mock import patch
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
import json
import db_services

class TestAdminMgmt(HelpdeskTestCase):
    def test_user_management_access_and_scoping(self):
        # 1. HOD CSE logs in. HOD should only see and manage CSE users.
        self.login_as("hod@gmail.com")
        
        # Verify page renders without Create User form
        response = self.client.get("/user-management")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"User Directory", response.data)
        self.assertNotIn(b">Create User<", response.data)
        
        # 2. Creating users via POST is disabled (405 Method Not Allowed)
        res_create = self.client.post("/user-management", data={
            "name": "CSE New Faculty",
            "email": "csenew@gmail.com",
            "password": "123",
            "role": "FACULTY",
            "department": "ECE"
        }, follow_redirects=True)
        self.assertEqual(res_create.status_code, 405)

    def test_user_update_delete(self):
        self.login_as("admin@gmail.com")

        # Update user (id 7, Demo Faculty) to change role to CA
        # Route: POST /user-management/<id>/update
        res_update = self.client.post("/user-management/7/update", data={
            "name": "Demo Faculty Updated",
            "role": "CA",
            "department": "CSE"
        }, follow_redirects=True)
        self.assertEqual(res_update.status_code, 200)
        
        updated_user = next((u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] if u["id"] == 7), None)
        self.assertEqual(updated_user["name"], "Demo Faculty Updated")
        self.assertEqual(updated_user["role"], "CA")

        # Delete user
        # Route: POST /user-management/<id>/delete
        res_delete = self.client.post("/user-management/7/delete", follow_redirects=True)
        self.assertEqual(res_delete.status_code, 200)
        
        deleted_user = next((u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] if u["id"] == 7), None)
        self.assertIsNone(deleted_user)

    def test_category_crud(self):
        # Login as CSE HOD
        self.login_as("hod@gmail.com")

        # Create a category
        # Route: POST /management/category-management
        res_cat_create = self.client.post("/management/category-management", data={
            "category_name": "Laptops",
            "department": "CSE"
        }, follow_redirects=True)
        self.assertEqual(res_cat_create.status_code, 200)

        # Check category was created
        new_cat = next((c for c in GLOBAL_DB_STATE.tables["helpdesk_categories"] if c["category_name"] == "Laptops"), None)
        self.assertIsNotNone(new_cat)

        # Toggle category status
        # Route: POST /management/category-management/<id>/toggle
        res_toggle = self.client.post(f"/management/category-management/{new_cat['id']}/toggle", follow_redirects=True)
        self.assertEqual(res_toggle.status_code, 200)
        
        toggled_cat = next((c for c in GLOBAL_DB_STATE.tables["helpdesk_categories"] if c["id"] == new_cat["id"]), None)
        self.assertEqual(toggled_cat["is_active"], 0)

        # Delete category
        # Route: POST /management/category-management/<id>/delete
        res_delete = self.client.post(f"/management/category-management/{new_cat['id']}/delete", follow_redirects=True)
        self.assertEqual(res_delete.status_code, 200)
        self.assertNotIn(new_cat["id"], [c["id"] for c in GLOBAL_DB_STATE.tables["helpdesk_categories"]])

    def test_ca_assignments_and_promotion(self):
        # Login as HOD
        self.login_as("hod@gmail.com")

        # Assign Faculty (user ID 7 is FACULTY) to category 1 and Block A
        # Route: POST /hod/ca-assignments
        response = self.client.post("/hod/ca-assignments", data={
            "faculty_id": "7",
            "category_id": "1",
            "block": "Block A"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Check that user 7 (Demo Faculty) was promoted to role CA
        promoted_user = next((u for u in GLOBAL_DB_STATE.tables["helpdesk_users"] if u["id"] == 7), None)
        self.assertEqual(promoted_user["role"], "CA")

        # Verify assignment was created
        assignment = next((a for a in GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] if a["ca_id"] == 7 and a["category_id"] == 1 and a["block"] == "Block A"), None)
        self.assertIsNotNone(assignment)

    def test_multi_ca_assignments(self):
        # Login as HOD
        self.login_as("hod@gmail.com")

        # Assign Faculty (user ID 7 is FACULTY) to multiple categories (1 and 2) and multiple blocks (Block B and Block C)
        # Route: POST /hod/ca-assignments
        response = self.client.post("/hod/ca-assignments", data={
            "faculty_id": "7",
            "categories": ["1", "2"],
            "blocks": ["Block B", "Block C"]
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Verify assignments were created for both categories and blocks (4 combinations)
        assignments = GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"]
        for cat in [1, 2]:
            for blk in ["Block B", "Block C"]:
                assignment = next((a for a in assignments if a["ca_id"] == 7 and a["category_id"] == cat and a["block"] == blk), None)
                self.assertIsNotNone(assignment, f"Assignment for Category {cat} and Block {blk} not found")

    def test_super_admin_ca_assignments(self):
        # Login as SUPER_ADMIN
        self.login_as("admin@gmail.com")

        # Verify page loads
        res_get = self.client.get("/hod/ca-assignments")
        self.assertEqual(res_get.status_code, 200)

        # Clear existing assignments in test state
        GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] = []

        # Assign Faculty (user ID 7 is FACULTY) to multiple categories (1 and 2) and multiple blocks (Block B and Block C)
        response = self.client.post("/hod/ca-assignments", data={
            "faculty_id": "7",
            "categories": ["1", "2"],
            "blocks": ["Block B", "Block C"]
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Verify assignments were created for all combinations
        assignments = GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"]
        for cat in [1, 2]:
            for blk in ["Block B", "Block C"]:
                assignment = next((a for a in assignments if a["ca_id"] == 7 and a["category_id"] == cat and a["block"] == blk), None)
                self.assertIsNotNone(assignment, f"Assignment for Category {cat} and Block {blk} not found")

    def test_location_cascade_api(self):
        self.login_as("faculty@gmail.com")

        # Route: GET /api/locations
        response = self.client.get("/api/locations")
        self.assertEqual(response.status_code, 200)
        
        # Verify JSON hierarchy matches seeded data
        data = json.loads(response.data.decode("utf-8"))
        self.assertTrue(len(data) > 0)
        
        # Check Block A structure
        block_a = data.get("Block A")
        self.assertIsNotNone(block_a)
        
        # Floors
        self.assertTrue("1st Floor" in block_a)
        floors = block_a["1st Floor"]
        self.assertTrue(len(floors) > 0)
        
        # Rooms
        self.assertTrue(any(r["room_no"] == "101" for r in floors))

    def test_ca_assignments_transaction_rollback(self):
        # Login as HOD
        self.login_as("hod@gmail.com")

        # Mock create_ca_assignment to raise ValueError on second mapping insert
        original_create = db_services.DemoDbService.create_ca_assignment
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 1:
                raise ValueError("Simulated DB failure")
            return original_create(args[0], *args[1:], **kwargs)

        # Clear existing assignments in test state
        GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] = []

        with patch.object(db_services.DemoDbService, "create_ca_assignment", side_effect=side_effect):
            # Attempt to assign CA to category 1 across two blocks (Block B and Block C)
            response = self.client.post("/hod/ca-assignments", data={
                "faculty_id": "7",
                "categories": ["1"],
                "blocks": ["Block B", "Block C"]
            }, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Assignment failed", response.data)

        # Verify that because of transaction rollback, NO assignments were created in the database
        assignments = GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"]
        self.assertEqual(len(assignments), 0, "Expected all assignments to be rolled back on failure")

    def test_cross_department_assignee_assignment_rejected(self):
        # Login as Admin
        self.login_as("admin@gmail.com")

        # Category 3 is Plumbing (Facilities). User 7 is CSE Faculty.
        # Attempt to assign CSE Faculty (user 7) to Facilities Category (3)
        response = self.client.post("/hod/ca-assignments", data={
            "faculty_id": "7",
            "category_id": "3"
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"does not match target department", response.data)
