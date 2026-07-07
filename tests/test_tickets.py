import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
import io

class TestTickets(HelpdeskTestCase):
    def test_create_ticket_page_renders(self):
        self.login_as("faculty@gmail.com")
        response = self.client.get("/tickets/create")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Create Ticket", response.data)
        self.assertIn(b"Description", response.data)

    def test_create_ticket_validation_failures(self):
        self.login_as("faculty@gmail.com")
        
        # Missing description (should fail validation)
        response2 = self.client.post("/tickets/create", data={
            "title": "WiFi issue",
            "category_id": "1",
            "location_id": "1"
        }, follow_redirects=True)
        self.assertIn(b"required", response2.data.lower())

    def test_create_ticket_success_and_auto_assignment(self):
        # Login as CSE Faculty
        self.login_as("faculty@gmail.com")
        
        response = self.client.post("/tickets/create", data={
            "title": "WiFi is down",
            "description": "It has been down since morning",
            "category_id": "1",
            "location_id": "1",
            "problem_type_id": "1"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ticket created and auto-assigned", response.data)
        
        # Verify database has the ticket
        created_tickets = [t for t in GLOBAL_DB_STATE.tables["demo_tickets"] if t["created_by"] == 7]
        self.assertEqual(len(created_tickets), 1)
        self.assertEqual(created_tickets[0]["status"], "PENDING")
        self.assertEqual(created_tickets[0]["assigned_to"], 4) # Fallback to default CA

    def test_create_ticket_custom_problem_type(self):
        self.login_as("faculty@gmail.com")
        
        # Create ticket with problem_type_id = "other" and other_problem = "Strange Beeping"
        response = self.client.post("/tickets/create", data={
            "title": "Projector noise",
            "description": "It makes a high pitched beeping sound",
            "category_id": "2",
            "location_id": "2",
            "problem_type_id": "other",
            "other_problem": "Strange Beeping"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        # Verify custom problem type was added to demo_problem_types table
        new_prob = next((p for p in GLOBAL_DB_STATE.tables["demo_problem_types"] if p["problem_name"] == "Strange Beeping"), None)
        self.assertIsNotNone(new_prob)
        self.assertEqual(new_prob["category_id"], 2)

        # Ticket created references the new problem type ID
        latest_ticket = GLOBAL_DB_STATE.tables["demo_tickets"][-1]
        self.assertEqual(latest_ticket["problem_type_id"], new_prob["id"])

    def test_ticket_status_transitions_happy_path(self):
        # Seed a ticket in PENDING state
        GLOBAL_DB_STATE.tables["demo_tickets"] = [{
            "id": 10,
            "title": "Broken light",
            "description": "Classroom 101",
            "category_id": 4, # Electrical
            "created_by": 7, # Faculty
            "assigned_to": 6, # Bhaskar CA
            "status": "PENDING",
            "org_id": "2000",
            "location_id": 1
        }]

        # Login as assigned CA
        self.login_as("bhaskar.ca@gmail.com")

        # 1. PENDING -> IN_PROGRESS
        res1 = self.client.post("/authority/update-status/10", data={
            "status": "IN_PROGRESS",
            "remarks": "I am on my way to room 101"
        }, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["demo_tickets"][0]["status"], "IN_PROGRESS")

        # 2. IN_PROGRESS -> ON_HOLD
        res2 = self.client.post("/authority/update-status/10", data={
            "status": "ON_HOLD",
            "remarks": "Waiting for a replacement bulb"
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["demo_tickets"][0]["status"], "ON_HOLD")

        # 3. ON_HOLD -> IN_PROGRESS
        res3 = self.client.post("/authority/update-status/10", data={
            "status": "IN_PROGRESS",
            "remarks": "Bulb arrived, replacing it now"
        }, follow_redirects=True)
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["demo_tickets"][0]["status"], "IN_PROGRESS")

        # 4. IN_PROGRESS -> RESOLVED
        res4 = self.client.post("/authority/update-status/10", data={
            "status": "RESOLVED",
            "remarks": "Bulb replaced, tested and working"
        }, follow_redirects=True)
        self.assertEqual(res4.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["demo_tickets"][0]["status"], "RESOLVED")

        # 5. RESOLVED -> REOPENED (Needs to be done by Faculty who created it)
        self.logout()
        self.login_as("faculty@gmail.com")
        res5 = self.client.post("/tickets/10/reopen", data={
            "remarks": "Light is flickering, please fix properly"
        }, follow_redirects=True)
        self.assertEqual(res5.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["demo_tickets"][0]["status"], "REOPENED")

    def test_ticket_status_transitions_invalid_paths(self):
        GLOBAL_DB_STATE.tables["demo_tickets"] = [{
            "id": 20,
            "title": "Broken light",
            "description": "Classroom 101",
            "category_id": 4,
            "created_by": 7,
            "assigned_to": 6,
            "status": "PENDING",
            "org_id": "2000",
            "location_id": 1
        }]

        # Login as assigned CA
        self.login_as("bhaskar.ca@gmail.com")

        # Case A: PENDING -> RESOLVED directly (Invalid - must accept first)
        resA = self.client.post("/authority/update-status/20", data={
            "status": "RESOLVED",
            "remarks": "Done directly"
        }, follow_redirects=True)
        self.assertIn(b"Invalid status transition", resA.data)
        self.assertEqual(GLOBAL_DB_STATE.tables["demo_tickets"][0]["status"], "PENDING")

        # Case B: PENDING -> REOPENED directly (Invalid)
        resB = self.client.post("/authority/update-status/20", data={
            "status": "REOPENED",
            "remarks": "Reopen PENDING"
        }, follow_redirects=True)
        self.assertIn(b"Invalid status transition", resB.data)

        # Case C: Access restriction - HOD trying to update status of ticket assigned to CA
        # HOD CSE (Dr. Kavya) trying to update status of Maintenance ticket
        self.logout()
        self.login_as("hod@gmail.com")
        resC = self.client.post("/authority/update-status/20", data={
            "status": "IN_PROGRESS",
            "remarks": "HOD accepts"
        }, follow_redirects=True)
        # HOD cannot update CA ticket status directly
        self.assertIn(b"You do not have access to that page", resC.data)
        self.assertEqual(GLOBAL_DB_STATE.tables["demo_tickets"][0]["status"], "PENDING")

        # Case D: Faculty trying to update status directly
        self.logout()
        self.login_as("faculty@gmail.com")
        resD = self.client.post("/authority/update-status/20", data={
            "status": "IN_PROGRESS",
            "remarks": "Faculty accepts"
        }, follow_redirects=True)
        self.assertIn(b"You do not have access to that page", resD.data)
