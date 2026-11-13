"""SMS alerts from an Android backup (synthetic messages only)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal as D
from xml.sax.saxutils import quoteattr

import pytest

from moneyos.domain.importer import SchemaError
from moneyos.domain.models import Status
from moneyos.domain.sms import looks_like_sms_backup, read_alert
from moneyos.domain.statements import detect_format, import_bytes


def stamp(day: date, hour: int = 12) -> int:
    return int(datetime(day.year, day.month, day.day, hour).timestamp() * 1000)


ALERTS = [  # (sender, day, text) in the styles of common Indian banks; all invented
    ("AX-HDFCBK", date(2026, 3, 12), "Sent Rs.500.00 From HDFC Bank A/C *1234 To SWIGGY On 12/03/26 Ref 412345678901 Not You? Call 18002586161"),
    ("JD-SBIUPI", date(2026, 3, 12), "Dear UPI user A/C X1234 debited by 250.0 on date 12Mar26 trf to RAVI KUMAR Refno 412398765432. If not u? call 1800111109. -SBI"),
    ("VM-ICICIT", date(2026, 3, 13), "ICICI Bank Acct XX123 debited for Rs 1,875.56 on 13-Mar-26; FRESHMART credited. UPI:412311112222. Call 18002662 for dispute."),
    ("AX-HDFCBK", date(2026, 3, 1), "Rs.85000.00 credited to HDFC Bank A/c XX1234 on 01-03-26 by a/c linked to VPA acme@okicici (UPI Ref No 412300001111)."),
    ("BZ-AXISBK", date(2026, 3, 14), "INR 999.00 spent on Axis Bank Card XX9876 at NETFLIX on 14-03-26. Avl Limit: INR 45,000.00"),
    ("AX-HDFCBK", date(2026, 3, 15), "Txn of Rs.450.00 failed. Amount debited will be reversed"),
]
NOT_TRANSACTIONS = [
    ("AX-HDFCBK", "Your OTP for transaction of Rs.5000 at AMAZON is 482913. Do not share it with anyone."),
    ("VK-PAYTM", "RAVI has requested Rs.300 from you on Paytm. Pay now."),
    ("AX-HDFCBK", "Your A/c XX1234 Avl Bal is Rs.12,000.50 as on 12-03-26"),
    ("KOTAKB", "Rs 2000 will be debited from your a/c on 15-03 towards SIP"),
    ("AX-HDFCBK", "Your credit card statement is ready. Total due Rs.3,450.00, minimum due Rs.172.50"),
    ("+919800000000", "Hey, dinner was great! I sent you the photos"),
    ("+919800000001", "Your Swiggy order is out for delivery. Pay Rs.250 cash on delivery"),
]
PRIVATE = "Hey, dinner was great! I sent you the photos"


def backup(alerts=ALERTS, others=NOT_TRANSACTIONS, sent=True) -> bytes:
    rows = [f'<sms protocol="0" address={quoteattr(a)} date="{stamp(d)}" type="1" body={quoteattr(b)} read="1" />'
            for a, d, b in alerts]
    rows += [f'<sms protocol="0" address={quoteattr(a)} date="{stamp(date(2026, 3, 10))}" type="1" body={quoteattr(b)} />'
             for a, b in others]
    if sent:  # a message the user sent: never a bank alert
        rows.append(f'<sms protocol="0" address="+919800000000" date="{stamp(date(2026, 3, 11))}" type="2" '
                    f'body="I paid Rs.400 for the cab, send me half" />')
    xml = f"<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>\n<smses count=\"{len(rows)}\">\n" + "\n".join(rows) + "\n</smses>"
    return xml.encode("utf-8")


def test_an_sms_backup_is_recognised_by_its_content():
    assert looks_like_sms_backup(backup()) and detect_format(backup()) == "sms"
    assert detect_format(b"Date,Description,Amount\n") == "csv"


def test_alerts_become_transactions():
    result = import_bytes(backup(), "sms-backup.xml")
    got = {(t.date, t.description, t.amount, t.account, t.reference, t.status) for t in result.transactions}
    assert got == {
        (date(2026, 3, 12), "SWIGGY", D("-500.00"), "HDFCBK XX1234", "412345678901", Status.POSTED),
        (date(2026, 3, 12), "RAVI KUMAR", D("-250.00"), "SBIUPI XX1234", "412398765432", Status.POSTED),
        (date(2026, 3, 13), "FRESHMART", D("-1875.56"), "ICICIT XX123", "412311112222", Status.POSTED),
        (date(2026, 3, 1), "acme@okicici", D("85000.00"), "HDFCBK XX1234", "412300001111", Status.POSTED),
        (date(2026, 3, 14), "NETFLIX", D("-999.00"), "AXISBK XX9876", None, Status.POSTED),
        (date(2026, 3, 15), "SMS alert from HDFCBK", D("-450.00"), "HDFCBK", None, Status.FAILED),  # failed: never counted
    }
    assert result.rejected == []


def test_other_messages_are_never_kept():
    result = import_bytes(backup(), "sms-backup.xml")
    kept = " ".join(" ".join(raw.values()) for raw in result.raw_rows.values())
    assert PRIVATE not in kept and "482913" not in kept and "send me half" not in kept
    assert len(result.raw_rows) == len(ALERTS)  # only the alerts are stored, with their text for traceability


@pytest.mark.parametrize("sender, text", NOT_TRANSACTIONS)
def test_otps_requests_balances_reminders_and_dues_are_not_transactions(sender, text):
    assert read_alert(sender, stamp(date(2026, 3, 10)), text) is None


@pytest.mark.parametrize("text, amount", [
    ("INR999.00 spent on card XX9876 at NETFLIX", "-999.00"),
    ("Rs500 debited from A/c XX1234 to ZOMATO", "-500"),
    ("₹ 1,20,000.50 credited to A/c XX1234 from EMPLOYER", "120000.50"),
])
def test_currency_written_without_a_space(text, amount):
    assert read_alert("HDFCBK", stamp(date(2026, 3, 10)), text)["Amount"] == amount


def test_a_balance_is_never_taken_as_the_amount():
    row = read_alert("HDFCBK", stamp(date(2026, 3, 10)),
                     "Avl Bal Rs.12,000.00. Rs.300.00 debited from A/c XX1234 to ZOMATO on 10-03-26")
    assert row["Amount"] == "-300.00"


def test_alerts_that_look_like_money_but_cannot_be_read_are_shown_not_guessed():
    content = backup(alerts=[("AX-HDFCBK", date(2026, 3, 9), "Rs. debited from A/c XX1234 to SHOP")], others=[], sent=False)
    result = import_bytes(content, "sms.xml")
    assert result.transactions == [] and [r.reason for r in result.rejected] == ["missing amount"]


def test_an_inbox_subfolder_names_the_account():
    result = import_bytes(backup(others=[]), "sms.xml", account="HDFC Savings")
    assert {t.account for t in result.transactions} == {"HDFC Savings"}


def test_size_limit(monkeypatch):
    from moneyos.domain import sms

    monkeypatch.setattr(sms, "MAX_SMS_BYTES", 100)
    with pytest.raises(SchemaError, match="larger than"):
        sms.read_backup(backup())


def test_hostile_or_wrong_xml_is_refused():
    bomb = (b"<?xml version='1.0'?><!DOCTYPE smses [<!ENTITY a 'aaaaaaaaaa'><!ENTITY b '&a;&a;&a;&a;&a;'>]>"
            b"<smses><sms type='1' date='1' address='x' body='&b;'/></smses>")
    with pytest.raises(SchemaError, match="could not be read"):
        import_bytes(bomb, "sms.xml")
    with pytest.raises(SchemaError, match="could not be read"):
        import_bytes(b"<?xml version='1.0'?><smses><sms type='1'", "sms.xml")


def test_an_alert_and_the_same_payment_in_a_statement_are_one_payment(make_txn):
    """The UPI reference in the alert matches the statement's, so the duplicate check sees one payment."""
    from moneyos.domain.dedupe import deduplicate

    alert = import_bytes(backup(alerts=ALERTS[:1], others=[], sent=False), "sms.xml", account="HDFC Savings").transactions
    statement = [make_txn(day="2026-03-12", description="UPI-SWIGGY-412345678901", amount="-500.00",
                          account="HDFC Savings", reference="412345678901")]
    result = deduplicate([statement, alert])
    assert len(result.unique) == 1 and len(result.duplicates) == 1


@pytest.mark.parametrize("text", [
    "Sent Rs.500.00 From HDFC Bank A/C *1234 To SWIGGY On 12/03/26 Ref 412345678901. Never share your OTP/PIN with anyone.",
    "Rs 250 debited from A/c XX1234 to RAVI. Do not share OTP, PIN or CVV with anyone. -Bank",
])
def test_a_safety_footer_does_not_hide_a_real_alert(text):
    assert read_alert("HDFCBK", stamp(date(2026, 3, 12)), text) is not None


@pytest.mark.parametrize("text", [
    "482913 is your OTP for a transaction of Rs.5000 at AMAZON. Do not share it.",
    "Use verification code 7731 to approve Rs.1,200 debited from your card.",
    "One time password for Rs 999 spent at NETFLIX is 551288",
])
def test_otp_messages_are_still_dropped_whatever_the_word_order(text):
    assert read_alert("HDFCBK", stamp(date(2026, 3, 12)), text) is None
