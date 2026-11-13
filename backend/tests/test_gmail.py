"""Gmail import against a stand-in Google server (no real account is ever used in tests)."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from domain.test_statements import pdf_bytes
from moneyos import gmail

PDF = pdf_bytes()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def email(sender, parts, internal="1773300000000"):
    return {"internalDate": internal, "payload": {"headers": [{"name": "From", "value": sender}], "parts": parts}}


MESSAGES = {
    "m1statement": email("HDFC Bank <estatements@hdfcbank.example>", [
        {"mimeType": "text/plain", "body": {"data": b64(b"Your statement is attached.")}},
        {"mimeType": "application/pdf", "filename": "Statement_Mar2026.pdf", "body": {"attachmentId": "att1", "size": len(PDF)}},
    ]),
    "m2photo": email("HDFC Bank <estatements@hdfcbank.example>", [
        {"mimeType": "image/png", "filename": "logo.png", "body": {"attachmentId": "att2", "size": 10}},
    ]),
    "a1plain": email("HDFC Bank InstaAlerts <alerts@hdfcbank.example>", [
        {"mimeType": "text/plain", "body": {"data": b64(
            b"Dear Customer, Rs.500.00 has been debited from account **1234 to VPA swiggy@icici on 12-03-26. "
            b"Your UPI transaction reference number is 412345678901.")}},
    ]),
    "a2html": email("Axis Bank Alerts <alerts@axisbank.example>", [
        {"mimeType": "text/html", "body": {"data": b64(
            b"<html><body><p>INR 999.00 spent on Axis Bank Card XX9876 at <b>NETFLIX</b> on 14-03-26.</p></body></html>")}},
    ]),
    "a3otp": email("HDFC Bank <alerts@hdfcbank.example>", [
        {"mimeType": "text/plain", "body": {"data": b64(
            b"OTP for transaction of Rs.5000 at AMAZON is 482913. Amount will be debited after verification.")}},
    ]),
}


class FakeGoogle(BaseHTTPRequestHandler):
    calls: list[tuple[str, str]] = []
    challenge = ""
    redirect = ""

    def log_message(self, *args):
        pass

    def _json(self, body, code=200):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        FakeGoogle.calls.append(("POST", self.path))
        form = dict(urllib.parse.parse_qsl(self.rfile.read(int(self.headers["Content-Length"])).decode()))
        if form.get("grant_type") == "authorization_code":
            verifier_ok = (base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest())
                           .rstrip(b"=").decode() == FakeGoogle.challenge)
            if form.get("code") != "the-code" or not verifier_ok or form.get("redirect_uri") != FakeGoogle.redirect:
                return self._json({"error": "invalid_grant"}, 400)
            return self._json({"access_token": "tok", "refresh_token": "refresh-1"})
        if form.get("grant_type") == "refresh_token" and form.get("refresh_token") == "refresh-1":
            return self._json({"access_token": "tok"})
        return self._json({"error": "invalid_request"}, 400)

    def do_GET(self):
        FakeGoogle.calls.append(("GET", self.path))
        if self.headers.get("Authorization") != "Bearer tok":
            return self._json({"error": "unauthenticated"}, 401)
        url = urllib.parse.urlparse(self.path)
        parts = url.path.split("/")[2:]  # after /api
        query = dict(urllib.parse.parse_qsl(url.query))
        if parts == ["messages"]:
            ids = ["m1statement", "m2photo"] if "has:attachment" in query["q"] else ["a1plain", "a2html", "a3otp"]
            return self._json({"messages": [{"id": i} for i in ids]})
        if len(parts) == 2:
            return self._json(MESSAGES[parts[1]])
        if len(parts) == 4 and parts[3] == "att1":
            return self._json({"data": b64(PDF)})
        return self._json({"error": "not found"}, 404)


@pytest.fixture
def google():
    server = HTTPServer(("127.0.0.1", 0), FakeGoogle)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeGoogle.calls = []
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield gmail.Endpoints(auth=f"{base}/auth", token=f"{base}/token", api=f"{base}/api")
    server.shutdown()
    server.server_close()


def browser_that_approves(code="the-code", state_override=None):
    """Stands in for the user's browser: reads Google's sign-in URL and returns to FinSight with a code."""
    seen = {}

    def open_browser(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        seen.update(query)
        FakeGoogle.challenge, FakeGoogle.redirect = query["code_challenge"], query["redirect_uri"]
        back = query["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": state_override or query["state"]})
        urllib.request.urlopen(back, timeout=5).read()

    return open_browser, seen


CLIENT = {"client_id": "id.apps.googleusercontent.com", "client_secret": "s"}


def test_connect_asks_only_for_read_only_access_and_keeps_the_token_locally(google, tmp_path):
    open_browser, seen = browser_that_approves()
    token = tmp_path / "gmail" / "token.json"
    gmail.connect(CLIENT, token, endpoints=google, open_browser=open_browser, timeout=10)
    assert seen["scope"] == "https://www.googleapis.com/auth/gmail.readonly"
    assert seen["code_challenge_method"] == "S256" and seen["redirect_uri"].startswith("http://127.0.0.1:")
    assert json.loads(token.read_text())["refresh_token"] == "refresh-1"
    assert gmail.disconnect(token) and not token.exists()


def test_a_sign_in_reply_for_another_request_is_refused(google, tmp_path):
    open_browser, _ = browser_that_approves(state_override="someone-else")
    with pytest.raises(gmail.GmailError, match="did not match"):
        gmail.connect(CLIENT, tmp_path / "token.json", endpoints=google, open_browser=open_browser, timeout=10)
    assert not (tmp_path / "token.json").exists()


def test_the_client_file_must_be_a_desktop_app(tmp_path):
    (tmp_path / "web.json").write_text(json.dumps({"web": {"client_id": "x"}}))
    with pytest.raises(gmail.GmailError, match="Desktop app"):
        gmail.load_client(tmp_path / "web.json")
    (tmp_path / "ok.json").write_text(json.dumps({"installed": CLIENT}))
    assert gmail.load_client(tmp_path / "ok.json") == CLIENT


def test_fetch_saves_statements_and_alerts_once_and_only_reads(google, tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({**CLIENT, "refresh_token": "refresh-1"}))
    inbox, state = tmp_path / "inbox", tmp_path / "seen.json"
    result = gmail.fetch(gmail.Gmail(token, endpoints=google), inbox, state, now=datetime(2026, 3, 15, 9, 0))

    assert result.statements == ["HDFC Bank/m1statem-Statement_Mar2026.pdf"]  # the logo was not a statement
    assert (inbox / "HDFC Bank" / "m1statem-Statement_Mar2026.pdf").read_bytes() == PDF
    assert result.alerts == 2 and result.alerts_file == "gmail-alerts-20260315-090000.csv"
    alerts = (inbox / result.alerts_file).read_text(encoding="utf-8")
    assert "swiggy@icici" in alerts and "-500.00" in alerts and "412345678901" in alerts
    assert "NETFLIX" in alerts and "-999.00" in alerts
    assert "482913" not in alerts  # the OTP email was not a transaction and is not kept

    again = gmail.fetch(gmail.Gmail(token, endpoints=google), inbox, state)
    assert again.statements == [] and again.alerts == 0 and again.skipped == 5
    assert {method for method, path in FakeGoogle.calls if path.startswith("/api")} == {"GET"}  # read-only


def test_fetched_items_are_staged_for_review_by_the_inbox(google, tmp_path, database_url):
    from moneyos.config import DataMode
    from moneyos.db.session import init_db
    from moneyos.db.tables import ImportBatch, User
    from moneyos.db.tenancy import system_session
    from moneyos.domain.classify import load_rules
    from moneyos.services.inbox import Inbox
    from sqlalchemy import select

    token = tmp_path / "token.json"
    token.write_text(json.dumps({**CLIENT, "refresh_token": "refresh-1"}))
    inbox = tmp_path / "inbox"
    gmail.fetch(gmail.Gmail(token, endpoints=google), inbox, tmp_path / "seen.json")
    factory = init_db(database_url, DataMode.REAL)
    try:
        with system_session(factory) as s:
            s.add(User(email="you@example.com"))
            s.commit()
        watcher = Inbox(inbox, factory, load_rules())
        watcher.scan()
        assert len(watcher.scan().staged) == 2
        with system_session(factory) as s:
            staged = {(b.filename, b.account_override, b.status, b.new_rows) for b in s.scalars(select(ImportBatch))}
        assert ("m1statem-Statement_Mar2026.pdf", "HDFC Bank", "previewed", 5) in staged
        assert any(name.startswith("gmail-alerts-") and new == 2 for name, _, _, new in staged)
    finally:
        factory.kw["bind"].dispose()


def test_not_connected_says_what_to_do(tmp_path):
    with pytest.raises(gmail.GmailError, match="moneyos gmail connect"):
        gmail.Gmail(tmp_path / "missing.json")


def test_attachment_names_cannot_escape_the_inbox():
    name = gmail._safe("../../Windows/evil.pdf")
    assert "/" not in name and not name.startswith(".") and name.endswith("evil.pdf")
    assert "/" not in gmail._safe("a/b\\c.pdf") and "\\" not in gmail._safe("a/b\\c.pdf")
    assert gmail._safe("...") == "statement"
