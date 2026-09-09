"""
Optional convenience script: populates a few example target titles and a
starter email template so the dashboard isn't empty on first run. Safe to
run once after initial setup; edit everything afterward from the
dashboard.

Usage:
    python scripts/seed_initial_data.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.factory import create_app
from app.db import db
from app.models import TargetCriteria, EmailTemplate

app = create_app()

DEFAULT_TITLES = ["Dean", "Associate Dean", "Department Chair", "Program Director", "Director of"]
DEFAULT_DISCIPLINES = []  # e.g. ["Computer Science", "Nursing", "Business"]

DEFAULT_TEMPLATE_SUBJECT = "Introduction and CV for your consideration"
DEFAULT_TEMPLATE_BODY = """Dear {{name}},

I hope this message finds you well. I am reaching out to introduce myself \
and share my background, given your role as {{title}} in {{department}} at \
{{institution}}.

I've attached my CV for your review and would welcome the opportunity to \
connect if there is relevant interest or opportunity within your program.

Thank you for your time and consideration.

Best regards,
"""

with app.app_context():
    for title in DEFAULT_TITLES:
        if not TargetCriteria.query.filter_by(type="title", keyword=title).first():
            db.session.add(TargetCriteria(type="title", keyword=title))

    for disc in DEFAULT_DISCIPLINES:
        if not TargetCriteria.query.filter_by(type="discipline", keyword=disc).first():
            db.session.add(TargetCriteria(type="discipline", keyword=disc))

    if not EmailTemplate.query.filter_by(name="Default Introduction").first():
        db.session.add(EmailTemplate(
            name="Default Introduction",
            subject=DEFAULT_TEMPLATE_SUBJECT,
            body=DEFAULT_TEMPLATE_BODY,
            active=True,
        ))

    db.session.commit()
    print("Seeded default target titles and a starter email template. Edit them anytime in the dashboard.")
