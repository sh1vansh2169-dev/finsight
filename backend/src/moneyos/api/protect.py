"""Protections applied to every request, before any route code runs.

* **Size limits.** A request body larger than its limit is refused with 413 before
  it is read into memory. Without this, a client on the home network (``serve
  --phone``) could send a huge body to an endpoint that only checks its key or
  password after reading the body, and exhaust memory.
* **Headers.** Every response says nosniff, no referrer and no framing; API
  responses (financial data) also say ``Cache-Control: no-store`` so browsers
  and phones never keep a copy.
"""

from __future__ import annotations

import json

from moneyos.domain.sms import MAX_SMS_BYTES

UPLOAD_PATH = "/api/v1/imports/preview"
UPLOAD_LIMIT = MAX_SMS_BYTES + 1024 * 1024  # the largest statement (an SMS backup) plus form overhead
BODY_LIMIT = 4 * 1024 * 1024                # every other request: JSON, at most a few hundred KB in practice

BASE_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
]


class TooLarge(Exception):
    pass


def limit_for(path: str) -> int:
    return UPLOAD_LIMIT if path == UPLOAD_PATH else BODY_LIMIT


class Protect:
    """ASGI middleware: body size limits and protective headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limit = limit_for(path)
        api = path.startswith("/api/")
        started = False

        async def send_with_headers(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                present = {name.lower() for name, _ in message.get("headers", [])}
                extra = [(n, v) for n, v in BASE_HEADERS if n not in present]
                if api and b"cache-control" not in present:
                    extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        async def refuse():
            body = json.dumps({"detail": f"request is larger than {limit // (1024 * 1024)} MB"}).encode()
            await send_with_headers({"type": "http.response.start", "status": 413,
                                     "headers": [(b"content-type", b"application/json"),
                                                 (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        declared = dict(scope.get("headers", [])).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    return await refuse()
            except ValueError:
                return await refuse()

        received = 0

        async def counted_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:  # a body sent without (or lying about) its length
                    raise TooLarge
            return message

        try:
            await self.app(scope, counted_receive, send_with_headers)
        except TooLarge:
            if not started:
                await refuse()
