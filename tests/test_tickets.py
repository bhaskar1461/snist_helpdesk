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
            "location_id": "1"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Ticket created and auto-assigned", response.data)
        
        # Verify database has the ticket
        created_tickets = [t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["created_by"] == 7]
        self.assertEqual(len(created_tickets), 1)
        self.assertEqual(created_tickets[0]["status"], "PENDING")
        self.assertEqual(created_tickets[0]["assigned_to"], 4) # Fallback to default CA

    def test_create_ticket_readonly_department_display(self):
        self.login_as("faculty@gmail.com")
        # Keep only CSE categories so available_depts has length 1
        GLOBAL_DB_STATE.tables["helpdesk_categories"] = [
            c for c in GLOBAL_DB_STATE.tables["helpdesk_categories"] if c.get("department") == "CSE"
        ]
        response = self.client.get("/tickets/create")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'id="dept-select"', response.data)
        self.assertIn(b'readonly', response.data)

    def test_create_ticket_cross_department_rejected(self):
        # Login as CSE Faculty (department: CSE)
        self.login_as("faculty@gmail.com")

        # Category 999 is non-existent/invalid
        response = self.client.post("/tickets/create", data={
            "title": "Fix plumbing",
            "description": "Pipe leaking in bathroom",
            "category_id": "999",
            "location_id": "1"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"does not exist", response.data.lower())

        # Verify no ticket was created
        created_tickets = [t for t in GLOBAL_DB_STATE.tables["helpdesk_tickets"] if t["created_by"] == 7 and t.get("category_id") == 999]
        self.assertEqual(len(created_tickets), 0)

    def test_create_ticket_inactive_category_rejected(self):
        self.login_as("faculty@gmail.com")

        # Category 2 is inactive in GLOBAL_DB_STATE
        cat2 = next((c for c in GLOBAL_DB_STATE.tables["helpdesk_categories"] if c["id"] == 2), None)
        if cat2:
            cat2["is_active"] = 0

        response = self.client.post("/tickets/create", data={
            "title": "Inactive category test",
            "description": "Testing submitting inactive category",
            "category_id": "2",
            "department": "CSE",
            "location_id": "1"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"inactive", response.data.lower())

    def test_create_ticket_mismatched_department_category_rejected(self):
        self.login_as("faculty@gmail.com")

        # Category 3 is Plumbing (Facilities). Submit with department = CSE
        response = self.client.post("/tickets/create", data={
            "title": "Mismatched dept test",
            "description": "Category belongs to Facilities but department submitted is CSE",
            "category_id": "3",
            "department": "CSE",
            "location_id": "1"
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"does not belong to the selected department", response.data.lower())

    def test_ticket_status_transitions_happy_path(self):
        # Seed a ticket in PENDING state
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [{
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
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "IN_PROGRESS")

        # 2. IN_PROGRESS -> ON_HOLD
        res2 = self.client.post("/authority/update-status/10", data={
            "status": "ON_HOLD",
            "remarks": "Waiting for a replacement bulb"
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "ON_HOLD")

        # 3. ON_HOLD -> IN_PROGRESS
        res3 = self.client.post("/authority/update-status/10", data={
            "status": "IN_PROGRESS",
            "remarks": "Bulb arrived, replacing it now"
        }, follow_redirects=True)
        self.assertEqual(res3.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "IN_PROGRESS")

        # 4. IN_PROGRESS -> RESOLVED
        res4 = self.client.post("/authority/update-status/10", data={
            "status": "RESOLVED",
            "remarks": "Bulb replaced, tested and working"
        }, follow_redirects=True)
        self.assertEqual(res4.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "RESOLVED")

        # 5. RESOLVED -> REOPENED (Needs to be done by Faculty who created it)
        self.logout()
        self.login_as("faculty@gmail.com")
        res5 = self.client.post("/tickets/10/reopen", data={
            "remarks": "Light is flickering, please fix properly"
        }, follow_redirects=True)
        self.assertEqual(res5.status_code, 200)
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "REOPENED")

    def test_ticket_status_transitions_invalid_paths(self):
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [{
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
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "PENDING")

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
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "PENDING")

        # Case D: Faculty trying to update status directly
        self.logout()
        self.login_as("faculty@gmail.com")
        resD = self.client.post("/authority/update-status/20", data={
            "status": "IN_PROGRESS",
            "remarks": "Faculty accepts"
        }, follow_redirects=True)
        self.assertIn(b"You do not have access to that page", resD.data)

    def test_ticket_upload_validation(self):
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [{
            "id": 30,
            "title": "Broken light",
            "description": "Classroom 101",
            "category_id": 4,
            "created_by": 7,
            "assigned_to": 6,
            "status": "IN_PROGRESS",
            "org_id": "2000",
            "location_id": 1
        }]

        # Login as assigned CA
        self.login_as("bhaskar.ca@gmail.com")

        # Case 1: Upload a valid PNG file signature
        valid_png = (io.BytesIO(b'\x89PNG\r\n\x1a\nimage-data'), 'test.png')
        res = self.client.post("/authority/update-status/30", data={
            "status": "RESOLVED",
            "remarks": "Resolved with attachment",
            "attachment": valid_png
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn(b"Ticket updated successfully", res.data)
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "RESOLVED")

        # Reset status back to IN_PROGRESS
        GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"] = "IN_PROGRESS"

        # Case 2: Upload a malicious file with PNG extension but MZ signature (malicious executable)
        malicious_exe = (io.BytesIO(b'MZ\x90\x00\x03\x00\x00\x00malicious-code'), 'test.png')
        res2 = self.client.post("/authority/update-status/30", data={
            "status": "RESOLVED",
            "remarks": "Resolved with malicious attachment",
            "attachment": malicious_exe
        }, content_type='multipart/form-data', follow_redirects=True)
        self.assertIn(b"File type not allowed", res2.data)
        # Should not transition status
        self.assertEqual(GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"], "IN_PROGRESS")

    def test_ticket_sla_escalation(self):
        from datetime import datetime, timedelta
        import db_services
        # 1. Seed an open ticket created 2 days ago
        old_time = datetime.now() - timedelta(days=2)
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [{
            "id": 40,
            "title": "Old broken light",
            "description": "Classroom 101",
            "category_id": 4,
            "created_by": 7,
            "assigned_to": 6,
            "status": "PENDING",
            "org_id": "2000",
            "location_id": 1,
            "created_at": old_time
        }]

        db_service = db_services.DemoDbService(None)
        
        # Retrieve the ticket
        ticket = db_service.get_ticket(40)
        self.assertTrue(ticket.get("is_escalated"), "Expected open ticket older than 24h to be escalated")

        # 2. Change status to RESOLVED and verify it is no longer escalated
        GLOBAL_DB_STATE.tables["helpdesk_tickets"][0]["status"] = "RESOLVED"
        ticket_resolved = db_service.get_ticket(40)
        self.assertFalse(ticket_resolved.get("is_escalated"), "Expected resolved ticket to not be escalated")
