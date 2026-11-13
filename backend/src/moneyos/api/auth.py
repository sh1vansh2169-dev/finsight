"""Sign-up, sign-in, sign-out and account deletion."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from moneyos.api.deps import SESSION_COOKIE, bearer_token, current_user, get_settings, get_system_session
from moneyos.config import Settings
from moneyos.db.tables import User, utc_now
from moneyos.services import auth
from moneyos.services.errors import ConflictError

router = APIRouter(prefix="/auth", tags=["account"])
SystemSession = Annotated[Session, Depends(get_system_session)]


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)
    use_cookie: bool = Field(
        default=False,
        description="For the web app: keep the session in an httpOnly cookie and do not return the token.",
    )


class UserOut(BaseModel):
    id: int
    email: str
    created_at: datetime


class SignedIn(BaseModel):
    token: str | None = Field(description="Send as 'Authorization: Bearer <token>'. Shown once; null with use_cookie.")
    expires_at: datetime
    user: UserOut


class DeleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=200)
    confirm: bool = Field(description="Must be true: everything you stored is deleted and cannot be recovered.")


def _out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, created_at=user.created_at)


def _signed_in(user: User, token: str, use_cookie: bool, request: Request, response: Response) -> SignedIn:
    expires = utc_now() + timedelta(days=auth.SESSION_DAYS)
    if use_cookie:
        response.set_cookie(
            SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="strict",
            secure=request.url.scheme == "https", path="/api",
        )
        return SignedIn(token=None, expires_at=expires, user=_out(user))
    return SignedIn(token=token, expires_at=expires, user=_out(user))


@router.post("/register", response_model=SignedIn, status_code=status.HTTP_201_CREATED)
def register(body: Credentials, request: Request, response: Response, session: SystemSession,
             settings: Annotated[Settings, Depends(get_settings)]):
    """Create an account. The first account can always be created; later ones only if sign-up is allowed."""
    if auth.user_count(session) and not settings.allow_signup:
        raise ConflictError("sign-up is closed on this FinSight; ask its owner to set MONEYOS_ALLOW_SIGNUP=true")
    auth.create_user(session, body.email, body.password)
    user, token = auth.sign_in(session, body.email, body.password)
    return _signed_in(user, token, body.use_cookie, request, response)


@router.post("/login", response_model=SignedIn)
def login(body: Credentials, request: Request, response: Response, session: SystemSession):
    user, token = auth.sign_in(session, body.email, body.password)
    return _signed_in(user, token, body.use_cookie, request, response)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, session: SystemSession, token: Annotated[str, Depends(bearer_token)]) -> None:
    auth.sign_out(session, token)
    response.delete_cookie(SESSION_COOKIE, path="/api")


@router.get("/me", response_model=UserOut)
def me(user: Annotated[User, Depends(current_user)]):
    return _out(user)


@router.get("/status")
def signup_status(session: SystemSession, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """Whether a new account can be created here (so the app can show or hide 'Create account')."""
    return {"signup_open": auth.user_count(session) == 0 or settings.allow_signup}


@router.post("/delete-account")
def delete_account(body: DeleteIn, response: Response, session: SystemSession,
                   user: Annotated[User, Depends(current_user)]) -> dict:
    """Permanently delete your account and every record you stored. Needs your password and confirm=true."""
    if not body.confirm:
        raise auth.AuthError("confirm must be true to delete everything")
    deleted = auth.delete_account(session, session.get(User, user.id), body.password)
    response.delete_cookie(SESSION_COOKIE, path="/api")
    return {"deleted": True, "rows_deleted": deleted}
