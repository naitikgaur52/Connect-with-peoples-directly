"""
Database models.

Design notes
------------
- `Contact.status` is the single source of truth for "should we email this
  person": eligible / needs_review / previously_contacted / blocked /
  do_not_contact / invalid / cooldown.
- `Exclusion` is a separate table so an admin can block an institution,
  domain, email address, department, or person *before* the scraper ever
  finds them, and so exclusions survive even if the contact record is
  deleted/recreated.
- `OutreachLog` is append-only: one row per email actually sent (or
  attempted). This is what the cooldown / max-per-month calculations read.
- `Setting` is a simple key/value store editable from the dashboard, so
  safeguards can be changed without redeploying code.
"""

from datetime import datetime, timezone
from app.db import db


def utcnow():
    return datetime.now(timezone.utc)


class Institution(db.Model):
    __tablename__ = "institutions"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    domain = db.Column(db.String(255), index=True)  # e.g. "example.edu"
    source_url = db.Column(db.String(1000))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)

    contacts = db.relationship("Contact", back_populates="institution", cascade="all, delete-orphan")

    __table_args__ = (db.UniqueConstraint("domain", name="uq_institution_domain"),)


class Contact(db.Model):
    __tablename__ = "contacts"

    STATUS_ELIGIBLE = "eligible"
    STATUS_NEEDS_REVIEW = "needs_review"
    STATUS_PREVIOUSLY_CONTACTED = "previously_contacted"
    STATUS_BLOCKED = "blocked"
    STATUS_DO_NOT_CONTACT = "do_not_contact"
    STATUS_INVALID = "invalid"
    STATUS_COOLDOWN = "cooldown"

    ALL_STATUSES = [
        STATUS_ELIGIBLE, STATUS_NEEDS_REVIEW, STATUS_PREVIOUSLY_CONTACTED,
        STATUS_BLOCKED, STATUS_DO_NOT_CONTACT, STATUS_INVALID, STATUS_COOLDOWN,
    ]

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(db.Integer, db.ForeignKey("institutions.id"), nullable=False)
    name = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(255))
    department = db.Column(db.String(255))
    email = db.Column(db.String(255), index=True)
    source_url = db.Column(db.String(1000))
    date_discovered = db.Column(db.DateTime, default=utcnow)
    status = db.Column(db.String(50), default=STATUS_NEEDS_REVIEW, index=True)
    confidence_score = db.Column(db.Float, default=0.0)  # 0.0-1.0, how sure the scraper is
    duplicate_of_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=True)
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    institution = db.relationship("Institution", back_populates="contacts")
    outreach_events = db.relationship("OutreachLog", back_populates="contact", cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("institution_id", "email", name="uq_contact_institution_email"),
    )


class Exclusion(db.Model):
    """
    A standing rule that blocks outreach, independent of any single Contact
    record. Checked by the dedup/eligibility engine before every send.
    """
    __tablename__ = "exclusions"

    TYPE_INSTITUTION = "institution"
    TYPE_DOMAIN = "domain"
    TYPE_EMAIL = "email"
    TYPE_DEPARTMENT = "department"
    TYPE_NAME = "name"

    ALL_TYPES = [TYPE_INSTITUTION, TYPE_DOMAIN, TYPE_EMAIL, TYPE_DEPARTMENT, TYPE_NAME]

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)
    value = db.Column(db.String(500), nullable=False)  # normalized (lowercased) value to match against
    reason = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=utcnow)

    __table_args__ = (db.UniqueConstraint("type", "value", name="uq_exclusion_type_value"),)


class EmailTemplate(db.Model):
    __tablename__ = "email_templates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    subject = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=False)  # supports {{name}}, {{title}}, {{institution}}, {{department}}
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class OutreachLog(db.Model):
    __tablename__ = "outreach_log"

    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"

    id = db.Column(db.Integer, primary_key=True)
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey("email_templates.id"))
    subject = db.Column(db.String(500))
    status = db.Column(db.String(50), default=STATUS_SENT)
    gmail_message_id = db.Column(db.String(255))
    error_message = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=utcnow)

    contact = db.relationship("Contact", back_populates="outreach_events")
    template = db.relationship("EmailTemplate")


class TargetCriteria(db.Model):
    """
    Configurable target job titles / disciplines used by the discovery
    scraper to decide who is relevant on a given staff/directory page.
    """
    __tablename__ = "target_criteria"

    TYPE_TITLE = "title"
    TYPE_DISCIPLINE = "discipline"

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(50), nullable=False)   # "title" or "discipline"
    keyword = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)

    __table_args__ = (db.UniqueConstraint("type", "keyword", name="uq_criteria_type_keyword"),)


class SeedUrl(db.Model):
    """
    Starting points for the scraper -- e.g. a university's faculty
    directory or department listing page. The admin manages this list;
    the scraper does not "discover the internet" on its own.
    """
    __tablename__ = "seed_urls"

    id = db.Column(db.Integer, primary_key=True)
    url = db.Column(db.String(1000), nullable=False, unique=True)
    institution_name = db.Column(db.String(255))
    active = db.Column(db.Boolean, default=True)
    last_scraped_at = db.Column(db.DateTime)
    last_scrape_result = db.Column(db.String(255))  # e.g. "12 contacts found"


class Setting(db.Model):
    __tablename__ = "settings"

    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=False)

    @staticmethod
    def get(key, default=None):
        row = Setting.query.get(key)
        return row.value if row else default

    @staticmethod
    def set(key, value):
        row = Setting.query.get(key)
        if row:
            row.value = str(value)
        else:
            row = Setting(key=key, value=str(value))
            db.session.add(row)
        db.session.commit()
