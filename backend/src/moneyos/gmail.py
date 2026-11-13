"""Bring bank statements and alert emails from Gmail into the statement inbox.

Read-only, through Google's official OAuth and Gmail API, using the
standard library only. The user creates their own Google Cloud OAuth client
("Desktop app"), runs ``moneyos gmail connect`` once and approves read-only
access in Google's own page. FinSight then:

* saves statement attachments (CSV, Excel, PDF) from matching emails into the
  inbox, in a subfolder named after the sender, so they are imported for
  review like any other statement;
* reads alert emails ("Rs 500 debited ...") with the same rules as SMS
  alerts and writes them to one CSV in the inbox, also for review.

Each email is handled once (its id is remembered). Nothing is sent, deleted
or changed in the mailbox: the only scope requested is ``gmail.readonly``.
The refresh token is stored in a local file under ``data/`` (never committed);
``moneyos gmail disconnect`` deletes it.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import re
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from moneyos.domain.importer import MAX_IMPORT_BYTES
from moneyos.domain.sms import HEADER, read_alert

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
STATEMENT_EXTENSIONS = (".csv", ".xlsx", ".pdf")
# Default searches; the user can replace them (MONEYOS_GMAIL_STATEMENTS / MONEYOS_GMAIL_ALERTS).
STATEMENT_QUERY = "newer_than:120d has:attachment (filename:pdf OR filename:xlsx OR filename:csv) statement"
ALERT_QUERY = "newer_than:60d (debited OR credited) -statement"
MAX_MESSAGES = 200


@dataclass(frozen=True)
class Endpoints:
    auth: str = "https://accounts.google.com/o/oauth2/v2/auth"
    token: str = "https://oauth2.googleapis.com/token"
    api: str = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailError(RuntimeError):
    """Something the user can act on; the message says what."""


def _post_form(url: str, fields: dict[str, str]) -> dict[str, Any]:
    data = urllib.parse.urlencode(fields).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=30) as r:  # noqa: S310
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as error:
        with error:
            detail = error.read().decode(errors="replace")[:300]
        raise GmailError(f"Google refused the request ({error.code}): {detail}") from None
    except urllib.error.URLError as error:
        raise GmailError(f"could not reach Google ({error.reason})") from None


def load_client(path: Path) -> dict[str, str]:
    """The OAuth client file downloaded from Google Cloud ("Desktop app")."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GmailError(f"could not read the client file {path} ({type(error).__name__})") from None
    installed = data.get("installed")
    if not installed or "client_id" not in installed:
        raise GmailError('this is not a "Desktop app" OAuth client file (no "installed" section)')
    return {"client_id": installed["client_id"], "client_secret": installed.get("client_secret", "")}


def connect(client: dict[str, str], token_path: Path, *, endpoints: Endpoints = Endpoints(),
            open_browser: Callable[[str], Any] = webbrowser.open, timeout: float = 300) -> None:
    """One-time consent in the user's browser (OAuth for installed apps, loopback redirect + PKCE)."""
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    received: dict[str, str] = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):  # noqa: N802 - http.server API
            query = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" in query or "error" in query:
                received.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<p>FinSight: you can close this tab and go back to the terminal.</p>".encode())

    server = HTTPServer(("127.0.0.1", 0), Handler)  # only this computer can reach it
    redirect = f"http://127.0.0.1:{server.server_address[1]}"
    url = endpoints.auth + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    thread = threading.Thread(target=server.handle_request, daemon=True)
    server.timeout = timeout
    thread.start()
    open_browser(url)
    thread.join(timeout + 5)
    server.server_close()
    if "error" in received:
        raise GmailError(f"Google sign-in did not complete: {received['error']}")
    if received.get("state") != state:
        raise GmailError("the sign-in reply did not match this request; try again")
    if "code" not in received:
        raise GmailError("no reply from the browser in time; run the command again")
    tokens = _post_form(endpoints.token, {
        "code": received["code"], "client_id": client["client_id"], "client_secret": client["client_secret"],
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if "refresh_token" not in tokens:
        raise GmailError("Google did not return a refresh token; remove FinSight's access and connect again")
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(json.dumps({**client, "refresh_token": tokens["refresh_token"]}), encoding="utf-8")


def disconnect(token_path: Path) -> bool:
    if token_path.exists():
        token_path.unlink()
        return True
    return False


@dataclass
class FetchResult:
    statements: list[str] = field(default_factory=list)  # files saved into the inbox
    alerts: int = 0                                     # alert emails turned into rows
    alerts_file: str | None = None
    skipped: int = 0                                    # emails seen before, or with nothing usable


class Gmail:
    def __init__(self, token_path: Path, *, endpoints: Endpoints = Endpoints()):
        try:
            self.saved = json.loads(Path(token_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise GmailError("Gmail is not connected: run `moneyos gmail connect --client <file>` first") from None
        self.endpoints = endpoints
        self._access: str | None = None

    def _token(self) -> str:
        if self._access is None:
            reply = _post_form(self.endpoints.token, {
                "client_id": self.saved["client_id"], "client_secret": self.saved["client_secret"],
                "refresh_token": self.saved["refresh_token"], "grant_type": "refresh_token",
            })
            self._access = reply["access_token"]
        return self._access

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        url = f"{self.endpoints.api}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._token()}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as r:  # noqa: S310 - fixed Google endpoints
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as error:
            with error:
                detail = error.read().decode(errors="replace")[:300]
            raise GmailError(f"Gmail refused the request ({error.code}): {detail}") from None
        except urllib.error.URLError as error:
            raise GmailError(f"could not reach Gmail ({error.reason})") from None

    def search(self, query: str, limit: int = MAX_MESSAGES) -> list[str]:
        ids: list[str] = []
        page: str | None = None
        while len(ids) < limit:
            params = {"q": query, "maxResults": min(100, limit - len(ids))}
            if page:
                params["pageToken"] = page
            reply = self._get("messages", **params)
            ids += [m["id"] for m in reply.get("messages", [])]
            page = reply.get("nextPageToken")
            if not page:
                break
        return ids

    def message(self, message_id: str) -> dict[str, Any]:
        return self._get(f"messages/{message_id}", format="full")

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        data = self._get(f"messages/{message_id}/attachments/{attachment_id}")["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    out, stack = [], [payload]
    while stack:
        part = stack.pop()
        out.append(part)
        stack.extend(part.get("parts") or [])
    return out


def _header(message: dict[str, Any], name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _text(message: dict[str, Any]) -> str:
    """The plain text of an email (HTML stripped if there is no plain part)."""
    plain, rich = [], []
    for part in _parts(message.get("payload", {})):
        data = (part.get("body") or {}).get("data")
        if not data or part.get("filename"):
            continue
        text = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")
        (plain if part.get("mimeType") == "text/plain" else rich if part.get("mimeType") == "text/html" else []).append(text)
    if plain:
        return " ".join(plain)
    return html.unescape(re.sub(r"<[^>]+>", " ", " ".join(rich)))


def _sender_name(message: dict[str, Any]) -> str:
    name, address = parseaddr(_header(message, "From"))
    return (name or address.split("@")[-1] or "Email").strip()


def _safe(name: str) -> str:
    """A file or folder name that is safe on Windows and cannot leave the inbox."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return cleaned[:80] or "statement"


def fetch(gmail: Gmail, inbox: Path, state_path: Path, *, statement_query: str = STATEMENT_QUERY,
          alert_query: str = ALERT_QUERY, now: datetime | None = None) -> FetchResult:
    """Save new statement attachments and alert emails into ``inbox``. Each email is handled once."""
    seen: set[str] = set(json.loads(state_path.read_text(encoding="utf-8"))) if state_path.exists() else set()
    result = FetchResult()
    inbox.mkdir(parents=True, exist_ok=True)

    for message_id in gmail.search(statement_query):
        if message_id in seen:
            result.skipped += 1
            continue
        message = gmail.message(message_id)
        folder = inbox / _safe(_sender_name(message))
        for part in _parts(message.get("payload", {})):
            filename, attachment_id = part.get("filename") or "", (part.get("body") or {}).get("attachmentId")
            if not attachment_id or not filename.lower().endswith(STATEMENT_EXTENSIONS):
                continue
            if (part.get("body") or {}).get("size", 0) > MAX_IMPORT_BYTES:
                continue
            folder.mkdir(parents=True, exist_ok=True)
            target = folder / f"{message_id[:8]}-{_safe(filename)}"
            target.write_bytes(gmail.attachment(message_id, attachment_id))
            result.statements.append(target.relative_to(inbox).as_posix())
        seen.add(message_id)

    rows = []
    for message_id in gmail.search(alert_query):
        if message_id in seen:
            result.skipped += 1
            continue
        message = gmail.message(message_id)
        seen.add(message_id)
        row = read_alert(_sender_name(message), int(message.get("internalDate", "0")), _text(message), source="Email")
        if row is None:
            result.skipped += 1
            continue
        rows.append(row)
    if rows:
        stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
        target = inbox / f"gmail-alerts-{stamp}.csv"
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)
        target.write_text(buffer.getvalue(), encoding="utf-8")
        result.alerts, result.alerts_file = len(rows), target.name

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    return result
