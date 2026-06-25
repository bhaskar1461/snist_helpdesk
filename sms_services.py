import os
import urllib.parse
import urllib.request
import threading
import logging

logger = logging.getLogger("sms_services")

def _send_sms_sync(phone_number, message):
    api_key = os.getenv("SMS_API_KEY", "c69fc621-e477-43c5-84ea-d9d94108d7cc")
    sender = os.getenv("SMS_SENDER", "SNISTA")
    test_number = os.getenv("SMS_TEST_NUMBER")

    # Route to test number if specified in env (useful for demo/seeded accounts)
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

def send_whatsapp_async(phone_number, message):
    """
    Asynchronously dispatch a WhatsApp notification.
    By default, logs the notification. If a custom WHATSAPP_API_URL is configured,
    it can hit that endpoint in the background.
    """
    whatsapp_enabled = os.getenv("WHATSAPP_ENABLED", "true").lower() == "true"
    if not whatsapp_enabled:
        return

    test_number = os.getenv("SMS_TEST_NUMBER")
    target_number = test_number if test_number else phone_number
    if not target_number:
        logger.warning(f"No target phone number provided for WhatsApp. (Template: '{message}')")
        return

    target_number = "".join(c for c in str(target_number) if c.isdigit())
    if not target_number:
        logger.warning("Target phone number for WhatsApp contains no digits. Skipping.")
        return

    def _send_whatsapp_sync():
        whatsapp_url = os.getenv("WHATSAPP_API_URL")
        if whatsapp_url:
            # If a custom URL is provided, format it and send GET/POST
            try:
                # Basic substitution or query parameters if needed
                encoded_msg = urllib.parse.quote_plus(message)
                # Form URL or standard payload depending on config
                url = whatsapp_url.replace("{number}", target_number).replace("{message}", encoded_msg)
                if "{number}" not in whatsapp_url:
                    # Append parameters if placeholder not in URL
                    sep = "&" if "?" in whatsapp_url else "?"
                    url = f"{whatsapp_url}{sep}number={target_number}&message={encoded_msg}"
                
                logger.info(f"Sending WhatsApp alert to {target_number} via configured API...")
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=10) as response:
                    resp_body = response.read().decode('utf-8')
                    logger.info(f"WhatsApp API response: {resp_body}")
            except Exception as e:
                logger.error(f"Failed to send WhatsApp to {target_number}: {e}")
        else:
            # Simulate or log the WhatsApp action
            logger.info(f"[WhatsApp Simulation] Sent to {target_number}: '{message}'")

    thread = threading.Thread(target=_send_whatsapp_sync, daemon=True)
    thread.start()

def send_allocation_sms(ca_name, ca_phone, ticket_id):
    # Template 1: Dear {#var#}, A ticket id with {#var#} about System has been allocated to you, pls attend to it immediately. - ICT
    msg = f"Dear {ca_name}, A ticket id with {ticket_id} about System has been allocated to you, pls attend to it immediately. - ICT"
    send_sms_async(ca_phone, msg)
    send_whatsapp_async(ca_phone, msg)

def send_closure_sms(creator_phone, ticket_id):
    # Template 2: Dear staff, Your ICT complaint ticket id : {#var#} is closed, please check and if you are not satisfied reopen the same ticket id. - ICT
    msg = f"Dear staff, Your ICT complaint ticket id : {ticket_id} is closed, please check and if you are not satisfied reopen the same ticket id. - ICT"
    send_sms_async(creator_phone, msg)
    send_whatsapp_async(creator_phone, msg)

