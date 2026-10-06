import os
os.environ["TESTING"] = "true"

import unittest
from unittest.mock import patch, MagicMock
import re
import copy
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session

from app import create_app
from app.helpers import LOGIN_ATTEMPTS
import db_services

from app.demo_engine import MockDbState, MockCursor, MockConnection, GLOBAL_DB_STATE

flask_app = create_app(testing=True)

# Disable state file persistence during test suite executions
GLOBAL_DB_STATE.enable_persistence = False

class HelpdeskTestCase(unittest.TestCase):
    def setUp(self):
        # 1. Reset database state before each test
        GLOBAL_DB_STATE.reset()
        LOGIN_ATTEMPTS.clear()
        
        # 2. Patch database connection pools to use mock connections
        self.conn_patcher = patch.object(db_services.BaseMySQLService, "connection", return_value=MockConnection(GLOBAL_DB_STATE))
        self.mock_conn = self.conn_patcher.start()

        # 3. Configure the Flask test client
        self.app = flask_app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF token validation during testing
        self.app.config["SECRET_KEY"] = "test-secret"
        self.client = self.app.test_client()

        # Also patch notifications to avoid actual SMTP/SMS network calls
        self.sms_alloc_patcher = patch("sms_services.send_allocation_sms", return_value=(True, "Mock SMS success"))
        self.sms_close_patcher = patch("sms_services.send_closure_sms", return_value=(True, "Mock SMS success"))
        self.email_alloc_patcher = patch("email_services.send_allocation_email", return_value=True)
        self.email_close_patcher = patch("email_services.send_closure_email", return_value=True)

        self.mock_sms_alloc = self.sms_alloc_patcher.start()
        self.mock_sms_close = self.sms_close_patcher.start()
        self.mock_email_alloc = self.email_alloc_patcher.start()
        self.mock_email_close = self.email_close_patcher.start()

    def tearDown(self):
        self.conn_patcher.stop()
        self.sms_alloc_patcher.stop()
        self.sms_close_patcher.stop()
        self.email_alloc_patcher.stop()
        self.email_close_patcher.stop()

    def login_as(self, email, password="123", follow_redirects=False):
        """Helper to log in a user and set their session parameters."""
        response = self.client.post("/", data={"email": email, "password": password}, follow_redirects=follow_redirects)
        return response

    def logout(self):
        """Helper to clear current user sessions."""
        return self.client.get("/logout", follow_redirects=True)
