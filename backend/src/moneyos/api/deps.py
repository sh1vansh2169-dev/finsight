"""FastAPI dependencies: the signed-in user and their database session."""

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

_bearer = HTTPBearer(auto_error=False, description="The token returned by /api/v1/auth/login.")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rules(request: Request) -> Rules:
    return request.app.state.rules


def get_system_session(request: Request) -> Iterator[Session]:
    """Unrestricted session: only for signing in and account management."""
    with system_session(request.app.state.session_factory) as session:
        yield session


def bearer_token(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise auth.AuthError("please sign in")
    return credentials.credentials


def current_user(request: Request, token: str = Depends(bearer_token)) -> User:
    with system_session(request.app.state.session_factory) as session:
        user = auth.user_for_token(session, token)
        session.expunge(user)
        return user


def get_session(request: Request, user: User = Depends(current_user)) -> Iterator[Session]:
    """A session that can only ever see the signed-in user's records."""
    with user_session(request.app.state.session_factory, user.id) as session:
        yield session
