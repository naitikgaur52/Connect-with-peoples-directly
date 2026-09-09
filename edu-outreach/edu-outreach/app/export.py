"""
Export contacts / outreach history to CSV or Excel.
"""

import csv
import io
from openpyxl import Workbook
from app.models import Contact, OutreachLog


CONTACT_FIELDS = [
    "id", "institution", "name", "title", "department", "email",
    "status", "confidence_score", "source_url", "date_discovered",
]


def _contact_row(c: Contact):
    return [
        c.id, c.institution.name if c.institution else "", c.name, c.title,
        c.department, c.email, c.status, c.confidence_score, c.source_url,
        c.date_discovered.isoformat() if c.date_discovered else "",
    ]


def export_contacts_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CONTACT_FIELDS)
    for c in Contact.query.all():
        writer.writerow(_contact_row(c))
    return output.getvalue()


def export_contacts_xlsx():
    wb = Workbook()
    ws = wb.active
    ws.title = "Contacts"
    ws.append(CONTACT_FIELDS)
    for c in Contact.query.all():
        ws.append(_contact_row(c))

    ws2 = wb.create_sheet("Outreach History")
    ws2.append(["id", "contact_email", "institution", "subject", "status", "sent_at", "error_message"])
    for log in OutreachLog.query.all():
        ws2.append([
            log.id,
            log.contact.email if log.contact else "",
            log.contact.institution.name if log.contact and log.contact.institution else "",
            log.subject, log.status,
            log.sent_at.isoformat() if log.sent_at else "",
            log.error_message,
        ])

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
