"""
Minimal single-admin authentication for the dashboard.

This is intentionally simple (one admin account, session cookie) because
the spec calls for a *private* admin dashboard for a single authorized
user, not a multi-user system. The password is stored as a hash (never
plaintext) in the environment/.env file -- set it with
scripts/set_admin_password.py.
"""

from functools import wraps
from flask import session, redirect, url_for, request
from werkzeug.security import check_password_hash
from app.config import Config


def verify_login(username, password):
    if username != Config.ADMIN_USERNAME:
        return False
    if not Config.ADMIN_PASSWORD_HASH:
        return False
    return check_password_hash(Config.ADMIN_PASSWORD_HASH, password)


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("dashboard.login", next=request.path))
        return view_func(*args, **kwargs)
    return wrapped
