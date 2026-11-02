"""Password and opaque-cookie session helpers for Woodesk accounts."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import db

ITERATIONS = 600_000
SESSION_DAYS = 14
_DUMMY_SALT = bytes.fromhex("f42e8cc8fb5a7cccb4ec7c568f1a4f82")
_DUMMY_HASH = hashlib.pbkdf2_hmac("sha256", b"invalid-password", _DUMMY_SALT, ITERATIONS)


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            raise ValueError("Unsupported password hash.")
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _DUMMY_SALT, ITERATIONS)
        hmac.compare_digest(actual, _DUMMY_HASH)
        return False


def new_session(user_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    db.create_session(user_id, db._hash_token(token), expires.isoformat(timespec="seconds"))
    return token, expires


def new_invitation():
    token = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(days=7)
    return token, expires


def cookie(token, max_age=SESSION_DAYS * 24 * 60 * 60, secure=False):
    value = f"jobdesk_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
    return value + ("; Secure" if secure else "")


def session_user(token):
    if not token:
        return None
    return db.get_session_user(db._hash_token(token))
