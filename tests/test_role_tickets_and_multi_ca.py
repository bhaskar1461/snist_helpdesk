import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
import db_services

class TestRoleTicketsAndMultiCA(HelpdeskTestCase):
    def test_ca_status_update_permissions(self):
        # 1. Login as CA / ASSIGNEE user (Chandini, ca@gmail.com, id=4)
        self.login_as("ca@gmail.com")
        
        # Look up ticket 159 (assigned to Chandini)
        ticket = next((t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["id"] == 159), None)
        if not ticket:
            # Create a test ticket assigned to Chandini
            ticket = {
                "id": 999,
                "title": "Network Outage",
                "description": "Network is down in Block I",
                "category_id": 1,
                "created_by": 1, # Demo User
                "assigned_to": 4, # Chandini
                "status": "PENDING",
                "org_id": "2000",
                "location_id": 1,
            }
            GLOBAL_DB_STATE.tables["helpdesk_tickets"].append(ticket)

        # GET ticket detail - should render status update action form (can_update=True)
        res = self.client.get(f"/tickets/{ticket['id']}")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Update Ticket Status", res.data)

        # POST update status from PENDING -> IN_PROGRESS
        res_update = self.client.post(f"/authority/update-status/{ticket['id']}", data={
            "status": "IN_PROGRESS",
            "remarks": "Investigating network switch",
            "time_taken": "15 mins"
        }, follow_redirects=True)
        self.assertEqual(res_update.status_code, 200)
        self.assertIn(b"Ticket updated successfully", res_update.data)

        updated_ticket = next(t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["id"] == ticket["id"])
        self.assertEqual(updated_ticket["status"], "IN_PROGRESS")

    def test_multi_ca_assignment_and_routing(self):
        from app import get_demo_db
        self.login_as("admin@gmail.com")
        demo_db = get_demo_db()

        # Category 1: Assign CA 4 (Chandini) to Block-I and CA 7 (Faculty promoted to CA) to Block-II
        demo_db.assign_ca_to_category_blocks(1, 4, ["Block-I"])
        demo_db.assign_ca_to_category_blocks(1, 7, ["Block-II"])

        # Fetch category assignees
        assignees = demo_db.get_category_assignees(1)
        ca_ids = [a["ca_id"] for a in assignees]
        self.assertIn(4, ca_ids)
        self.assertIn(7, ca_ids)

        # Verify auto-routing resolves to CA 4 for Block-I
        resolved_ca_block1 = demo_db.resolve_assigned_ca(1, "Block-I")
        self.assertEqual(resolved_ca_block1, 4)

        # Verify auto-routing resolves to CA 7 for Block-II
        resolved_ca_block2 = demo_db.resolve_assigned_ca(1, "Block-II")
        self.assertEqual(resolved_ca_block2, 7)

    def test_faculty_restricted_from_all_tickets(self):
        # Regular faculty login
        self.login_as("faculty@gmail.com")

        # Faculty can access My Tickets
        res_my = self.client.get("/user/my-tickets")
        self.assertEqual(res_my.status_code, 200)

        # Faculty is strictly forbidden from accessing super-admin or admin all-tickets routes
        res_admin_all = self.client.get("/admin/all-tickets", follow_redirects=False)
        self.assertIn(res_admin_all.status_code, [302, 403])

    def test_ca_assigned_tickets_scoped_to_assignee(self):
        # 1. Seed two tickets: one assigned to Chandini (id=4), one assigned to Bhaskar CA (id=6)
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [
            {
                "id": 101,
                "title": "Chandini Ticket",
                "description": "Assigned to Chandini",
                "category_id": 1,
                "created_by": 7,
                "assigned_to": 4, # Chandini
                "status": "PENDING",
                "org_id": "2000",
                "location_id": 1,
            },
            {
                "id": 102,
                "title": "Other CA Ticket",
                "description": "Assigned to Bhaskar CA",
                "category_id": 1,
                "created_by": 7,
                "assigned_to": 6, # Bhaskar CA
                "status": "PENDING",
                "org_id": "2000",
                "location_id": 1,
            }
        ]

        # 2. Login as Chandini
        self.login_as("ca@gmail.com")

        # 3. Access Assigned Tickets repository
        res = self.client.get("/authority/assigned-tickets")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Chandini Ticket", res.data)
        self.assertNotIn(b"Other CA Ticket", res.data)

