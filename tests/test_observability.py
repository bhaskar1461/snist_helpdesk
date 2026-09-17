"""Tests for Milestone 3 & Phase 10 Observability, SLA Badging & Prometheus Metrics."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE


class TestObservabilityAndUX(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        GLOBAL_DB_STATE.reset()

    def test_prometheus_metrics_endpoints(self):
        """Verify GET /metrics and GET /health/metrics return 200 in valid Prometheus text format."""
        for endpoint in ("/metrics", "/health/metrics"):
            res = self.client.get(endpoint)
            self.assertEqual(res.status_code, 200, f"Expected 200 from {endpoint}")
            self.assertIn("text/plain", res.content_type)
            body = res.data.decode("utf-8")

            # Check core metric headers and definitions
            self.assertIn("# HELP snist_helpdesk_uptime_seconds", body)
            self.assertIn("# TYPE snist_helpdesk_uptime_seconds gauge", body)
            self.assertIn("snist_helpdesk_uptime_seconds", body)

            self.assertIn("# HELP snist_helpdesk_pool_in_use", body)
            self.assertIn("# TYPE snist_helpdesk_pool_in_use gauge", body)
            self.assertIn("snist_helpdesk_pool_in_use", body)

            self.assertIn("# HELP snist_helpdesk_pool_checkouts_total", body)
            self.assertIn("# TYPE snist_helpdesk_pool_checkouts_total counter", body)
            self.assertIn("snist_helpdesk_pool_checkouts_total", body)

            self.assertIn("# HELP snist_helpdesk_pool_checkout_latency_p50_ms", body)
            self.assertIn("snist_helpdesk_pool_checkout_latency_p50_ms", body)
            self.assertIn("snist_helpdesk_pool_checkout_latency_p95_ms", body)

    def test_ticket_status_metrics_exposition(self):
        """Verify ticket breakdown metrics are exposed in Prometheus scrape output."""
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        body = res.data.decode("utf-8")
        self.assertIn("snist_helpdesk_tickets_total", body)
        self.assertIn('snist_helpdesk_tickets_by_status{status="pending"}', body)
        self.assertIn('snist_helpdesk_tickets_by_status{status="resolved"}', body)

    def test_ticket_detail_attachment_preview_modal(self):
        """Verify ticket detail screen renders attachment modal and preview script."""
        # Seed ticket 1 for org 2000
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [{
            "id": 1,
            "title": "Projector not working",
            "description": "Projector HDMI cable broken in room 101",
            "category_id": 1,
            "status": "PENDING",
            "created_by": 7,
            "assigned_to": 4,
            "org_id": "2000",
            "location_id": 1,
            "created_at": now_str,
            "updated_at": now_str,
        }]

        self.login_as("admin@gmail.com")
        res = self.client.get("/tickets/1")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")

        # In-browser modal preview components
        self.assertIn('id="attachmentModal"', html)
        self.assertIn("previewAttachment", html)
        self.assertIn("closeAttachmentModal", html)
        self.assertIn("Call Assignee", html)  # Standardized terminology invariant

    def test_sla_overdue_badging_in_ticket_lists(self):
        """Verify overdue (>24h) tickets display SLA overdue indicator badges in ticket lists."""
        # Seed an overdue open ticket (>24h ago)
        old_time = (datetime.now() - timedelta(hours=36)).strftime("%Y-%m-%d %H:%M:%S")
        GLOBAL_DB_STATE.tables["helpdesk_tickets"] = [{
            "id": 99,
            "title": "Old Overdue Server Outage",
            "description": "Server room power trip",
            "category_id": 1,
            "status": "PENDING",
            "created_by": 7,
            "assigned_to": 4,
            "org_id": "2000",
            "location_id": 1,
            "created_at": old_time,
            "updated_at": old_time,
        }]

        # Check in Assignee Tickets queue
        self.login_as("ca@gmail.com")
        res = self.client.get("/authority/tickets")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("Overdue", html)
        self.assertIn("escalated-pill", html)

        # Check in Faculty My Tickets queue
        self.login_as("faculty@gmail.com")
        res_my = self.client.get("/user/my-tickets")
        self.assertEqual(res_my.status_code, 200)
        html_my = res_my.data.decode("utf-8")
        self.assertIn("escalated-pill", html_my)
        self.assertIn("Overdue", html_my)


if __name__ == "__main__":
    unittest.main()
