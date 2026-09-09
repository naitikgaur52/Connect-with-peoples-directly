"""
Central configuration for the outreach system.

Everything here is loaded from environment variables (via a .env file in
development, or real environment variables in production). Nothing
sensitive is hard-coded, and nothing here depends on any personal
developer account -- the person deploying this system fills in their own
values in `.env` (copy `.env.example` to `.env` first).
"""

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # --- Core paths -------------------------------------------------
    BASE_DIR = BASE_DIR
    DATA_DIR = BASE_DIR / "data"
    DATABASE_PATH = os.environ.get("DATABASE_PATH", str(DATA_DIR / "outreach.db"))
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DATABASE_PATH}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # --- Web dashboard ------------------------------------------------
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-please")
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")  # set via scripts/set_admin_password.py

    # --- Gmail / Google OAuth -----------------------------------------
    GMAIL_CREDENTIALS_FILE = os.environ.get("GMAIL_CREDENTIALS_FILE", str(BASE_DIR / "credentials.json"))
    GMAIL_TOKEN_FILE = os.environ.get("GMAIL_TOKEN_FILE", str(BASE_DIR / "token.json"))
    GMAIL_SENDER_EMAIL = os.environ.get("GMAIL_SENDER_EMAIL", "")
    GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    CV_ATTACHMENT_PATH = os.environ.get("CV_ATTACHMENT_PATH", str(BASE_DIR / "attachments" / "cv.pdf"))

    # --- Outreach safeguards (defaults; overridable in dashboard/DB) --
    DEFAULT_MAX_EMAILS_PER_DAY = int(os.environ.get("MAX_EMAILS_PER_DAY", 3))
    DEFAULT_MAX_EMAILS_PER_MONTH = int(os.environ.get("MAX_EMAILS_PER_MONTH", 50))
    DEFAULT_MAX_PER_INSTITUTION = int(os.environ.get("MAX_PER_INSTITUTION", 2))
    DEFAULT_COOLDOWN_DAYS = int(os.environ.get("COOLDOWN_DAYS", 180))
    DEFAULT_CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", 0.75))

    # --- Scheduler ------------------------------------------------------
    DISCOVERY_SCHEDULE_CRON = os.environ.get("DISCOVERY_SCHEDULE_CRON", "0 7 * * *")   # 7am daily
    OUTREACH_SCHEDULE_CRON = os.environ.get("OUTREACH_SCHEDULE_CRON", "0 9,14 * * *")  # 9am & 2pm daily

    # --- Scraper --------------------------------------------------------
    SCRAPER_USER_AGENT = os.environ.get(
        "SCRAPER_USER_AGENT",
        "Mozilla/5.0 (compatible; EduOutreachBot/1.0; +contact-research)"
    )
    SCRAPER_REQUEST_DELAY_SECONDS = float(os.environ.get("SCRAPER_REQUEST_DELAY_SECONDS", 2.0))
    SCRAPER_TIMEOUT_SECONDS = int(os.environ.get("SCRAPER_TIMEOUT_SECONDS", 15))


def ensure_dirs():
    Config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (Config.BASE_DIR / "attachments").mkdir(parents=True, exist_ok=True)
