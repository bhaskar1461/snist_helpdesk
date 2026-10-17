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

    def test_routing_with_block_aliases(self):
        """
        3. Test that resolve_assigned_ca normalizes between Roman and Arabic numerals,
        as well as Academic prefixes (e.g. Block 11 <-> Block-XI).
        """
        demo_db = get_demo_db()

        # Category 1: assign CA 4 to Block-XI, CA 5 to Block-III
        demo_db.assign_ca_to_category_blocks(1, 4, ["Block-XI"])
        demo_db.assign_ca_to_category_blocks(1, 5, ["Block-III"])

        # Test resolving Arabic numeral 'Block 11' maps to CA 4 (assigned to Block-XI)
        self.assertEqual(demo_db.resolve_assigned_ca(1, "Block 11"), 4)
        self.assertEqual(demo_db.resolve_assigned_ca(1, "Block-11"), 4)
        self.assertEqual(demo_db.resolve_assigned_ca(1, "Academic Block 11"), 4)

        # Test resolving 'Block 3' maps to CA 5 (assigned to Block-III)
        self.assertEqual(demo_db.resolve_assigned_ca(1, "Block 3"), 5)
        self.assertEqual(demo_db.resolve_assigned_ca(1, "Block-3"), 5)

        # Reverse test: assign CA 4 to 'Block 5', resolve with Roman numeral 'Block-V'
        demo_db.assign_ca_to_category_blocks(1, 4, ["Block 5"])
        self.assertEqual(demo_db.resolve_assigned_ca(1, "Block-V"), 4)
        self.assertEqual(demo_db.resolve_assigned_ca(1, "Block 5"), 4)

    def test_specific_block_takes_precedence_over_all_blocks(self):
        """
        4. Test that a specific block assignment takes priority over a wildcard 'All Blocks' assignment.
        """
        demo_db = get_demo_db()

        # Category 1: CA 6 is mapped to 'All Blocks', CA 4 is specifically mapped to 'Block-V'
        demo_db.assign_ca_to_category_blocks(1, 6, ["All Blocks"])
        demo_db.assign_ca_to_category_blocks(1, 4, ["Block-V"])

        # For Block-V (or Block 5), specific CA 4 should be returned, not All Blocks CA 6
        resolved = demo_db.resolve_assigned_ca(1, "Block 5")
        self.assertEqual(resolved, 4)

        # For an unmapped block (e.g. Block-VIII), All Blocks CA 6 should be returned
        resolved_unmapped = demo_db.resolve_assigned_ca(1, "Block-VIII")
        self.assertEqual(resolved_unmapped, 6)

    def test_create_ticket_with_block_without_room(self):
        """
        5. Test that submitting a ticket with block (and location_id=None)
        correctly routes to the block CA and resolves location.
        """
        demo_db = get_demo_db()
        demo_db.assign_ca_to_category_blocks(1, 4, ["Block-XI"])

        ticket_id = demo_db.create_ticket(
            title="Switch failure",
            description="Testing block routing without room",
            category_id=1,
            created_by=7,
            org_id="2000",
            location_id=None,
            block="Block 11",
        )
        t = demo_db.get_ticket(ticket_id)
        self.assertEqual(t["assigned_to"], 4)

    def test_legacy_ticket_location_fallback(self):
        """
        6. Test that legacy tickets with NULL location_id extract location from title.
        """
        demo_db = get_demo_db()
        ticket_data = {
            "title": "Monitor issue in Block-V 5003",
            "location_block": None,
            "location_room_no": None,
            "created_at": "2026-09-17 10:24:02",
        }
        enriched = demo_db.add_escalation_status(ticket_data)
        self.assertEqual(enriched["location_block"], "Block-V")
        self.assertEqual(enriched["location_room_no"], "5003")

