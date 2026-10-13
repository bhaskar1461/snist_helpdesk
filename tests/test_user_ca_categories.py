from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from app import get_demo_db

class TestUserCaCategories(HelpdeskTestCase):
    def test_get_user_assigned_categories(self):
        """Verify get_user_assigned_categories returns structured categories and blocks."""
        demo_db = get_demo_db()
        # In seeded data, CA id 4 (Chandini CA, CSE) has:
        # Category 1 (Internet, Block A) via helpdesk_ca_assignments
        # Category 2 (Projector, All Blocks) via helpdesk_categories.assigned_ca_id
        cats = demo_db.get_user_assigned_categories(4)
        self.assertGreaterEqual(len(cats), 2)
        
        cat_names = [c["category_name"] for c in cats]
        self.assertIn("Internet", cat_names)
        self.assertIn("Projector", cat_names)

        internet_cat = next(c for c in cats if c["category_name"] == "Internet")
        self.assertIn("Block A", internet_cat["blocks"])

    def test_get_users_assigned_categories_map(self):
        """Verify batch querying categories for multiple users."""
        demo_db = get_demo_db()
        # Query for CA 4 and Faculty 7
        cats_map = demo_db.get_users_assigned_categories_map([4, 7])
        self.assertIn(4, cats_map)
        self.assertIn(7, cats_map)
        self.assertGreaterEqual(len(cats_map[4]), 2)
        self.assertEqual(len(cats_map[7]), 0)

    def test_user_management_view_renders_categories(self):
        """Verify user management page renders assigned categories and count for CAs."""
        self.login_as("admin@gmail.com")
        res = self.client.get("/user-management")
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn("Assigned Categories", content)
        self.assertIn("Internet", content)
        self.assertIn("Manage", content)

    def test_unassign_ca_category_action(self):
        """Verify unassigning a category from a CA."""
        self.login_as("admin@gmail.com")
        demo_db = get_demo_db()
        
        # Verify CA 4 has category 1
        cats_before = demo_db.get_user_assigned_categories(4)
        self.assertTrue(any(c["category_id"] == 1 for c in cats_before))

        # Perform unassign
        res = self.client.post("/user-management/unassign-category", data={
            "ca_id": 4,
            "category_id": 1
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn("Successfully unassigned", content)

        # Verify category 1 is removed from CA 4
        cats_after = demo_db.get_user_assigned_categories(4)
        self.assertFalse(any(c["category_id"] == 1 for c in cats_after))

    def test_hod_department_restriction_on_unassign(self):
        """Verify HOD can only unassign categories within their own department."""
        # Dr. Kavya is HOD of CSE
        self.login_as("hod@gmail.com")
        
        # CA 5 (Sravan CA) is in Facilities, Category 3 is in Facilities
        res = self.client.post("/user-management/unassign-category", data={
            "ca_id": 5,
            "category_id": 3
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn("You can only manage category assignments within your own department", content)

    def test_admin_sees_department_dropdown_in_assign_modal(self):
        """Verify Admin sees department dropdown in Assign Categories modal."""
        self.login_as("admin@gmail.com")
        res = self.client.get("/user-management")
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn('id="assign-ca-dept-select"', content)
        self.assertIn("Choose Department", content)

        res_cat = self.client.get("/management/category-assignments")
        self.assertEqual(res_cat.status_code, 200)
        content_cat = res_cat.get_data(as_text=True)
        self.assertIn('id="assign-person-dept-select"', content_cat)

    def test_hod_does_not_see_department_dropdown_in_assign_modal(self):
        """Verify HOD does NOT see department dropdown in Assign Categories modal."""
        self.login_as("hod@gmail.com")
        res = self.client.get("/user-management")
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertNotIn('id="assign-ca-dept-select"', content)

        res_cat = self.client.get("/management/category-assignments")
        self.assertEqual(res_cat.status_code, 200)
        content_cat = res_cat.get_data(as_text=True)
        self.assertNotIn('id="assign-person-dept-select"', content_cat)

    def test_unassign_ca_category_ajax_json_response(self):
        """Verify AJAX unassign request returns JSON and doesn't trigger page redirect."""
        self.login_as("admin@gmail.com")
        demo_db = get_demo_db()

        # Ensure CA 4 has category 1
        demo_db.assign_ca_to_category_blocks(1, 4, ["Block A"])
        cats_before = demo_db.get_user_assigned_categories(4)
        self.assertTrue(any(c["category_id"] == 1 for c in cats_before))

        # Perform AJAX unassign
        res = self.client.post(
            "/user-management/unassign-category",
            data={"ca_id": 4, "category_id": 1},
            headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.is_json)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("ca_id"), 4)
        self.assertEqual(data.get("category_id"), 1)

        # Verify category 1 is removed
        cats_after = demo_db.get_user_assigned_categories(4)
        self.assertFalse(any(c["category_id"] == 1 for c in cats_after))

    def test_role_demotion_clears_all_assigned_categories(self):
        """Verify changing an Assignee to USER automatically clears all their category assignments."""
        self.login_as("admin@gmail.com")
        demo_db = get_demo_db()

        # CA 4 starts with assigned categories
        cats_before = demo_db.get_user_assigned_categories(4)
        self.assertGreaterEqual(len(cats_before), 1)

        # Demote CA 4 to FACULTY (displayed as USER)
        res = self.client.post("/user-management/4/update", data={
            "name": "Chandini CA",
            "email": "ca@gmail.com",
            "role": "FACULTY",
            "department": "CSE"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        self.assertIn("All mapped categories were automatically unassigned", content)

        # Verify all category assignments were wiped for user 4
        cats_after = demo_db.get_user_assigned_categories(4)
        self.assertEqual(len(cats_after), 0)

        # Verify user 4 is not default assigned_ca_id on any category
        for cat in demo_db.list_categories():
            self.assertNotEqual(cat.get("assigned_ca_id"), 4)

        # Verify routing engine does not assign tickets to demoted user 4
        resolved = demo_db.resolve_assigned_ca(1, "Block A")
        self.assertNotEqual(resolved, 4)

    def test_user_management_table_shows_dash_for_faculty(self):
        """Verify non-assignee users render '—' in the Assigned Categories column."""
        self.login_as("admin@gmail.com")
        res = self.client.get("/user-management")
        self.assertEqual(res.status_code, 200)
        content = res.get_data(as_text=True)
        # Demo Faculty (id 7) should not have a Manage button
        self.assertNotIn('id="btn-manage-cat-7"', content)

