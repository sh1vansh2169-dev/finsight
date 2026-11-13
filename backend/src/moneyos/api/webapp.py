"""Serve the built web app (frontend/dist) from the API server, same-origin.

Same-origin matters: the session cookie is SameSite=Strict and the API
allows no cross-origin requests. Every page gets a strict Content Security
Policy (scripts only from this server), so injected markup cannot run code.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
_NOT_APP = ("api/", "docs", "redoc", "openapi.json", "health")


def mount(app: FastAPI, dist: Path) -> bool:
    """Serve ``dist`` if it holds a build. Returns whether it was mounted."""
    index = dist / "index.html"
    if not index.is_file():
        return False
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def web_app(path: str) -> FileResponse:
        if path.startswith(_NOT_APP):
            raise HTTPException(status_code=404)
        candidate = (root / path).resolve()
        inside = candidate == root or root in candidate.parents
        if path and inside and candidate.is_file():
            return FileResponse(candidate, headers=SECURITY_HEADERS)
        # Client-side routes (/transactions, /money-majra, ...) all load the app.
        return FileResponse(index, headers={**SECURITY_HEADERS, "Cache-Control": "no-cache"})

    return True
