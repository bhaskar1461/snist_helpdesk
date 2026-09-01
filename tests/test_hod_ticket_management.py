import unittest
from werkzeug.security import generate_password_hash
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE


class TestHodTicketManagement(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        # Seed a second CA in CSE (A.Lavanya, id 9)
        GLOBAL_DB_STATE.tables["helpdesk_users"].append({
            "id": 9,
            "name": "A.Lavanya CA",
            "email": "lavanya.ca@gmail.com",
            "password": generate_password_hash("123"),
            "role": "CA",
            "department": "CSE",
            "phone": "9849123456",
            "org_id": "2000",
            "is_active": 1,
        })

        # Seed test tickets for CA 4 (Chandini) in CSE
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [
            {
                "id": 201,
                "title": "WiFi not connecting in Lab 1",
                "description": "Signal drops frequently",
                "category_id": 1, # Internet (CSE)
                "created_by": 7,  # Demo Faculty (CSE)
                "assigned_to": 4, # Chandini (CA)
                "status": "PENDING",
                "org_id": "2000",
                "location_id": 1,
            },
            {
                "id": 202,
                "title": "Switch port faulty",
                "description": "Ethernet port 12 dead",
                "category_id": 1, # Internet (CSE)
                "created_by": 7,
                "assigned_to": 4, # Chandini (CA)
                "status": "IN_PROGRESS",
                "org_id": "2000",
                "location_id": 1,
            },
            {
                "id": 203,
                "title": "Slow internet in Room 5201",
                "description": "High latency",
                "category_id": 1, # Internet (CSE)
                "created_by": 7,
                "assigned_to": 4, # Chandini (CA)
                "status": "ON_HOLD",
                "org_id": "2000",
                "location_id": 1,
            },
            {
                "id": 204,
                "title": "DHCP lease issue",
                "description": "IP conflict",
                "category_id": 1, # Internet (CSE)
                "created_by": 7,
                "assigned_to": 4, # Chandini (CA)
                "status": "PENDING",
                "org_id": "2000",
                "location_id": 1,
            },
        ]

    def test_hod_sidebar_link_and_page_access(self):
        # 1. Login as HOD (Dr. Kavya, hod@gmail.com, CSE)
        self.login_as("hod@gmail.com")

        # 2. Access HOD Ticket Management
        res = self.client.get("/hod/ticket-management")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Selective Ticket Reassignment", res.data)
        self.assertIn(b"Ticket Management", res.data)
        self.assertIn(b"Transfer Selected", res.data)

    def test_selective_ticket_reassignment(self):
        # Login as HOD (Dr. Kavya)
        self.login_as("hod@gmail.com")

        # Selectively reassign tickets 201 and 203 from CA 4 (Chandini) to CA 9 (A.Lavanya)
        res = self.client.post("/hod/ticket-management", data={
            "action": "reassign_tickets",
            "source_ca_id": 4,
            "target_ca_id": 9,
            "selected_tickets": [201, 203],
            "remarks": "Chandini on leave; transferring urgent tickets to Lavanya."
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Successfully transferred 2 ticket(s)", res.data)

        # Verify in DB: Tickets 201 & 203 are reassigned to CA 9
        t201 = next(t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["id"] == 201)
        t203 = next(t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["id"] == 203)
        self.assertEqual(t201["assigned_to"], 9)
        self.assertEqual(t203["assigned_to"], 9)

        # Verify in DB: Non-selected tickets 202 & 204 REMAIN with CA 4 (Chandini)
        t202 = next(t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["id"] == 202)
        t204 = next(t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["id"] == 204)
        self.assertEqual(t202["assigned_to"], 4)
        self.assertEqual(t204["assigned_to"], 4)

        # Verify activity log was recorded
        activities = [a for a in GLOBAL_DB_STATE.tables["helpdesk_ticket_activity"] if a["ticket_id"] in [201, 203]]
        self.assertTrue(len(activities) >= 2)
        self.assertIn("Chandini on leave", activities[-1]["remarks"])

    def test_unauthorized_roles_blocked(self):
        # 1. Faculty cannot access
        self.login_as("faculty@gmail.com")
        res_faculty = self.client.get("/hod/ticket-management", follow_redirects=False)
        self.assertIn(res_faculty.status_code, [302, 403])

        # 2. Assignee / CA cannot access
        self.login_as("ca@gmail.com")
        res_ca = self.client.get("/hod/ticket-management", follow_redirects=False)
        self.assertIn(res_ca.status_code, [302, 403])

    def test_cross_department_reassignment_rejected(self):
        # Login as HOD of CSE (Dr. Kavya)
        self.login_as("hod@gmail.com")

        # Create a Facilities ticket (Category 3 is Plumbing, Facilities) assigned to Sravan CA (id 5, Facilities)
        GLOBAL_DB_STATE.tables["helpdesk_tickets"].append({
            "id": 205,
            "title": "Pipe leakage in Block B",
            "description": "Ground floor washroom",
            "category_id": 3, # Plumbing (Facilities)
            "created_by": 7,
            "assigned_to": 5, # Sravan (Facilities CA)
            "status": "PENDING",
            "org_id": "2000",
            "location_id": 1,
        })

        # Try to reassign Facilities ticket as CSE HOD
        res = self.client.post("/hod/ticket-management", data={
            "action": "reassign_tickets",
            "source_ca_id": 5,
            "target_ca_id": 4,
            "selected_tickets": [205],
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Reassignment failed", res.data)

        # Verify ticket was NOT reassigned
        t205 = next(t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["id"] == 205)
        self.assertEqual(t205["assigned_to"], 5)

    def test_invalid_ca_reassignment_rejected(self):
        self.login_as("hod@gmail.com")

        # Source CA == Target CA
        res = self.client.post("/hod/ticket-management", data={
            "action": "reassign_tickets",
            "source_ca_id": 4,
            "target_ca_id": 4,
            "selected_tickets": [201],
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"Reassignment failed", res.data)
