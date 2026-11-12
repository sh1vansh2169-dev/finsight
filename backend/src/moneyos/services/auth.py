"""Accounts, passwords and sign-in sessions.

* Passwords: scrypt (memory-hard; Python standard library) with a random
  16-byte salt per user, compared in constant time.
* Sessions: a random 256-bit token is returned once; only its SHA-256 hash
  is stored, so a copy of the database cannot be used to sign in. Sessions
  expire and can be revoked (sign-out).
* Sign-in failures: the same message whether the email or the password was
  wrong; after ``MAX_FAILURES`` failures in ``FAILURE_WINDOW`` the email is
  locked for that window.

All functions here take a *system* session (see db/tenancy.py), because
they run before anyone is signed in.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from moneyos.db.tables import (
    AuthSession,
    Base,
    ImportRow,
    MajraGroupMember,
    MajraShare,
    Owned,
    TransactionRecord,
    User,
    utc_now,
)
from moneyos.services.errors import ConflictError, InvalidRequestError

SESSION_DAYS = 7
MIN_PASSWORD = 10
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60  # seconds
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+$")


class AuthError(PermissionError):
    """401: not signed in, or the credentials are wrong."""


class TooManyAttempts(PermissionError):
    """429: too many failed sign-ins for this email; try again later."""


# ------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p))
    return hmac.compare_digest(actual, base64.b64decode(digest))


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise InvalidRequestError(f"use at least {MIN_PASSWORD} characters")
    if password.strip() != password or not password.strip():
        raise InvalidRequestError("the password cannot start or end with spaces")
    if any(ord(ch) < 32 or ch in "﻿​‌‍⁠" for ch in password):
        raise InvalidRequestError("the password contains invisible or control characters")


def normalise_email(email: str) -> str:
    email = email.strip().lower()
    if not _EMAIL.match(email) or len(email) > 254:
        raise InvalidRequestError("that does not look like an email address")
    return email


# ---------------------------------------------------------- failed sign-ins


class _Failures:
    """In-memory record of recent failed sign-ins per email (resets on restart)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._times: dict[str, list[float]] = {}

    def locked(self, email: str) -> bool:
        with self._lock:
            recent = [t for t in self._times.get(email, []) if time.monotonic() - t < FAILURE_WINDOW]
            self._times[email] = recent
            return len(recent) >= MAX_FAILURES

    def record(self, email: str) -> None:
        with self._lock:
            self._times.setdefault(email, []).append(time.monotonic())

    def clear(self, email: str) -> None:
        with self._lock:
            self._times.pop(email, None)


failures = _Failures()


# ------------------------------------------------------------------ users


def user_count(session: Session) -> int:
    return len(session.scalars(select(User.id)).all())


def create_user(session: Session, email: str, password: str) -> User:
    email = normalise_email(email)
    check_password_rules(password)
    if session.scalar(select(User.id).where(User.email == email)):
        raise ConflictError("an account with that email already exists")
    user = User(email=email, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    return user


def set_password(session: Session, email: str, password: str) -> User:
    check_password_rules(password)
    user = session.scalar(select(User).where(User.email == normalise_email(email)))
    if user is None:
        raise InvalidRequestError(f"no account for {email}")
    user.password_hash = hash_password(password)
    session.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
                    .values(revoked_at=utc_now()))  # a new password signs out everywhere
    session.commit()
    return user


# ---------------------------------------------------------------- sessions


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def sign_in(session: Session, email: str, password: str) -> tuple[User, str]:
    """Returns (user, token). The token is shown only now."""
    try:
        email = normalise_email(email)
    except InvalidRequestError:
        raise AuthError("email or password is incorrect") from None
    if failures.locked(email):
        raise TooManyAttempts(f"too many failed attempts; try again in {FAILURE_WINDOW // 60} minutes")
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(password, user.password_hash):
        if user is None:
            verify_password(password, hash_password("timing-equaliser"))  # similar time either way
        failures.record(email)
        raise AuthError("email or password is incorrect")
    failures.clear(email)
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(user_id=user.id, token_hash=_token_hash(token),
                            expires_at=utc_now() + timedelta(days=SESSION_DAYS)))
    session.commit()
    return user, token


def user_for_token(session: Session, token: str) -> User:
    record = session.scalar(select(AuthSession).where(AuthSession.token_hash == _token_hash(token)))
    if record is None or record.revoked_at is not None or record.expires_at <= utc_now():
        raise AuthError("please sign in again")
    return session.get(User, record.user_id)


def sign_out(session: Session, token: str) -> None:
    session.execute(update(AuthSession).where(AuthSession.token_hash == _token_hash(token))
                    .values(revoked_at=utc_now()))
    session.commit()


def delete_account(session: Session, user: User, password: str) -> dict[str, int]:
    """Permanently delete the user and every record they own. Returns rows deleted per table."""
    if not verify_password(password, user.password_hash):
        raise AuthError("password is incorrect")
    session.execute(update(TransactionRecord).where(TransactionRecord.user_id == user.id)
                    .values(duplicate_of_id=None))  # break self-references first
    owned = {m.local_table.name: m.class_ for m in Base.registry.mappers if issubclass(m.class_, Owned)}
    # Children before parents, so no foreign key is left dangling.
    order = ("match_candidates", "majra_entries", "majra_groups", "majra_people", "commitments", "budgets",
             "audit_events", "transactions", "import_batches", "accounts")
    deleted = {}
    for table in order:
        cls = owned[table]
        if table == "majra_entries":
            ids = select(cls.id).where(cls.user_id == user.id)
            session.execute(delete(MajraShare).where(MajraShare.entry_id.in_(ids)))
        if table == "majra_groups":
            ids = select(cls.id).where(cls.user_id == user.id)
            session.execute(delete(MajraGroupMember).where(MajraGroupMember.group_id.in_(ids)))
        if table == "import_batches":
            ids = select(cls.id).where(cls.user_id == user.id)
            session.execute(delete(ImportRow).where(ImportRow.batch_id.in_(ids)))
        deleted[table] = session.execute(delete(cls).where(cls.user_id == user.id)).rowcount
    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    session.delete(user)
    session.commit()
    return deleted
