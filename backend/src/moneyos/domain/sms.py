"""Bank and UPI alert messages from an Android SMS backup.

Reads the XML file exported by the "SMS Backup & Restore" app
(``<smses><sms address=... date=... type=... body=.../></smses>``) and turns
transaction alerts into rows for the normal import path, so they get the same
validation, duplicate checks and preview-before-adding as a statement.

**Privacy.** A backup holds every message: OTPs, chats, everything. Only
messages that look like money moving in or out of the user's account are
kept; all others are dropped here and never stored. OTPs, payment requests,
reminders ("will be debited"), card dues and balance-only messages are never
treated as transactions.

**How alerts are read (heuristics, written for common Indian bank formats):**

* direction: the first of "debited / spent / paid / sent / withdrawn" or
  "credited / received / deposited / refunded" in the message;
* amount: the first amount marked Rs, INR or ₹ that is not a balance or a
  limit, else "debited by 500.0" style;
* date: the message's own timestamp (reliable), not the text (every bank
  writes dates differently);
* reference: a UPI / UTR reference number, when present, so the same payment
  in a statement is recognised as a duplicate;
* who: "to X", "trf to X", "at X", "X credited", "from X", "by X"; otherwise
  "SMS alert from <sender>".

Messages that look like money but cannot be read come back as rejected rows
with their text, so nothing is guessed. Failed or declined payments are kept
with status "failed", which is never counted.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime

from defusedxml import ElementTree

from moneyos.domain.importer import SchemaError

MAX_SMS_BYTES = 50 * 1024 * 1024
HEADER = ["Date", "Description", "Amount", "Account", "Reference", "Status", "Sender", "Message"]

_DEBIT = r"debited|spent|paid|sent|withdrawn|withdrawal|purchase|deducted|transferred"
_CREDIT = r"credited|received|deposited|refunded|refund|reversed"
_DIRECTION = re.compile(rf"\b(?:(?P<debit>{_DEBIT})|(?P<credit>{_CREDIT}))\b", re.IGNORECASE)
# An OTP message carries a code next to the OTP words. Real alerts often END with "never share
# your OTP/PIN": that footer alone must not hide a payment.
_OTP_WORDS = r"(?:\botp\b|one[- ]time password|verification code)"
_OTP = re.compile(
    _OTP_WORDS + r"[^\n]{0,60}?(?:\bis\b|:|-)\s*\d{4,8}\b"    # "OTP for Rs.5000 at X is 482913", "OTP: 4829"
    + r"|\b\d{4,8}\s+is\s+(?:your|the)\s+" + _OTP_WORDS     # "482913 is your OTP"
    + r"|verification code\s*:?\s*\d{4,8}\b",                # "verification code 7731"
    re.IGNORECASE,
)
_NOT_A_TRANSACTION = re.compile(
    r"\bhas requested\b|\brequested money\b|\b(?:collect|payment|money) request\b|\bcollect\b|"
    r"will be (?:debited|credited|deducted)|\bdue\b|minimum amount|"
    r"\bstatement\b|\bmandate\b.*\bcreated\b|\bauto[- ]?pay\b.*\bscheduled\b|\bscheduled\b",
    re.IGNORECASE,
)
_FAILED = re.compile(r"\bfail(?:ed|ure)?\b|\bdeclined\b|\bunsuccessful\b|\breversal pending\b", re.IGNORECASE)
_AMOUNT = r"(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
_MONEY = re.compile(rf"(?:rs\.?|inr|₹)\s*{_AMOUNT}", re.IGNORECASE)
_CURRENCY = re.compile(r"\b(?:rs|inr)(?=[\s.\d]|$)|₹", re.IGNORECASE)  # "Rs.500", "INR999", "Rs 5"
_BALANCE_WORDS = re.compile(r"(?:bal(?:ance)?|limit|avl|available|outstanding)[^0-9]{0,15}$", re.IGNORECASE)
_BARE = re.compile(rf"\b(?:debited|credited|withdrawn)\s+(?:by|for|with)?\s*{_AMOUNT}", re.IGNORECASE)
_ACCOUNT = re.compile(r"\b(?:a/?c|acct|account|card)\b\.?\s*(?:no\.?\s*)?(?:ending\s*(?:with)?\s*)?[x*•.]*(\d{3,6})\b",
                      re.IGNORECASE)
_REFERENCE = re.compile(r"\b(?:upi\s*ref(?:\s*no)?|ref(?:erence)?\s*(?:no|num(?:ber)?)?|refno|utr|rrn|upi)[\s:.#-]*(\d{8,})",
                        re.IGNORECASE)
_WHO = [
    re.compile(r"\btrf to\s+(?P<who>[A-Za-z0-9 .&@_-]{2,40}?)(?=\s+(?:ref|refno|upi|on|\.|$))", re.IGNORECASE),
    re.compile(r";\s*(?P<who>[A-Za-z0-9 .&@_-]{2,40}?)\s+credited", re.IGNORECASE),
    re.compile(r"\b(?:to|at|towards)\s+(?:vpa\s+)?(?P<who>[A-Za-z0-9 .&@_-]{2,40}?)(?=\s+(?:on|ref|upi|via|using|from|avl|\(|\.|,)|$)",
               re.IGNORECASE),
    re.compile(r"\b(?:from|by)\s+(?:a/c linked to\s+)?(?:vpa\s+)?(?P<who>[A-Za-z0-9 .&@_-]{2,40}?)(?=\s+(?:on|ref|upi|\(|\.|,)|$)",
               re.IGNORECASE),
]
# Whole words only: "acme" must not be mistaken for "a/c".
_GENERIC_WHO = re.compile(r"^(?:(?:your|you|a/?c|acct|account|hdfc bank|bank|card|xx)\b|\*)", re.IGNORECASE)


def looks_like_sms_backup(content: bytes) -> bool:
    head = content[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith((b"<?xml", b"<smses")) and b"<smses" in head


def _sender(address: str) -> str:
    """'AX-HDFCBK' -> 'HDFCBK' (Indian bank senders carry a 2-letter route prefix)."""
    address = address.strip()
    return address.split("-", 1)[1] if re.match(r"^[A-Za-z]{2}-", address) else address


def _amount(body: str) -> str | None:
    for m in _MONEY.finditer(body):
        if not _BALANCE_WORDS.search(body[max(0, m.start() - 20): m.start()]):
            return m.group(1).replace(",", "")
    m = _BARE.search(body)
    return m.group(1).replace(",", "") if m else None


def _who(body: str) -> str | None:
    for pattern in _WHO:
        for m in pattern.finditer(body):
            who = " ".join(m.group("who").split()).strip(" .-")
            if who and not _GENERIC_WHO.match(who) and not re.fullmatch(r"[\dx*]+", who, re.IGNORECASE):
                return who
    return None


def read_alert(sender: str, timestamp_ms: int, body: str, *, source: str = "SMS") -> dict[str, str] | None:
    """One message as a row, or None if it is not a transaction alert (it is then forgotten)."""
    text = " ".join(body.split())
    direction = _DIRECTION.search(text)
    if not direction or _OTP.search(text) or _NOT_A_TRANSACTION.search(text):
        return None
    # A currency mark is enough to keep it: if the amount then cannot be read, the row is shown
    # as unreadable rather than silently dropped.
    has_money = bool(_CURRENCY.search(text) or _BARE.search(text))
    if not has_money:
        return None  # "your card was used", no money mentioned: not something we can record
    when = datetime.fromtimestamp(timestamp_ms / 1000).date()
    amount = _amount(text)
    account = _ACCOUNT.search(text)
    reference = _REFERENCE.search(text)
    debit = direction.group("debit") is not None
    return {
        "Date": when.isoformat(),
        "Description": _who(text) or f"{source} alert from {sender}",
        "Amount": "" if amount is None else (f"-{amount}" if debit else amount),
        "Account": f"{sender} XX{account.group(1)}" if account else sender,
        "Reference": reference.group(1) if reference else "",
        "Status": "failed" if _FAILED.search(text) else "posted",
        "Sender": sender,
        "Message": text[:300],
    }


def read_backup(content: bytes) -> tuple[list[str], Iterator[tuple[int, dict[str, str]]], int]:
    """(header, alert rows, number of messages read). Non-alert messages are not returned."""
    if len(content) > MAX_SMS_BYTES:
        raise SchemaError(f"the SMS backup is larger than {MAX_SMS_BYTES // (1024 * 1024)} MB; "
                          "back up a shorter period or only your banks' conversations")
    try:
        root = ElementTree.fromstring(content)
    except Exception as error:  # defusedxml refuses entity tricks; ParseError for broken files
        raise SchemaError(f"the SMS backup could not be read ({type(error).__name__})") from None
    if root.tag != "smses":
        raise SchemaError("this XML file is not an SMS backup from SMS Backup & Restore")
    rows: list[tuple[int, dict[str, str]]] = []
    count = 0
    for number, sms in enumerate(root.iter("sms"), start=1):
        count += 1
        if sms.get("type") != "1":  # 1 = received; sent messages are not bank alerts
            continue
        try:
            stamp = int(sms.get("date") or "")
        except ValueError:
            continue
        row = read_alert(_sender(sms.get("address") or "unknown"), stamp, sms.get("body") or "")
        if row is not None:
            rows.append((number, row))
    return HEADER, iter(rows), count
