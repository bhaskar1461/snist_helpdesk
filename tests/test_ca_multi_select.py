import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE

class TestCAMultiSelect(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        self.login_as("admin@gmail.com")

    def test_create_category_with_multiple_location_blocks(self):
        # Post category creation with multiple location blocks
        res = self.client.post("/management/category-assignments", data={
            "action": "create_category",
            "category_name": "Multi Block Test Category",
            "department": "CSE",
            "assigned_ca_id": "7",
            "blocks": ["Academic Block 1", "Academic Block 4", "Block 7", "Admin Block"]
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b"created successfully", res.data.lower())
        self.assertIn(b"created 4 location block mapping(s)", res.data.lower())

        # Verify 4 distinct mapping records were inserted into demo_ca_assignments
        new_cat = next((c for c in GLOBAL_DB_STATE.tables["demo_categories"] if c["category_name"] == "Multi Block Test Category"), None)
        self.assertIsNotNone(new_cat)

        mappings = [m for m in GLOBAL_DB_STATE.tables["demo_ca_assignments"] if m["category_id"] == new_cat["id"]]
        mapped_blocks = set(m["block"] for m in mappings)
        self.assertEqual(mapped_blocks, {"Academic Block 1", "Academic Block 4", "Block 7", "Admin Block"})

    def test_create_category_duplicate_block_prevention(self):
        # Create category via form endpoint first
        res_create = self.client.post("/management/category-assignments", data={
            "action": "create_category",
            "category_name": "Existing Block Category",
            "department": "CSE",
            "assigned_ca_id": "7",
            "blocks": ["Academic Block 1"]
        }, follow_redirects=True)
        self.assertEqual(res_create.status_code, 200)

        created_cat = next((c for c in GLOBAL_DB_STATE.tables["demo_categories"] if c["category_name"] == "Existing Block Category"), None)
        self.assertIsNotNone(created_cat)
        cat_id = created_cat["id"]

        # Post update category with existing Academic Block 1 and new Block 7
        res = self.client.post("/management/category-assignments", data={
            "action": "update_category",
            "category_id": str(cat_id),
            "category_name": "Existing Block Category",
            "department": "CSE",
            "assigned_ca_id": "7",
            "blocks": ["Academic Block 1", "Block 7"]
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b"created 1 location block mapping(s)", res.data.lower())
        self.assertIn(b"1 skipped because they already existed", res.data.lower())

        # Verify only 1 new mapping was created, total 2 mappings
        mappings = [m for m in GLOBAL_DB_STATE.tables["demo_ca_assignments"] if m["category_id"] == cat_id]
        self.assertEqual(len(mappings), 2)
        mapped_blocks = set(m["block"] for m in mappings)
        self.assertEqual(mapped_blocks, {"Academic Block 1", "Block 7"})

    def test_assign_ca_multi_block(self):
        # Assign CA with multi-select blocks
        res = self.client.post("/management/category-assignments", data={
            "action": "assign_ca",
            "faculty_id": "7",
            "categories": ["1"],
            "blocks": ["Block X", "Block Y"]
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b"ca assigned successfully", res.data.lower())

        mappings = [m for m in GLOBAL_DB_STATE.tables["demo_ca_assignments"] if m["category_id"] == 1 and m["ca_id"] == 7]
        mapped_blocks = set(m["block"] for m in mappings)
        self.assertTrue({"Block X", "Block Y"}.issubset(mapped_blocks))

if __name__ == "__main__":
    unittest.main()
