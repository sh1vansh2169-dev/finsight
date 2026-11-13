"""Phones paired with the FinSight phone app, and the SMS alerts they send.

A phone is paired from inside the app while the user is signed in: the app
gets its own key, shown once, of which only a hash is stored. That key can do
one thing: send SMS alerts. It cannot read data or sign in.

Alerts go through the same rules as an SMS backup (``domain/sms.py``):
anything that is not a bank or UPI transaction alert, OTPs included, is
dropped and never stored. Kept alerts collect in ONE waiting preview named
``Phone SMS``, which the user reviews and adds like any statement. Each
message has a fingerprint (sender, time, text), so a message the phone sends
twice is only staged once.
"""

from __future__ import annotations

import csv
import hashlib
import io
import secrets
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from moneyos.db.tables import ImportBatch, PhoneDevice, User, utc_now
from moneyos.domain.classify import Rules
from moneyos.domain.sms import HEADER, read_alert
from moneyos.services import imports
from moneyos.services.auth import AuthError
from moneyos.services.errors import NotFoundError

BATCH_NAME = "Phone SMS.csv"
KEY_COLUMN = "SmsKey"
MAX_ALERTS_PER_CALL = 500


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_device(session: Session, user: User, name: str) -> tuple[PhoneDevice, str]:
    """Pair a phone. Returns (device, key); the key is shown only now."""
    token = "fsp_" + secrets.token_urlsafe(32)
    device = PhoneDevice(user_id=user.id, name=name.strip()[:100] or "Phone", token_hash=_hash(token))
    session.add(device)
    session.commit()
    return device, token


def list_devices(session: Session, user: User) -> list[PhoneDevice]:
    return list(session.scalars(select(PhoneDevice).where(PhoneDevice.user_id == user.id,
                                                          PhoneDevice.revoked_at.is_(None)).order_by(PhoneDevice.id)))


def revoke_device(session: Session, user: User, device_id: int) -> None:
    device = session.get(PhoneDevice, device_id)
    if device is None or device.user_id != user.id or device.revoked_at is not None:
        raise NotFoundError(f"phone {device_id} not found")  # another user's phone is "not found" too
    device.revoked_at = utc_now()
    session.commit()


def device_owner(session: Session, token: str) -> int:
    """The user id a phone key belongs to; refuses unknown or disconnected keys."""
    device = session.scalar(select(PhoneDevice).where(PhoneDevice.token_hash == _hash(token)))
    if device is None or device.revoked_at is not None:
        raise AuthError("this phone is not connected; connect it again from the app")
    session.execute(update(PhoneDevice).where(PhoneDevice.id == device.id).values(last_seen_at=utc_now()))
    session.commit()
    return device.user_id


@dataclass
class Received:
    received: int
    kept: int          # new transaction alerts staged for review
    batch_id: int | None


def _fingerprint(sender: str, timestamp_ms: int, body: str) -> str:
    return hashlib.sha256(f"{sender}\n{timestamp_ms}\n{body}".encode()).hexdigest()[:24]


def receive_alerts(session: Session, alerts: list[tuple[str, int, str]], rules: Rules) -> Received:
    """Stage new transaction alerts in the waiting "Phone SMS" preview (in the owner's session)."""
    from moneyos.domain.sms import _sender

    waiting = session.scalar(select(ImportBatch).where(ImportBatch.filename == BATCH_NAME,
                                                       ImportBatch.status == "previewed").order_by(ImportBatch.id.desc()))
    rows: dict[str, dict[str, str]] = {}
    if waiting is not None:
        for row in sorted(waiting.rows, key=lambda r: r.source_row):
            if row.raw and row.raw.get(KEY_COLUMN):
                rows[row.raw[KEY_COLUMN]] = {k: v for k, v in row.raw.items() if isinstance(v, str)}
    before = len(rows)
    for sender, stamp, body in alerts:
        key = _fingerprint(sender, stamp, body)
        if key in rows:
            continue  # sent before (a retry): staged once
        row = read_alert(_sender(sender), stamp, body)
        if row is not None:  # not a transaction alert: dropped here, never stored
            rows[key] = {**row, KEY_COLUMN: key}
    kept = len(rows) - before
    if kept == 0:
        return Received(len(alerts), 0, waiting.id if waiting else None)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=[*HEADER, KEY_COLUMN], extrasaction="ignore")
    writer.writeheader()
    writer.writerows(sorted(rows.values(), key=lambda r: (r["Date"], r[KEY_COLUMN])))
    if waiting is not None:
        imports.discard_import(session, waiting.id)  # replaced by the fuller preview below
    batch = imports.preview_import(session, filename=BATCH_NAME, content=buffer.getvalue().encode("utf-8"),
                                   options=imports.ImportOptions(), rules=rules)
    return Received(len(alerts), kept, batch.id)
