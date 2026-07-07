import os
import json
import ssl
import urllib.parse
import urllib.request
import threading
import logging
import base64

logger = logging.getLogger("sms_services")
if os.getenv("BYPASS_SMS_WHATSAPP_LOGS", "false").lower() == "true":
    logger.setLevel(logging.WARNING)

# ── SMS (BulkSMS HTTP API) ──────────────────────────────────────────────

def _send_sms_sync(phone_number, message):
    api_key = os.getenv("SMS_API_KEY", "c69fc621-e477-43c5-84ea-d9d94108d7cc")
    sender = os.getenv("SMS_SENDER", "SNISTA")
    test_number = os.getenv("SMS_TEST_NUMBER")

    target_number = test_number if test_number else phone_number
    if not target_number:
        logger.warning(f"No target phone number provided. (SMS template: '{message}')")
        return

    # Clean phone number (remove spaces, plus sign, etc.)
    target_number = "".join(c for c in str(target_number) if c.isdigit())
    if not target_number:
        logger.warning("Target phone number contains no digits. Skipping SMS.")
        return

    # URL-encode the message text
    encoded_msg = urllib.parse.quote_plus(message)
    url = f"http://bulksmsapps.com/api/apismsv2.aspx?apikey={api_key}&sender={sender}&number={target_number}&message={encoded_msg}"

    logger.info(f"Sending SMS alert to {target_number}...")
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            resp_body = response.read().decode('utf-8')
            logger.info(f"SMS API response: {resp_body}")
    except Exception as e:
        logger.error(f"Failed to send SMS to {target_number} via API: {e}")

def send_sms_async(phone_number, message):
    thread = threading.Thread(target=_send_sms_sync, args=(phone_number, message), daemon=True)
    thread.start()

# ── WhatsApp (Unified Messaging Platform API) ───────────────────────────

def _normalize_phone(phone_number):
    """Clean and normalize phone number to digits only, with 91 country code."""
    if not phone_number:
        return None
    digits = "".join(c for c in str(phone_number) if c.isdigit())
    if not digits:
        return None
    # Ensure 91 country code prefix for Indian numbers
    if len(digits) == 10:
        digits = "91" + digits
    return digits

def _build_whatsapp_allocation_payload(target_number, ca_name, ticket_id, category_name, priority, department):
    """
    Build the JSON payload for the Unified Messaging Platform WhatsApp API.
    Uses template ID 1773697 for ticket allocation notifications.
    
    Template:
        Dear {{1}}, A new system support ticket has been allocated to you.
        Ticket ID: {{2}} Category: {{3}} Priority: {{4}}
        Please log into the helpdesk portal to update and resolve this issue.
        {{5}}, Helpdesk.
    """
    from_number = os.getenv("WHATSAPP_FROM_NUMBER", "919133386678")
    template_id = os.getenv("WHATSAPP_TEMPLATE_ID", "1773697")

    # Build templateinfo: templateId~var1~var2~var3~var4~var5
    template_info = f"{template_id}~{ca_name}~{ticket_id}~{category_name}~{priority}~{department}"

    payload = {
        "apiver": "1.0",
        "whatsapp": {
            "ver": "2.0",
            "dlr": {
                "url": ""
            },
            "messages": [
                {
                    "coding": "1",
                    "id": str(ticket_id),
                    "msgtype": "1",
                    "templateinfo": template_info,
                    "type": "",
                    "contenttype": "",
                    "b_urlinfo": "",
                    "mediadata": "",
                    "text": "",
                    "addresses": [
                        {
                            "seq": "1",
                            "to": str(target_number),
                            "from": str(from_number),
                            "tag": "sreenidhi-helpdesk"
                        }
                    ]
                }
            ]
        }
    }
    return payload

def _send_whatsapp_allocation_sync(target_number, ca_name, ticket_id, category_name, priority, department):
    """Send a WhatsApp allocation notification via the Unified Messaging Platform."""
    api_url = os.getenv("WHATSAPP_API_URL", "https://103.229.250.150/unified/v2/send")
    client_id = os.getenv("WHATSAPP_CLIENT_ID", "sreenidhiclgbepfs44jy504")
    client_password = os.getenv("WHATSAPP_CLIENT_PASSWORD", "wm84r8yhj9mzp9m1yrm78fqhpmzb8on0")

    payload = _build_whatsapp_allocation_payload(
        target_number, ca_name, ticket_id, category_name, priority, department
    )
    json_data = json.dumps(payload).encode("utf-8")

    # Basic Auth header
    credentials = f"{client_id}:{client_password}"
    auth_b64 = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {auth_b64}",
        "User-Agent": "SNIST-Helpdesk/1.0",
    }

    logger.info(f"Sending WhatsApp allocation to {target_number} for ticket #{ticket_id}...")
    logger.debug(f"WhatsApp payload: {json.dumps(payload, indent=2)}")

    try:
        # Create SSL context that skips verification (API is on IP with likely self-signed cert)
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        req = urllib.request.Request(api_url, data=json_data, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=15, context=ssl_ctx) as response:
            resp_body = response.read().decode("utf-8")
            logger.info(f"WhatsApp API response ({response.status}): {resp_body}")
    except Exception as e:
        logger.error(f"Failed to send WhatsApp to {target_number}: {e}")

def send_whatsapp_allocation_async(phone_number, ca_name, ticket_id, category_name, priority="Normal", department="ICT Department"):
    """
    Asynchronously send a WhatsApp allocation notification using the real API.
    """
    whatsapp_enabled = os.getenv("WHATSAPP_ENABLED", "true").lower() == "true"
    if not whatsapp_enabled:
        return

    test_number = os.getenv("SMS_TEST_NUMBER")
    target_number = _normalize_phone(test_number if test_number else phone_number)
    if not target_number:
        logger.warning(f"No valid phone number for WhatsApp allocation (ticket #{ticket_id}). Skipping.")
        return

    thread = threading.Thread(
        target=_send_whatsapp_allocation_sync,
        args=(target_number, ca_name, ticket_id, category_name, priority, department),
        daemon=True,
    )
    thread.start()

def send_whatsapp_closure_async(phone_number, ticket_id):
    """
    Asynchronously dispatch a WhatsApp closure notification.
    Currently logs only — a closure template ID has not been provided yet.
    Once a closure template is available, this will use the real API.
    """
    whatsapp_enabled = os.getenv("WHATSAPP_ENABLED", "true").lower() == "true"
    if not whatsapp_enabled:
        return

    test_number = os.getenv("SMS_TEST_NUMBER")
    target_number = _normalize_phone(test_number if test_number else phone_number)
    if not target_number:
        logger.warning(f"No valid phone number for WhatsApp closure (ticket #{ticket_id}). Skipping.")
        return

    def _log_closure():
        logger.info(
            f"[WhatsApp Closure — Template Pending] "
            f"Would notify {target_number} that ticket #{ticket_id} is resolved. "
            f"Awaiting closure template ID from college to enable real delivery."
        )

    thread = threading.Thread(target=_log_closure, daemon=True)
    thread.start()

# ── Public API (called from db_services.py) ──────────────────────────────

def send_allocation_sms(ca_name, ca_phone, ticket_id, category_name="System", department="ICT Department"):
    """
    Send ticket allocation notifications via both SMS and WhatsApp.
    Called from db_services.py when a new ticket is created.
    """
    # SMS (BulkSMS — existing template)
    msg = f"Dear {ca_name}, A ticket id with {ticket_id} about System has been allocated to you, pls attend to it immediately. - ICT"
    send_sms_async(ca_phone, msg)

    # WhatsApp (Unified Messaging Platform — real API with template 1773697)
    send_whatsapp_allocation_async(ca_phone, ca_name, ticket_id, category_name, "Normal", department)

def send_closure_sms(creator_phone, ticket_id):
    """
    Send ticket closure notifications via SMS and WhatsApp.
    Called from db_services.py when a ticket is resolved.
    """
    # SMS (BulkSMS — existing template)
    msg = f"Dear staff, Your ICT complaint ticket id : {ticket_id} is closed, please check and if you are not satisfied reopen the same ticket id. - ICT"
    send_sms_async(creator_phone, msg)

    # WhatsApp closure (currently simulated — awaiting template from college)
    send_whatsapp_closure_async(creator_phone, ticket_id)
