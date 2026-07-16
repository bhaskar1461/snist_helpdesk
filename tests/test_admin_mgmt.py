import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
import json

class TestAdminMgmt(HelpdeskTestCase):
    def test_user_management_access_and_scoping(self):
        # 1. HOD CSE logs in. HOD should only see and manage CSE users.
        self.login_as("hod@gmail.com")
        
        # Verify page renders
        response = self.client.get("/user-management")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"User Management", response.data)
        
        # 2. HOD CSE creates a new Faculty user in ECE (Should be restricted / default to CSE)
        # In HOD user-management routes, department is forced to HOD's department.
        # Let's verify by posting a user payload.
        res_create = self.client.post("/user-management", data={
            "name": "CSE New Faculty",
            "email": "csenew@gmail.com",
            "password": "123",
            "role": "FACULTY",
            "department": "ECE" # HOD tries to select ECE
        }, follow_redirects=True)
        self.assertEqual(res_create.status_code, 200)
        
        # CSE HOD's action should force creation in CSE, not ECE
        created_user = next((u for u in GLOBAL_DB_STATE.tables["demo_users"] if u["email"] == "csenew@gmail.com"), None)
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user["department"], "CSE") # Forced to HOD's department

        # 3. Super Admin logs in. Super Admin can manage anyone in any department.
        self.logout()
        self.login_as("admin@gmail.com")
        res_sa_create = self.client.post("/user-management", data={
            "name": "ECE New Faculty",
            "email": "ecenew@gmail.com",
            "password": "123",
            "role": "FACULTY",
            "department": "ECE" # Super admin specifies ECE
        }, follow_redirects=True)
        self.assertEqual(res_sa_create.status_code, 200)
        
        ece_user = next((u for u in GLOBAL_DB_STATE.tables["demo_users"] if u["email"] == "ecenew@gmail.com"), None)
        self.assertIsNotNone(ece_user)
        self.assertEqual(ece_user["department"], "ECE")

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
        
        updated_user = next((u for u in GLOBAL_DB_STATE.tables["demo_users"] if u["id"] == 7), None)
        self.assertEqual(updated_user["name"], "Demo Faculty Updated")
        self.assertEqual(updated_user["role"], "CA")

        # Delete user
        # Route: POST /user-management/<id>/delete
        res_delete = self.client.post("/user-management/7/delete", follow_redirects=True)
        self.assertEqual(res_delete.status_code, 200)
        
        deleted_user = next((u for u in GLOBAL_DB_STATE.tables["demo_users"] if u["id"] == 7), None)
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
        new_cat = next((c for c in GLOBAL_DB_STATE.tables["demo_categories"] if c["category_name"] == "Laptops"), None)
        self.assertIsNotNone(new_cat)

        # Toggle category status
        # Route: POST /management/category-management/<id>/toggle
        res_toggle = self.client.post(f"/management/category-management/{new_cat['id']}/toggle", follow_redirects=True)
        self.assertEqual(res_toggle.status_code, 200)
        
        toggled_cat = next((c for c in GLOBAL_DB_STATE.tables["demo_categories"] if c["id"] == new_cat["id"]), None)
        self.assertEqual(toggled_cat["is_active"], 0)

        # Delete category
        # Route: POST /management/category-management/<id>/delete
        res_delete = self.client.post(f"/management/category-management/{new_cat['id']}/delete", follow_redirects=True)
        self.assertEqual(res_delete.status_code, 200)
        self.assertNotIn(new_cat["id"], [c["id"] for c in GLOBAL_DB_STATE.tables["demo_categories"]])

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
        promoted_user = next((u for u in GLOBAL_DB_STATE.tables["demo_users"] if u["id"] == 7), None)
        self.assertEqual(promoted_user["role"], "CA")

        # Verify assignment was created
        assignment = next((a for a in GLOBAL_DB_STATE.tables["demo_ca_assignments"] if a["ca_id"] == 7 and a["category_id"] == 1 and a["block"] == "Block A"), None)
        self.assertIsNotNone(assignment)

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
