"""FastAPI dependencies: database sessions and the optional API token."""

from __future__ import annotations

import hmac
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from moneyos.config import Settings
from moneyos.domain.classify import Rules

_bearer = HTTPBearer(auto_error=False)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rules(request: Request) -> Rules:
    return request.app.state.rules


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def require_token(
    settings: Settings = Depends(get_settings),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    """Enforce MONEYOS_API_TOKEN when it is set; allow everything when it is not.

    Running without a token is only acceptable on a loopback address; the
    ``serve`` command refuses other hosts unless a token is configured.
    """
    if settings.api_token is None:
        return
    supplied = credentials.credentials if credentials else ""
    if not hmac.compare_digest(supplied.encode(), settings.api_token.encode()):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
