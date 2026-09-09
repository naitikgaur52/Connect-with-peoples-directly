"""
Background scheduling using APScheduler.

Two jobs run on cron schedules configured in Config (and editable via
environment variables without touching code):

  1. discovery job  -- scrapes seed URLs, populates/updates contacts
  2. outreach job   -- goes through eligible contacts and sends emails,
                        respecting every safeguard in app.dedup

Both jobs log a summary to the application log. Automation can be paused
instantly from the dashboard (Setting: automation_paused) without
stopping the scheduler process itself -- the outreach job just no-ops.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Config
from app.models import Contact, EmailTemplate
from app.dedup import evaluate_contact_for_sending, automation_paused
from app.gmail.sender import send_to_contact

logger = logging.getLogger("scheduler")


def _cron_trigger(cron_expr):
    minute, hour, day, month, day_of_week = cron_expr.split()
    return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week)


def discovery_job(app):
    from app.scraper.discovery import run_discovery
    with app.app_context():
        if automation_paused():
            logger.info("Automation paused -- skipping scheduled discovery.")
            return
        summary = run_discovery()
        logger.info("Discovery run complete: %s", summary)


def outreach_job(app):
    with app.app_context():
        if automation_paused():
            logger.info("Automation paused -- skipping scheduled outreach.")
            return

        template = EmailTemplate.query.filter_by(active=True).first()
        if not template:
            logger.warning("No active email template configured -- skipping outreach run.")
            return

        candidates = Contact.query.filter_by(status=Contact.STATUS_ELIGIBLE).all()
        sent_count = 0
        for contact in candidates:
            ok, reason = evaluate_contact_for_sending(contact)
            if not ok:
                logger.debug("Skipping contact %s: %s", contact.email, reason)
                if "limit reached" in reason:
                    break  # stop the whole run once a global limit is hit
                continue
            result = send_to_contact(contact, template)
            logger.info("Send to %s -> %s", contact.email, result.get("status"))
            if result.get("status") == "sent":
                sent_count += 1
        logger.info("Outreach run complete: %d email(s) sent.", sent_count)


def start_scheduler(app):
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        discovery_job, _cron_trigger(Config.DISCOVERY_SCHEDULE_CRON),
        args=[app], id="discovery_job", replace_existing=True,
    )
    scheduler.add_job(
        outreach_job, _cron_trigger(Config.OUTREACH_SCHEDULE_CRON),
        args=[app], id="outreach_job", replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler started. Discovery: '%s', Outreach: '%s'",
                Config.DISCOVERY_SCHEDULE_CRON, Config.OUTREACH_SCHEDULE_CRON)
    return scheduler
