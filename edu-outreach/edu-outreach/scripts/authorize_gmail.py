"""
Run this once to authorize the dedicated Gmail account for sending.

Usage:
    python scripts/authorize_gmail.py

This opens a browser window where you log into the Gmail account that
should send the outreach emails, and grant the "send email" permission.
A refresh token is then saved to token.json so future sends happen
without any further interaction.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.gmail.auth import run_interactive_authorization

if __name__ == "__main__":
    run_interactive_authorization()
