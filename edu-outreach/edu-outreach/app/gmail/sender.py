"""
Email composition and sending via the Gmail API.
"""

import base64
import logging
import mimetypes
import os
from email.message import EmailMessage

from app.config import Config
from app.gmail.auth import get_gmail_service
from app.db import db
from app.models import Contact, EmailTemplate, OutreachLog

logger = logging.getLogger("gmail_sender")


def render_template(template: EmailTemplate, contact: Contact):
    """Simple {{field}} substitution -- no external templating dependency needed."""
    fields = {
        "name": contact.name or "",
        "title": contact.title or "",
        "institution": contact.institution.name if contact.institution else "",
        "department": contact.department or "",
    }
    subject = template.subject
    body = template.body
    for key, value in fields.items():
        subject = subject.replace("{{" + key + "}}", value)
        body = body.replace("{{" + key + "}}", value)
    return subject, body


def build_message(sender, to, subject, body_text, attachment_path=None):
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    msg.set_content(body_text)

    if attachment_path and os.path.exists(attachment_path):
        ctype, encoding = mimetypes.guess_type(attachment_path)
        if ctype is None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with open(attachment_path, "rb") as f:
            msg.add_attachment(
                f.read(), maintype=maintype, subtype=subtype,
                filename=os.path.basename(attachment_path),
            )

    encoded = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": encoded}


def send_to_contact(contact: Contact, template: EmailTemplate, dry_run=False):
    """
    Sends one email and writes an OutreachLog row regardless of success or
    failure, so the history is always complete and auditable.

    NOTE: this function does NOT check eligibility itself -- callers
    (the scheduler, or the dashboard's manual-send action) must call
    app.dedup.evaluate_contact_for_sending() first. Keeping that check
    outside of this function means it's impossible to send without going
    through the safeguards, no matter which code path triggers a send.
    """
    subject, body = render_template(template, contact)

    if dry_run:
        logger.info("[DRY RUN] Would send to %s: %s", contact.email, subject)
        return {"status": "dry_run", "subject": subject, "body": body}

    try:
        service = get_gmail_service()
        message = build_message(
            sender=Config.GMAIL_SENDER_EMAIL,
            to=contact.email,
            subject=subject,
            body_text=body,
            attachment_path=Config.CV_ATTACHMENT_PATH,
        )
        result = service.users().messages().send(userId="me", body=message).execute()

        log = OutreachLog(
            contact_id=contact.id, template_id=template.id, subject=subject,
            status=OutreachLog.STATUS_SENT, gmail_message_id=result.get("id"),
        )
        contact.status = Contact.STATUS_PREVIOUSLY_CONTACTED
        db.session.add(log)
        db.session.commit()
        return {"status": "sent", "gmail_message_id": result.get("id")}

    except Exception as e:
        logger.exception("Failed to send to %s", contact.email)
        log = OutreachLog(
            contact_id=contact.id, template_id=template.id, subject=subject,
            status=OutreachLog.STATUS_FAILED, error_message=str(e),
        )
        db.session.add(log)
        db.session.commit()
        return {"status": "failed", "error": str(e)}
