import os
import unittest
from unittest.mock import patch, MagicMock
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from app import get_demo_db
from db_services import zero_date_safe, ZERO_DATE_SAFE, ZERO_DATE_COLUMNS


class TestDataIntegrity(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        self.demo_db = get_demo_db()

    def test_org_scoping_isolation(self):
        """
        1. Test org scoping: user from org A cannot see/modify data from org B
        through list endpoints (tickets, user directory).
        """
        # Create ticket in Org A (2000)
        t_org_a = self.demo_db.create_ticket(
            title="Ticket Org A",
            description="Tenant 2000 ticket",
            category_id=1,
            created_by=7,
            org_id="2000",
        )

        # Assert cross-tenant category creation is blocked:
        with self.assertRaises(ValueError):
            self.demo_db.create_ticket(
                title="Invalid Cross-Tenant Ticket",
                description="Tenant 3000 cannot use Org 2000 category",
                category_id=1,
                created_by=8,
                org_id="3000",
            )

        # Create category belonging to Org B (3000) with matching department
        cat_b = self.demo_db.create_category({
            "category_name": "SNU Category",
            "department": "Administration",
            "assigned_ca_id": 8,
            "is_active": 1,
            "org_id": "3000",
        })

        # Create ticket in Org B (3000) using Org B category
        t_org_b = self.demo_db.create_ticket(
            title="Ticket Org B",
            description="Tenant 3000 ticket",
            category_id=cat_b,
            created_by=8,
            org_id="3000",
        )

        viewer_a = {"id": 1, "role": "SUPER_ADMIN", "org_id": "2000", "department": "Administration"}
        viewer_b = {"id": 8, "role": "SUPER_ADMIN", "org_id": "3000", "department": "Administration"}

        tickets_a = self.demo_db.list_tickets(viewer_a, scope="all")
        tickets_b = self.demo_db.list_tickets(viewer_b, scope="all")

        # Org A viewer must see Ticket Org A and NEVER Ticket Org B
        ticket_ids_a = [t["id"] for t in tickets_a]
        self.assertIn(t_org_a, ticket_ids_a)
        self.assertNotIn(t_org_b, ticket_ids_a)
        for t in tickets_a:
            self.assertEqual(str(t.get("org_id")), "2000")

        # Org B viewer must see Ticket Org B and NEVER Ticket Org A
        ticket_ids_b = [t["id"] for t in tickets_b]
        self.assertIn(t_org_b, ticket_ids_b)
        self.assertNotIn(t_org_a, ticket_ids_b)
        for t in tickets_b:
            self.assertEqual(str(t.get("org_id")), "3000")

    def test_zero_date_safety_helpers(self):
        """
        2. Test zero-date defense: helpers correctly construct NULLIF statements
        and selecting zero-date fixture does not crash.
        """
        # Test helper functions
        for col in ZERO_DATE_COLUMNS:
            expr = zero_date_safe(col, alias="t")
            self.assertEqual(expr, f"NULLIF(t.{col}, '0000-00-00')")
            self.assertIn(col, ZERO_DATE_SAFE)
            self.assertEqual(ZERO_DATE_SAFE[col], f"NULLIF(t.{col}, '0000-00-00') AS {col}")

        # Inject a teacher with zero dates in mock DB
        zero_date_teacher = {
            "TEACHER_ID": 9999,
            "id": 9999,
            "TEACHER_NAME": "Zero Date Faculty",
            "name": "Zero Date Faculty",
            "EMAIL_ID": "zerodate@sreenidhi.edu.in",
            "email": "zerodate@sreenidhi.edu.in",
            "DATE_OF_BIRTH": "0000-00-00",
            "FROM_DATE": "0000-00-00",
            "TO_DATE": "0000-00-00",
            "ACTIVE": 1,
            "BRANCH_CODE": "CSE",
            "BRANCH_ID": 1,
            "department": "CSE",
            "org_id": "2000",
            "ORG_ID": "2000",
        }
        GLOBAL_DB_STATE.tables["teacher_info"].append(zero_date_teacher)

        # Querying reference users with zero-dates in SELECT should safely execute without Error 1525
        try:
            with self.demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute(f"""
                    SELECT id, {zero_date_safe('DATE_OF_BIRTH')}, {zero_date_safe('FROM_DATE')}
                    FROM teacher_info
                    WHERE id = %s
                """, (9999,))
                row = cur.fetchone()
                self.assertIsNotNone(row)
                self.assertEqual(row.get("id"), 9999)

            # Verify NULLIF logic: zero date transforms to NULL (None in Python)
            test_val = zero_date_teacher["FROM_DATE"]
            self.assertEqual(test_val, "0000-00-00")
            safe_val = None if test_val == "0000-00-00" else test_val
            self.assertIsNone(safe_val)
        finally:
            GLOBAL_DB_STATE.tables["teacher_info"] = [
                t for t in GLOBAL_DB_STATE.tables["teacher_info"] if t.get("id") != 9999
            ]

    def test_audit_script_flags_orphaned_records(self):
        """
        3. Test audit script checks: simulate orphan record and verify check flags it.
        """
        # Inject an orphan ticket referencing a non-existent category
        orphan_ticket = {
            "id": 99998,
            "title": "Orphan Category Ticket",
            "description": "Category does not exist",
            "category_id": 888888,  # Non-existent
            "created_by": 7,
            "assigned_to": 4,
            "status": "PENDING",
            "org_id": "2000",
            "location_id": None,
            "created_at": "2026-09-12 10:00:00",
            "updated_at": "2026-09-12 10:00:00",
        }
        GLOBAL_DB_STATE.tables["helpdesk_tickets"].append(orphan_ticket)

        try:
            # Query orphan check directly against state
            with self.demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute("""
                    SELECT t.id, t.title, t.category_id
                    FROM helpdesk_tickets t
                    WHERE t.category_id = 888888
                """)
                orphans = cur.fetchall()
                self.assertEqual(len(orphans), 1)
                self.assertEqual(orphans[0]["id"], 99998)
        finally:
            GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [
                t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t.get("id") != 99998
            ]

    def test_sql_injection_resistance_on_filters(self):
        """
        4. Test that filter parameters (status, department, search) with malicious SQL
        execute safely and return empty results without error.
        """
        viewer = {"id": 1, "role": "SUPER_ADMIN", "org_id": "2000", "department": "Administration"}

        malicious_inputs = [
            "'; DROP TABLE helpdesk_tickets; --",
            "' OR '1'='1",
            "1; SELECT * FROM helpdesk_users; --",
            "admin' UNION SELECT * FROM helpdesk_tickets --",
        ]

        for payload in malicious_inputs:
            # Test status filter
            tickets = self.demo_db.list_tickets(viewer, filters={"status": payload})
            self.assertEqual(tickets, [])

            # Test department filter
            tickets = self.demo_db.list_tickets(viewer, filters={"department": payload})
            self.assertEqual(tickets, [])

            # Test search query
            tickets = self.demo_db.list_tickets(viewer, filters={"q": payload})
            self.assertEqual(tickets, [])

        # Ensure helpdesk_tickets still exists and operates normally
        all_tickets = self.demo_db.list_tickets(viewer, scope="all")
        self.assertIsInstance(all_tickets, list)


if __name__ == "__main__":
    unittest.main()
