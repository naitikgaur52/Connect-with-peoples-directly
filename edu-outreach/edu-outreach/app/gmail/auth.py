"""
Google OAuth handling for the Gmail API.

This uses the standard "installed app" OAuth flow with a locally stored
refresh token (token.json). It authenticates as whichever Google account
the admin authorizes during the one-time setup step (see README.md) --
NOT a developer's personal account. After handoff, the client re-runs
this flow once against their own Gmail account and credentials.json
(downloaded from their own Google Cloud project), and everything after
that runs unattended using the stored refresh token.
"""

import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from app.config import Config


def get_gmail_service():
    """
    Returns an authenticated Gmail API service object. Raises a clear
    RuntimeError with setup instructions if the account has not yet been
    authorized (this is expected on first run -- see README.md,
    "Gmail API Setup").
    """
    creds = None
    token_path = Config.GMAIL_TOKEN_FILE

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, Config.GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(Config.GMAIL_CREDENTIALS_FILE):
                raise RuntimeError(
                    "Gmail is not yet authorized. Download 'credentials.json' from your "
                    "Google Cloud project (see README.md -> Gmail API Setup), place it at "
                    f"{Config.GMAIL_CREDENTIALS_FILE}, then run: python scripts/authorize_gmail.py"
                )
            raise RuntimeError(
                "Gmail authorization token missing or invalid. Run: python scripts/authorize_gmail.py"
            )
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def run_interactive_authorization():
    """
    One-time interactive setup: opens a browser for the admin to log into
    the dedicated Gmail account and grant send permission. Intended to be
    run manually via scripts/authorize_gmail.py, never automatically.
    """
    if not os.path.exists(Config.GMAIL_CREDENTIALS_FILE):
        raise RuntimeError(f"Missing {Config.GMAIL_CREDENTIALS_FILE}. Download it from Google Cloud Console first.")

    flow = InstalledAppFlow.from_client_secrets_file(Config.GMAIL_CREDENTIALS_FILE, Config.GMAIL_SCOPES)
    creds = flow.run_local_server(port=0)
    with open(Config.GMAIL_TOKEN_FILE, "w") as f:
        f.write(creds.to_json())
    print(f"Authorization complete. Token saved to {Config.GMAIL_TOKEN_FILE}")
