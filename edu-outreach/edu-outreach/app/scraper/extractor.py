"""
Heuristic contact extraction from a single HTML page.

College and university staff-directory pages have wildly inconsistent
markup, so this module does NOT try to hard-code one site's structure.
Instead it uses a layered set of heuristics that work reasonably well
across most directory/bio-page layouts, roughly in this priority order:

  1. Structured data: JSON-LD (schema.org Person) blocks, if present.
  2. "Card" heuristic: find every mailto: link, then look at the
     surrounding block-level element for a name and a job title, matched
     against the configured target-title keywords.
  3. Plain-text fallback: regex for email addresses anywhere on the page,
     with a nearby-text title-keyword search for confidence scoring.

Every extracted contact gets a confidence_score (0.0-1.0) reflecting how
sure we are that (a) the email really belongs to this named person and
(b) the title really matches what the client is looking for. Low
confidence is intentional -- see app/dedup.py, which routes low-confidence
contacts to a "needs_review" queue instead of auto-sending to them.

This module is the single place to extend/improve extraction quality as
you tune the system against real target sites -- it does not touch the
database directly, so it's easy to unit test with saved HTML fixtures.
"""

import json
import re
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _title_matches(text, title_keywords):
    text_l = (text or "").lower()
    for kw in title_keywords:
        if kw.lower() in text_l:
            return kw
    return None


def _discipline_matches(text, discipline_keywords):
    text_l = (text or "").lower()
    for kw in discipline_keywords:
        if kw.lower() in text_l:
            return kw
    return None


def extract_from_jsonld(soup):
    """Look for schema.org Person blocks. Highest-confidence source."""
    results = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "Person":
                email = item.get("email", "").replace("mailto:", "")
                results.append({
                    "name": item.get("name"),
                    "title": item.get("jobTitle"),
                    "email": email or None,
                    "department": None,
                    "base_confidence": 0.9,
                })
    return results


def extract_from_mailto_cards(soup, title_keywords, discipline_keywords):
    """
    For each mailto: link, walk up to the nearest reasonably-sized
    container and pull name/title text out of it. This mirrors how most
    directory "card" layouts are built (a div/li per person containing a
    name, a title, and a contact link).
    """
    results = []
    seen_emails = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href.lower().startswith("mailto:"):
            continue
        email = href.split(":", 1)[1].split("?")[0].strip()
        if not email or email.lower() in seen_emails:
            continue
        seen_emails.add(email.lower())

        # Walk up a few levels to find a container with enough text to
        # plausibly hold a name + title.
        container = a
        block_text = ""
        for _ in range(4):
            if container.parent is None:
                break
            container = container.parent
            block_text = _clean(container.get_text(" "))
            if len(block_text) > 15:
                break

        # Name heuristic: prefer a heading element inside the container.
        name = None
        heading = container.find(["h1", "h2", "h3", "h4", "strong", "b"]) if hasattr(container, "find") else None
        if heading:
            name = _clean(heading.get_text())
        if not name:
            # fall back to link text itself, or text before the email in the block
            link_text = _clean(a.get_text())
            name = link_text if link_text and "@" not in link_text else None

        # Search for the title keyword in the text *excluding* the name,
        # so the extracted title phrase doesn't start with the person's name.
        title_search_text = block_text.replace(name, "", 1) if name else block_text
        title_kw = _title_matches(title_search_text, title_keywords)
        discipline_kw = _discipline_matches(block_text, discipline_keywords)

        confidence = 0.4
        if title_kw:
            confidence += 0.3
        if discipline_kw:
            confidence += 0.1
        if name:
            confidence += 0.1
        confidence = min(confidence, 0.95)

        results.append({
            "name": name or "(name not found)",
            "title": title_kw and _extract_title_phrase(title_search_text, title_kw) or None,
            "email": email,
            "department": discipline_kw,
            "base_confidence": confidence,
        })

    return results


def _extract_title_phrase(text, keyword):
    """Grab a short phrase around the matched keyword to use as the title field."""
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return keyword
    start = max(0, idx - 20)
    end = min(len(text), idx + len(keyword) + 20)
    return _clean(text[start:end])


def extract_from_plain_text(soup, title_keywords, discipline_keywords):
    """Last-resort fallback: any email on the page, low confidence."""
    text = soup.get_text(" ")
    results = []
    for match in EMAIL_RE.finditer(text):
        email = match.group(0)
        window_start = max(0, match.start() - 100)
        window_end = min(len(text), match.end() + 100)
        window = text[window_start:window_end]
        title_kw = _title_matches(window, title_keywords)
        if not title_kw:
            continue  # too unreliable without a matched title nearby
        results.append({
            "name": None,
            "title": _extract_title_phrase(window, title_kw),
            "email": email,
            "department": _discipline_matches(window, discipline_keywords),
            "base_confidence": 0.35,
        })
    return results


def extract_contacts(html, title_keywords, discipline_keywords):
    """
    Main entry point. Returns a list of dicts:
      {name, title, email, department, base_confidence}
    Deduplicated by email within this single page.
    """
    soup = BeautifulSoup(html, "html.parser")

    all_results = []
    all_results += extract_from_jsonld(soup)
    all_results += extract_from_mailto_cards(soup, title_keywords, discipline_keywords)
    all_results += extract_from_plain_text(soup, title_keywords, discipline_keywords)

    # Merge by email, keeping the highest-confidence version of each.
    by_email = {}
    for r in all_results:
        if not r.get("email"):
            continue
        key = r["email"].lower()
        if key not in by_email or r["base_confidence"] > by_email[key]["base_confidence"]:
            by_email[key] = r

    return list(by_email.values())
