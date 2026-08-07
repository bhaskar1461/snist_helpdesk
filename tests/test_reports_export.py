import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
import csv
import io

class TestReportsExport(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        # Seed tickets for export testing
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [
            {
                "id": 1,
                "title": "=1+2 (Formula Injection Test)", # Formula injection character
                "description": "Slow speed WiFi",
                "category_id": 1,
                "created_by": 7,
                "assigned_to": 4,
                "status": "PENDING",
                "org_id": "2000",
                "location_id": 1,
                "created_at": "2026-07-07 10:00:00",
                "updated_at": "2026-07-07 10:00:00"
            },
            {
                "id": 2,
                "title": "Normal Ticket",
                "description": "Lamps broken",
                "category_id": 4,
                "created_by": 7,
                "assigned_to": 6,
                "status": "RESOLVED",
                "org_id": "2000",
                "location_id": 2,
                "created_at": "2026-07-07 11:00:00",
                "updated_at": "2026-07-07 11:05:00"
            }
        ]

    def test_csv_export_access_and_contents(self):
        # 1. Anonymous download is blocked
        response_anon = self.client.get("/tickets/export/all.csv")
        self.assertEqual(response_anon.status_code, 302)

        # 2. Login as Admin
        self.login_as("admin@gmail.com")

        # 3. Request CSV export
        response_csv = self.client.get("/tickets/export/all.csv")
        self.assertEqual(response_csv.status_code, 200)
        self.assertEqual(response_csv.mimetype, "text/csv")
        self.assertIn("attachment; filename=", response_csv.headers.get("Content-Disposition", ""))

        # Parse CSV content
        csv_data = response_csv.data.decode("utf-8")
        reader = csv.reader(io.StringIO(csv_data))
        rows = list(reader)

        # Verify headers
        self.assertTrue(len(rows) >= 3)
        headers = rows[0]
        self.assertIn("Ticket ID", headers)
        self.assertIn("Title", headers)
        self.assertIn("Description", headers)
        self.assertIn("Category", headers)
        self.assertIn("Status", headers)

        # Verify formula injection escaping
        # The title '=1+2 (Formula Injection Test)' starts with '=' and should be escaped with a leading "'"
        escaped_title = rows[1][1] # Row 1, Column 1 (Title)
        self.assertEqual(escaped_title, "'=1+2 (Formula Injection Test)")

        # Verify second row content
        normal_title = rows[2][1]
        self.assertEqual(normal_title, "Normal Ticket")

    def test_excel_export_headers(self):
        self.login_as("admin@gmail.com")
        response_xls = self.client.get("/tickets/export/all.xls")
        self.assertEqual(response_xls.status_code, 200)
        self.assertEqual(response_xls.mimetype, "application/vnd.ms-excel")
        self.assertIn("attachment; filename=", response_xls.headers.get("Content-Disposition", ""))
        self.assertIn(b"<table>", response_xls.data)
        self.assertIn(b"<thead>", response_xls.data)
        self.assertIn(b"Ticket ID", response_xls.data)

    def test_report_filters_and_queries(self):
        self.login_as("admin@gmail.com")
        
        # Test filters: by status PENDING
        response_pending = self.client.get("/super-admin/all-tickets?status=PENDING")
        self.assertEqual(response_pending.status_code, 200)
        self.assertIn(b"Formula Injection", response_pending.data)
        
        # Test filters: by department Facilities
        # (Facilities department categories will not match the mock ticket categories)
        response_dept = self.client.get("/super-admin/all-tickets?department=Facilities")
        self.assertEqual(response_dept.status_code, 200)

    def test_audit_logging_system(self):
        # Trigger an action that creates an audit event
        self.login_as("admin@gmail.com")

        # Create a new user (generates audit event)
        self.client.post("/user-management", data={
            "name": "Audit Test User",
            "email": "audit_test@gmail.com",
            "password": "123",
            "role": "FACULTY",
            "department": "CSE"
        })

        # Verify audit event table contains the log entry
        audit_events = GLOBAL_DB_STATE.tables["helpdesk_audit_events"]
        self.assertTrue(len(audit_events) >= 1)
        self.assertEqual(audit_events[-1]["org_id"], "2000")
        
        # Check details contain user email or action
        self.assertIn("audit_test@gmail.com", audit_events[-1]["details"])
