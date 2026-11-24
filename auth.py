"""Session and invitation helpers. Sign-in itself is by magic link (server.py, db.create_login_link)."""

import secrets
from datetime import datetime, timedelta, timezone

import db

SESSION_DAYS = 14


def new_session(user_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    db.create_session(user_id, db._hash_token(token), expires.isoformat(timespec="seconds"))
    return token, expires


def new_invitation(days=7):
    token = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    return token, expires


def cookie(token, max_age=SESSION_DAYS * 24 * 60 * 60, secure=False):
    value = f"jobdesk_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
    return value + ("; Secure" if secure else "")


def session_user(token):
    if not token:
        return None
    return db.get_session_user(db._hash_token(token))
