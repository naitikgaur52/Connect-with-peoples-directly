"""
Deduplication + eligibility engine.

This is the piece that answers: "is it OK to email this person right now?"
It is deliberately kept separate from the scraper and the Gmail sender so
it can be unit-tested and audited on its own, and so every send path
(scheduled or manual, from the dashboard) goes through the same checks.
"""

from datetime import datetime, timedelta, timezone
from app.db import db
from app.models import Contact, Exclusion, OutreachLog, Setting
from app.config import Config


def _norm(s):
    return (s or "").strip().lower()


def is_excluded(institution_name=None, domain=None, email=None, department=None, name=None):
    """
    Check the standing Exclusion table. Returns (True, reason) if any
    exclusion rule matches, else (False, None).
    """
    checks = [
        (Exclusion.TYPE_INSTITUTION, institution_name),
        (Exclusion.TYPE_DOMAIN, domain),
        (Exclusion.TYPE_EMAIL, email),
        (Exclusion.TYPE_DEPARTMENT, department),
        (Exclusion.TYPE_NAME, name),
    ]
    for etype, value in checks:
        if not value:
            continue
        match = Exclusion.query.filter_by(type=etype, value=_norm(value)).first()
        if match:
            return True, f"Excluded ({etype}='{value}'): {match.reason or 'no reason given'}"
    return False, None


def find_existing_contact(institution_id, email=None, name=None):
    """
    Look for a pre-existing contact record for this institution, matched
    first by exact email (most reliable), then by exact name, to avoid
    creating duplicate rows when the scraper re-discovers the same person
    from a different page. Used by the dashboard's "possible duplicate"
    checks; the scraper's own write path (app/scraper/discovery.py)
    performs its own email-based lookup inline.
    """
    if email:
        existing = Contact.query.filter_by(institution_id=institution_id, email=_norm(email)).first()
        if existing:
            return existing

    if name:
        candidates = Contact.query.filter_by(institution_id=institution_id).all()
        for c in candidates:
            if _norm(c.name) == _norm(name):
                return c
    return None


def was_recently_contacted(contact_id, cooldown_days=None):
    """True if this contact was emailed within the cooldown window."""
    cooldown_days = cooldown_days or int(Setting.get("cooldown_days", Config.DEFAULT_COOLDOWN_DAYS))
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
    recent = (
        OutreachLog.query
        .filter(OutreachLog.contact_id == contact_id)
        .filter(OutreachLog.status == OutreachLog.STATUS_SENT)
        .filter(OutreachLog.sent_at >= cutoff)
        .first()
    )
    return recent is not None


def emails_sent_today():
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return OutreachLog.query.filter(
        OutreachLog.status == OutreachLog.STATUS_SENT, OutreachLog.sent_at >= start
    ).count()


def emails_sent_this_month():
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return OutreachLog.query.filter(
        OutreachLog.status == OutreachLog.STATUS_SENT, OutreachLog.sent_at >= start
    ).count()


def emails_sent_to_institution(institution_id):
    return (
        OutreachLog.query.join(Contact)
        .filter(Contact.institution_id == institution_id, OutreachLog.status == OutreachLog.STATUS_SENT)
        .count()
    )


def daily_limit_reached():
    limit = int(Setting.get("max_emails_per_day", Config.DEFAULT_MAX_EMAILS_PER_DAY))
    return emails_sent_today() >= limit


def monthly_limit_reached():
    limit = int(Setting.get("max_emails_per_month", Config.DEFAULT_MAX_EMAILS_PER_MONTH))
    return emails_sent_this_month() >= limit


def institution_limit_reached(institution_id):
    limit = int(Setting.get("max_per_institution", Config.DEFAULT_MAX_PER_INSTITUTION))
    return emails_sent_to_institution(institution_id) >= limit


def automation_paused():
    return Setting.get("automation_paused", "false").lower() == "true"


def evaluate_contact_for_sending(contact: Contact):
    """
    The single gatekeeping function. Returns (eligible: bool, reason: str).
    Called by the scheduler before every automated send, and available to
    the dashboard for a manual "why can't I send to this person" check.
    """
    if automation_paused():
        return False, "Automation is paused."

    if contact.status != Contact.STATUS_ELIGIBLE:
        return False, f"Contact status is '{contact.status}', not eligible."

    excluded, reason = is_excluded(
        institution_name=contact.institution.name if contact.institution else None,
        domain=contact.institution.domain if contact.institution else None,
        email=contact.email,
        department=contact.department,
        name=contact.name,
    )
    if excluded:
        return False, reason

    if not contact.email:
        return False, "No email address on file."

    threshold = float(Setting.get("confidence_threshold", Config.DEFAULT_CONFIDENCE_THRESHOLD))
    if contact.confidence_score < threshold:
        return False, f"Confidence {contact.confidence_score:.2f} below threshold {threshold:.2f} -- needs manual review."

    if was_recently_contacted(contact.id):
        return False, "Contacted within the cooldown period."

    if daily_limit_reached():
        return False, "Daily send limit reached."

    if monthly_limit_reached():
        return False, "Monthly send limit reached."

    if institution_limit_reached(contact.institution_id):
        return False, "Per-institution send limit reached."

    return True, "Eligible."


def apply_new_contact_status(contact: Contact):
    """
    Called right after a contact is created/updated by the scraper, to set
    its initial status based on exclusions and confidence -- *before* any
    send is attempted. Low-confidence or ambiguous matches land in
    'needs_review' rather than being auto-approved.
    """
    excluded, reason = is_excluded(
        institution_name=contact.institution.name if contact.institution else None,
        domain=contact.institution.domain if contact.institution else None,
        email=contact.email,
        department=contact.department,
        name=contact.name,
    )
    if excluded:
        contact.status = Contact.STATUS_DO_NOT_CONTACT
        contact.notes = (contact.notes or "") + f"\n[auto] {reason}"
        return

    if not contact.email:
        contact.status = Contact.STATUS_INVALID
        contact.notes = (contact.notes or "") + "\n[auto] No email extracted."
        return

    threshold = float(Setting.get("confidence_threshold", Config.DEFAULT_CONFIDENCE_THRESHOLD))
    if contact.confidence_score >= threshold:
        contact.status = Contact.STATUS_ELIGIBLE
    else:
        contact.status = Contact.STATUS_NEEDS_REVIEW
