import os
import unittest
from unittest.mock import MagicMock
import pymysql
from db_services import BaseMySQLService, DbConfig


class TestInstPrefix(unittest.TestCase):
    def setUp(self):
        self.orig_env = os.environ.get("MYSQL_INSTITUTIONAL_DATABASE")

    def tearDown(self):
        if self.orig_env is not None:
            os.environ["MYSQL_INSTITUTIONAL_DATABASE"] = self.orig_env
        else:
            os.environ.pop("MYSQL_INSTITUTIONAL_DATABASE", None)

    def test_inst_prefix_same_db(self):
        """1. Test inst_prefix returns '' when institutional DB == current DB."""
        os.environ["MYSQL_INSTITUTIONAL_DATABASE"] = "helpdesk"
        cfg = DbConfig(host="localhost", port=3306, user="demo", password="123", database="helpdesk")
        service = BaseMySQLService(cfg)
        self.assertEqual(service.inst_prefix, "")

    def test_inst_prefix_empty_env(self):
        """2. Test inst_prefix returns '' when env var is empty or unset."""
        os.environ["MYSQL_INSTITUTIONAL_DATABASE"] = ""
        cfg = DbConfig(host="localhost", port=3306, user="demo", password="123", database="helpdesk")
        service = BaseMySQLService(cfg)
        self.assertEqual(service.inst_prefix, "")

        os.environ.pop("MYSQL_INSTITUTIONAL_DATABASE", None)
        service2 = BaseMySQLService(cfg)
        self.assertEqual(service2.inst_prefix, "")

    def test_inst_prefix_different_db(self):
        """3. Test inst_prefix returns '`other_db`.' when configured for a different DB."""
        os.environ["MYSQL_INSTITUTIONAL_DATABASE"] = "other_db"
        cfg = DbConfig(host="localhost", port=3306, user="demo", password="123", database="helpdesk")
        service = BaseMySQLService(cfg)
        service._force_prefix = True
        self.assertEqual(service.inst_prefix, "`other_db`.")

    def test_permission_probe_fallback_and_caching(self):
        """4. Test that permission probe failure (1142) triggers fallback to '' and prevents repeated probing."""
        os.environ["MYSQL_INSTITUTIONAL_DATABASE"] = "inaccessible_db"
        cfg = DbConfig(host="localhost", port=3306, user="demo", password="123", database="helpdesk")
        service = BaseMySQLService(cfg)
        service._force_prefix = True

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.execute.side_effect = pymysql.err.OperationalError(
            1142, "SELECT command denied to user 'demo' for table 'teacher_info'"
        )

        with self.assertLogs("db_services", level="CRITICAL") as log_ctx:
            success = service.probe_institutional_access(conn=mock_conn)

        self.assertFalse(success)
        self.assertTrue(service._inst_fallback)
        self.assertTrue(service._inst_probed)
        self.assertEqual(service.inst_prefix, "")
        self.assertTrue(any("inaccessible as user" in msg for msg in log_ctx.output))
        self.assertEqual(mock_cursor.execute.call_count, 1)

        # Second probe execution must NOT re-execute query due to caching
        success_cached = service.probe_institutional_access(conn=mock_conn)
        self.assertFalse(success_cached)
        self.assertEqual(mock_cursor.execute.call_count, 1)
        self.assertEqual(service.inst_prefix, "")
