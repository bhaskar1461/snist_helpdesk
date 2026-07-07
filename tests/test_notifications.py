import unittest
from tests.test_base import HelpdeskTestCase
from sms_services import _normalize_phone, _build_whatsapp_allocation_payload, send_allocation_sms, send_closure_sms
from email_services import send_allocation_email, send_closure_email
from unittest.mock import patch

class TestNotifications(HelpdeskTestCase):
    def test_phone_normalization(self):
        # 1. 10 digit number should get 91 prefix
        self.assertEqual(_normalize_phone("9876543210"), "919876543210")
        
        # 2. Already prefixed 91 should remain same
        self.assertEqual(_normalize_phone("919876543210"), "919876543210")

        # 3. Spaces and formatting characters should be stripped
        self.assertEqual(_normalize_phone("+91-98765-43210"), "919876543210")
        self.assertEqual(_normalize_phone("987 654 3210"), "919876543210")

        # 4. Empty/invalid values should return None
        self.assertIsNone(_normalize_phone(None))
        self.assertIsNone(_normalize_phone(""))
        self.assertIsNone(_normalize_phone("abc"))

    def test_whatsapp_payload_builder(self):
        # Build payload
        payload = _build_whatsapp_allocation_payload(
            target_number="919876543210",
            ca_name="Chandini",
            ticket_id=42,
            category_name="Internet",
            priority="High",
            department="CSE"
        )
        
        # Verify fields in request payload (Unified Messaging Platform API format)
        message = payload["whatsapp"]["messages"][0]
        address = message["addresses"][0]
        self.assertEqual(address["from"], "919133386678")
        self.assertEqual(address["to"], "919876543210")
        
        # Verify templateinfo variables
        # Format: templateId~var1~var2~var3~var4~var5
        template_info = message["templateinfo"]
        self.assertTrue(template_info.startswith("1773697~"))
        self.assertIn("Chandini", template_info)
        self.assertIn("42", template_info)
        self.assertIn("Internet", template_info)
        self.assertIn("High", template_info)
        self.assertIn("CSE", template_info)

    @patch("sms_services.send_sms_async")
    @patch("sms_services.send_whatsapp_allocation_async")
    def test_send_allocation_sms(self, mock_wa, mock_sms):
        # Trigger sending
        send_allocation_sms(
            ca_name="Chandini",
            ca_phone="9876543210",
            ticket_id=123,
            category_name="Internet",
            department="CSE"
        )
        
        # Verify SMS was called with correct parameters
        mock_sms.assert_called_once()
        args_sms = mock_sms.call_args[0]
        self.assertEqual(args_sms[0], "9876543210")
        self.assertIn("Chandini", args_sms[1])
        self.assertIn("123", args_sms[1])
        
        # Verify WhatsApp was called with correct parameters
        mock_wa.assert_called_once_with("9876543210", "Chandini", 123, "Internet", "Normal", "CSE")

    @patch("sms_services.send_sms_async")
    @patch("sms_services.send_whatsapp_closure_async")
    def test_send_closure_sms(self, mock_wa_close, mock_sms):
        # Trigger sending
        send_closure_sms(creator_phone="9876543210", ticket_id=123)
        
        # Verify SMS content
        mock_sms.assert_called_once()
        args_sms = mock_sms.call_args[0]
        self.assertEqual(args_sms[0], "9876543210")
        self.assertIn("123", args_sms[1])
        self.assertIn("closed", args_sms[1])

        # Verify WhatsApp closure called
        mock_wa_close.assert_called_once_with("9876543210", 123)

    @patch("email_services.send_email_async")
    def test_email_helpers(self, mock_email_send):
        # 1. Allocation email
        send_allocation_email("Chandini", "ca@gmail.com", 123, "Internet")
        mock_email_send.assert_called_once()
        args1 = mock_email_send.call_args[0]
        self.assertEqual(args1[0], "ca@gmail.com")
        self.assertIn("Ticket #123 Allocated", args1[1])
        self.assertIn("Chandini", args1[2])
        self.assertIn("123", args1[2])

        # 2. Closure email
        mock_email_send.reset_mock()
        send_closure_email("faculty@gmail.com", 123)
        mock_email_send.assert_called_once()
        args2 = mock_email_send.call_args[0]
        self.assertEqual(args2[0], "faculty@gmail.com")
        self.assertTrue("Ticket Resolved" in args2[1] or "Closed" in args2[1])
        self.assertIn("123", args2[2])
