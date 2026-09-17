import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from app import get_demo_db


class TestRoutingFallback(HelpdeskTestCase):
    def test_routing_with_ca_assignments_returns_real_ca(self):
        """
        1. Test that with CA assignments populated, resolve_assigned_ca()
        returns a real CA (never a Super Admin) for a ticket created in a mapped block.
        """
        demo_db = get_demo_db()

        # In GLOBAL_DB_STATE, User 1 is Super Admin, User 4 is CA (Chandini CA), User 5 is CA (Sravan CA)
        # Category 1 is "Internet", Department "CSE"
        demo_db.assign_ca_to_category_blocks(1, 4, ["Block-I"])
        demo_db.assign_ca_to_category_blocks(1, 5, ["Block-II"])

        # Resolving for Block-I must return CA 4 (not Super Admin 1)
        resolved_ca_block1 = demo_db.resolve_assigned_ca(1, "Block-I")
        self.assertEqual(resolved_ca_block1, 4)
        self.assertNotEqual(resolved_ca_block1, 1)

        # Resolving for Block-II must return CA 5 (not Super Admin 1)
        resolved_ca_block2 = demo_db.resolve_assigned_ca(1, "Block-II")
        self.assertEqual(resolved_ca_block2, 5)
        self.assertNotEqual(resolved_ca_block2, 1)

    def test_create_ticket_logs_warning_on_unresolvable_ca_fallback(self):
        """
        2. Test that create_ticket logs a WARNING (not silently falling back)
        when no CA is resolvable for a category.
        """
        demo_db = get_demo_db()

        # Create a new category with NO assigned_ca_id and NO ca_assignments
        cat_id = demo_db.create_category({
            "category_name": "Unassigned Category",
            "department": "Administration",
            "assigned_ca_id": None,
            "is_active": 1,
        })

        # Ensure no CA assignments exist for this category
        GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] = [
            a for a in GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] if a["category_id"] != cat_id
        ]

        # Verify resolve_assigned_ca returns None
        resolved = demo_db.resolve_assigned_ca(cat_id, "Block-Z")
        self.assertIsNone(resolved)

        # Calling create_ticket must log a WARNING before falling back
        with self.assertLogs("db_services", level="WARNING") as log_ctx:
            ticket = demo_db.create_ticket(
                title="Unassigned Category Issue",
                description="Testing fallback warning",
                category_id=cat_id,
                created_by=7,  # Demo Faculty
                org_id="2000",
            )

        self.assertIsNotNone(ticket)
        # Check that the warning was logged
        warning_logged = any("No CA resolvable for category" in msg for msg in log_ctx.output)
        self.assertTrue(warning_logged, f"Expected fallback warning log not found in: {log_ctx.output}")
