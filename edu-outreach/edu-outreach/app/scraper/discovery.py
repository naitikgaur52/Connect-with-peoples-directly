"""
Discovery orchestration.

Walks the admin-configured list of SeedUrl rows (e.g. a university's
faculty directory page), fetches each one, runs the extractor, resolves
each result against the Institution/Contact tables (creating or updating
as needed), and applies the eligibility engine to set an initial status.

This module deliberately does NOT try to crawl the entire internet or
auto-discover new institutions -- the client's spec calls for a
maintainable, targeted system, not a broad crawler. Seed URLs are managed
from the dashboard (Institutions / Seed URLs page). This keeps the system
predictable, auditable, and easy to keep polite (rate-limited, one
domain's robots.txt respected) as required for responsible scraping.
"""

import time
import logging
from urllib.parse import urlparse
import requests
from urllib import robotparser

from app.db import db
from app.config import Config
from app.models import Institution, Contact, SeedUrl, TargetCriteria
from app.dedup import apply_new_contact_status
from app.scraper.extractor import extract_contacts

logger = logging.getLogger("discovery")

_robots_cache = {}


def _allowed_by_robots(url):
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in _robots_cache:
        rp = robotparser.RobotFileParser()
        rp.set_url(base + "/robots.txt")
        try:
            rp.read()
        except Exception:
            # If robots.txt can't be read, default to allowing but log it.
            logger.warning("Could not read robots.txt for %s", base)
            _robots_cache[base] = None
        else:
            _robots_cache[base] = rp

    rp = _robots_cache[base]
    if rp is None:
        return True
    return rp.can_fetch(Config.SCRAPER_USER_AGENT, url)


def _get_or_create_institution(name, url):
    domain = urlparse(url).netloc.lower()
    inst = Institution.query.filter_by(domain=domain).first()
    if inst:
        return inst
    inst = Institution(name=name or domain, domain=domain, source_url=url)
    db.session.add(inst)
    db.session.commit()
    return inst


def fetch_page(url):
    headers = {"User-Agent": Config.SCRAPER_USER_AGENT}
    resp = requests.get(url, headers=headers, timeout=Config.SCRAPER_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.text


def get_active_keywords():
    titles = [c.keyword for c in TargetCriteria.query.filter_by(type=TargetCriteria.TYPE_TITLE, active=True).all()]
    disciplines = [c.keyword for c in TargetCriteria.query.filter_by(type=TargetCriteria.TYPE_DISCIPLINE, active=True).all()]
    return titles, disciplines


def run_discovery_for_seed(seed: SeedUrl, title_keywords, discipline_keywords):
    """Process a single seed URL. Returns number of new/updated contacts."""
    if not _allowed_by_robots(seed.url):
        seed.last_scrape_result = "Skipped: disallowed by robots.txt"
        db.session.commit()
        logger.info("Skipping %s (robots.txt disallows)", seed.url)
        return 0

    try:
        html = fetch_page(seed.url)
    except requests.RequestException as e:
        seed.last_scrape_result = f"Fetch error: {e}"
        db.session.commit()
        logger.warning("Failed to fetch %s: %s", seed.url, e)
        return 0

    extracted = extract_contacts(html, title_keywords, discipline_keywords)
    institution = _get_or_create_institution(seed.institution_name, seed.url)

    count = 0
    for item in extracted:
        email = (item.get("email") or "").strip().lower() or None
        name = (item.get("name") or "(name not found)").strip()

        existing = None
        if email:
            existing = Contact.query.filter_by(institution_id=institution.id, email=email).first()

        if existing:
            # Refresh fields but never silently downgrade a manually-reviewed status.
            existing.title = item.get("title") or existing.title
            existing.department = item.get("department") or existing.department
            existing.source_url = seed.url
            existing.confidence_score = max(existing.confidence_score, item.get("base_confidence", 0))
            contact = existing
        else:
            contact = Contact(
                institution_id=institution.id,
                name=name,
                title=item.get("title"),
                department=item.get("department"),
                email=email,
                source_url=seed.url,
                confidence_score=item.get("base_confidence", 0.0),
            )
            db.session.add(contact)
            db.session.flush()  # get contact.id, needed for status logic
            apply_new_contact_status(contact)

        count += 1

    seed.last_scrape_result = f"{count} contact(s) found"
    db.session.commit()
    return count


def run_discovery(seed_ids=None):
    """
    Run discovery across all active seed URLs (or a specific subset).
    Rate-limits itself between requests per SCRAPER_REQUEST_DELAY_SECONDS.
    Returns a summary dict.
    """
    title_keywords, discipline_keywords = get_active_keywords()
    if not title_keywords:
        logger.warning("No active target titles configured -- discovery will find nothing useful.")

    query = SeedUrl.query.filter_by(active=True)
    if seed_ids:
        query = query.filter(SeedUrl.id.in_(seed_ids))
    seeds = query.all()

    total_new = 0
    for i, seed in enumerate(seeds):
        total_new += run_discovery_for_seed(seed, title_keywords, discipline_keywords)
        seed.last_scraped_at = db.func.now()
        if i < len(seeds) - 1:
            time.sleep(Config.SCRAPER_REQUEST_DELAY_SECONDS)

    db.session.commit()
    return {"seeds_processed": len(seeds), "contacts_found_or_updated": total_new}
