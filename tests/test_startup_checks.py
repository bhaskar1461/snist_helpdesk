"""Tests for Phase 4: Startup Fail-Fast, Config Validation & Health Endpoints."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from app import create_app
from app.config_validator import validate_config
from app.startup_checks import check_database
from db_services import DemoDbService, DbConfig


class TestStartupChecks(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        GLOBAL_DB_STATE.reset()

    def test_missing_mysql_database_errors_and_create_app_exits(self):
        """1. Missing MYSQL_DATABASE causes validate_config to return ERROR and create_app to exit."""
        env = {
            "SECRET_KEY": "0123456789abcdef0123456789abcdef",
            "MYSQL_HOST": "localhost",
            "MYSQL_USER": "root",
            "MYSQL_PASSWORD": "secretpassword",
            "FLASK_ENV": "production",
            # MYSQL_DATABASE is missing
        }
        issues = validate_config(env)
        db_errors = [i for i in issues if i["level"] == "ERROR" and "MYSQL_DATABASE" in i["message"]]
        self.assertTrue(len(db_errors) > 0, "Expected missing MYSQL_DATABASE to be flagged as ERROR.")

        # Test that create_app raises SystemExit(1) when MYSQL_DATABASE is missing and checks are active
        with patch.dict(os.environ, {
            "MYSQL_DATABASE": "",
            "SKIP_STARTUP_CHECKS": "0",
            "TESTING": "false",
            "FORCE_STARTUP_CHECKS": "1",
        }):
            with self.assertRaises(SystemExit) as cm:
                create_app(testing=False)
            self.assertEqual(cm.exception.code, 1)

    def test_weak_secret_key_production_vs_development(self):
        """2. Weak SECRET_KEY with FLASK_ENV=production causes ERROR; with development causes WARNING only."""
        # Production mode with weak key
        env_prod = {
            "SECRET_KEY": "dev",
            "FLASK_ENV": "production",
            "MYSQL_HOST": "localhost",
            "MYSQL_USER": "demo",
            "MYSQL_PASSWORD": "secretpassword",
            "MYSQL_DATABASE": "helpdesk",
        }
        issues_prod = validate_config(env_prod)
        prod_errors = [i for i in issues_prod if i["level"] == "ERROR" and i["check"] == "secret_key_strength"]
        self.assertTrue(len(prod_errors) > 0, "Expected weak key in production to be an ERROR.")

        # Development mode with weak key
        env_dev = {
            "SECRET_KEY": "dev",
            "FLASK_ENV": "development",
            "MYSQL_HOST": "localhost",
            "MYSQL_USER": "demo",
            "MYSQL_PASSWORD": "secretpassword",
            "MYSQL_DATABASE": "helpdesk",
        }
        issues_dev = validate_config(env_dev)
        dev_errors = [i for i in issues_dev if i["level"] == "ERROR" and i["check"] == "secret_key_strength"]
        dev_warnings = [i for i in issues_dev if i["level"] == "WARNING" and i["check"] == "secret_key_strength"]
        self.assertEqual(len(dev_errors), 0, "Weak key in development must NOT be an ERROR.")
        self.assertTrue(len(dev_warnings) > 0, "Weak key in development must produce a WARNING.")

    def test_missing_core_table_reports_fail(self):
        """3. Missing core table in mock DB causes check_database to report FAIL naming the table."""
        service = DemoDbService(DbConfig("localhost", 3306, "demo", "pass", "helpdesk"))

        # Remove a required table from MockDbState
        self.assertIn("helpdesk_ticket_notes", GLOBAL_DB_STATE.tables)
        del GLOBAL_DB_STATE.tables["helpdesk_ticket_notes"]

        report = check_database(db_service=service)
        self.assertFalse(report["healthy"])
        self.assertTrue(report["has_failure"])

        schema_fail = [
            c for c in report["checks"]
            if c["check"] == "schema_presence" and c["status"] == "FAIL"
        ]
        self.assertTrue(len(schema_fail) > 0)
        self.assertIn("helpdesk_ticket_notes", schema_fail[0]["detail"])

    def test_empty_ca_assignments_returns_warn(self):
        """4. Empty ca_assignments causes check_database to return WARN with the seeding hint."""
        service = DemoDbService(DbConfig("localhost", 3306, "demo", "pass", "helpdesk"))
        GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] = []

        report = check_database(db_service=service)
        routing_warns = [
            c for c in report["checks"]
            if c["check"] == "routing_sanity" and c["status"] == "WARN"
        ]
        self.assertTrue(len(routing_warns) > 0)
        self.assertIn("seed_production.py", routing_warns[0]["fix"])

    def test_skip_startup_checks_allows_boot_with_broken_state(self):
        """5. SKIP_STARTUP_CHECKS=1 allows create_app to boot in test harness mode even with weak keys."""
        with patch.dict(os.environ, {
            "SKIP_STARTUP_CHECKS": "1",
            "SECRET_KEY": "short",
            "FLASK_ENV": "production",
            "TESTING": "false",
        }):
            app = create_app(testing=False)
            self.assertIsNotNone(app)

    def test_health_endpoints(self):
        """6. /health returns 200 without DB; /health/deep handles auth, healthy 200, and failure 503."""
        # 6a: /health liveness does not touch DB and returns 200
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json["status"], "ok")
        self.assertIn("uptime_seconds", res.json)

        # 6b: /health/deep without token returns 403
        res_no_token = self.client.get("/health/deep")
        self.assertEqual(res_no_token.status_code, 403)

        # 6c: /health/deep with incorrect token returns 403
        res_bad_token = self.client.get("/health/deep", headers={"X-Health-Token": "wrong-secret"})
        self.assertEqual(res_bad_token.status_code, 403)

        # 6d: /health/deep with valid token on healthy DB returns 200
        res_ok = self.client.get("/health/deep", headers={"X-Health-Token": "snist-health-secret"})
        self.assertEqual(res_ok.status_code, 200)
        self.assertEqual(res_ok.json["status"], "healthy")
        self.assertIn("checks", res_ok.json)
        self.assertIn("db_latency_ms", res_ok.json)

        # 6e: /health/deep on broken DB returns 503
        del GLOBAL_DB_STATE.tables["helpdesk_tickets"]
        res_fail = self.client.get("/health/deep", headers={"X-Health-Token": "snist-health-secret"})
        self.assertEqual(res_fail.status_code, 503)
        self.assertEqual(res_fail.json["status"], "unhealthy")
        self.assertTrue(res_fail.json["has_failure"])


if __name__ == "__main__":
    unittest.main()
