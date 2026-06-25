import os
import smtplib
import logging
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("email_services")

def _send_email_sync(to_email, subject, body):
    host = os.getenv("SMTP_HOST")
    port = os.getenv("SMTP_PORT", "587")
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
    sender = os.getenv("SMTP_SENDER", user)

    if not host or not user:
        logger.warning(f"SMTP is not configured. (Simulated email to: {to_email} | Subject: '{subject}' | Body: '{body}')")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = sender
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP(host, int(port), timeout=10)
        if use_tls:
            server.starttls()
        if password:
            server.login(user, password)
        
        server.sendmail(sender, [to_email], msg.as_string())
        server.quit()
        logger.info(f"Email sent successfully to {to_email}")
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")

def send_email_async(to_email, subject, body):
    if not to_email:
        logger.warning("Empty recipient email address. Skipping email dispatch.")
        return
    thread = threading.Thread(target=_send_email_sync, args=(to_email, subject, body), daemon=True)
    thread.start()

def send_allocation_email(ca_name, ca_email, ticket_id, category_name):
    subject = f"Helpdesk Ticket #{ticket_id} Allocated"
    body = f"Dear {ca_name}, A helpdesk ticket ID with #{ticket_id} about {category_name} has been allocated to you. Please attend to it immediately. - ICT Sreenidhi"
    send_email_async(ca_email, subject, body)

def send_closure_email(creator_email, ticket_id):
    subject = f"Helpdesk Ticket #{ticket_id} Closed"
    body = f"Dear staff, Your ICT complaint ticket id : #{ticket_id} is closed, please check and if you are not satisfied reopen the same ticket id. - ICT"
    send_email_async(creator_email, subject, body)
