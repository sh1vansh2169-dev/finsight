"""FastAPI dependencies: the signed-in user and their database session.

Two ways to authenticate:

* ``Authorization: Bearer <token>``: for scripts and the interactive docs.
* The ``moneyos_session`` cookie: for the web app. It is httpOnly (page
  scripts cannot read it) and SameSite=Strict. Requests that change data
  with a cookie must also send ``X-MoneyOS-CSRF: 1``; another website can
  neither read the cookie nor add that header, which blocks cross-site
  request forgery.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from moneyos.config import Settings
from moneyos.db.tables import User
from moneyos.db.tenancy import system_session, user_session
from moneyos.domain.classify import Rules
from moneyos.services import auth

SESSION_COOKIE = "moneyos_session"
CSRF_HEADER = "X-MoneyOS-CSRF"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_bearer = HTTPBearer(auto_error=False, description="The token returned by /api/v1/auth/login.")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rules(request: Request) -> Rules:
    return request.app.state.rules


def get_system_session(request: Request) -> Iterator[Session]:
    """Unrestricted session: only for signing in and account management."""
    with system_session(request.app.state.session_factory) as session:
        yield session


def bearer_token(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    """The session token from the Authorization header, else from the cookie (with the CSRF check)."""
    if credentials is not None and credentials.scheme.lower() == "bearer" and credentials.credentials:
        return credentials.credentials
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        if request.method not in _SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise auth.AuthError(f"missing {CSRF_HEADER} header")
        return cookie
    raise auth.AuthError("please sign in")


def current_user(request: Request, token: str = Depends(bearer_token)) -> User:
    with system_session(request.app.state.session_factory) as session:
        user = auth.user_for_token(session, token)
        session.expunge(user)
        return user


def get_session(request: Request, user: User = Depends(current_user)) -> Iterator[Session]:
    """A session that can only ever see the signed-in user's records."""
    with user_session(request.app.state.session_factory, user.id) as session:
        yield session
