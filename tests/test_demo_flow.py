import os
import re
import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from app.demo_engine import DEMO_STATE_PATH
from app import create_app

class TestDemoFlow(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        GLOBAL_DB_STATE.seed_demo_enrichments()
        self.app.config["DEMO_MODE"] = True

    def tearDown(self):
        self.app.config["DEMO_MODE"] = False
        super().tearDown()
        if DEMO_STATE_PATH.exists():
            try:
                DEMO_STATE_PATH.unlink()
            except Exception:
                pass

    def test_demo_login_and_navigation(self):
        # 1. Login page loads with One-Click Demo Roles
        res = self.client.get('/login')
        self.assertEqual(res.status_code, 200)
        self.assertIn("One-Click Demo Roles", res.get_data(as_text=True))

        # 2. Login as Super Admin
        login_res = self.client.post('/login', data={
            'email': 'admin@gmail.com',
            'password': '123'
        }, follow_redirects=True)
        self.assertEqual(login_res.status_code, 200)
        self.assertIn("dashboard", login_res.request.path.lower())

        # 3. Super Admin All Tickets view
        tickets_res = self.client.get('/super-admin/all-tickets')
        self.assertEqual(tickets_res.status_code, 200)

        # 4. View Specific Ticket Details
        ticket_view = self.client.get('/tickets/1')
        self.assertEqual(ticket_view.status_code, 200)

        # 5. View Category Management
        cat_res = self.client.get('/management/category-management')
        self.assertEqual(cat_res.status_code, 200)
