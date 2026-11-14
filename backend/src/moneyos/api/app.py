"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse

from moneyos import __version__
from moneyos.api import analytics as analytics_api
from moneyos.api import auth as auth_api
from moneyos.api import majra as majra_api
from moneyos.api import ml as ml_api
from moneyos.api import assistant as assistant_api
from moneyos.api import phone as phone_api
from moneyos.api import planning as planning_api
from moneyos.api import webapp
from moneyos.api.protect import Protect
from moneyos.api.deps import current_user
from moneyos.api.routes import router
from moneyos.api.schemas import HealthOut
from moneyos.config import DataMode, Settings
from moneyos.db.session import init_db
from moneyos.domain.classify import load_rules
from moneyos.domain.importer import SchemaError
from moneyos.services.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
)
from moneyos.services.auth import AuthError, TooManyAttempts

_ERROR_STATUS = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    InvalidRequestError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    SchemaError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    PayloadTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
    AuthError: status.HTTP_401_UNAUTHORIZED,
    TooManyAttempts: status.HTTP_429_TOO_MANY_REQUESTS,
}


def _start_gmail_fetcher(settings: Settings, every_seconds: float = 30 * 60):
    """Fetch from Gmail into the inbox now and then every 30 minutes; returns an event that stops it."""
    import logging
    import os
    import threading

    from moneyos import gmail

    log = logging.getLogger("moneyos.gmail")
    stop = threading.Event()

    def run():
        while not stop.is_set():
            try:
                result = gmail.fetch(
                    gmail.Gmail(settings.gmail_dir / "token.json"), settings.watch_dir, settings.gmail_dir / "seen.json",
                    statement_query=os.environ.get("MONEYOS_GMAIL_STATEMENTS") or gmail.STATEMENT_QUERY,
                    alert_query=os.environ.get("MONEYOS_GMAIL_ALERTS") or gmail.ALERT_QUERY)
                if result.statements or result.alerts:
                    log.info("gmail: %d statement file(s), %d alert(s) saved to the inbox",
                             len(result.statements), result.alerts)
            except gmail.GmailError as error:
                log.warning("gmail: %s", error)
            except Exception:
                log.exception("gmail: fetch failed")
            stop.wait(every_seconds)

    threading.Thread(target=run, name="finsight-gmail", daemon=True).start()
    return stop


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watcher = None
        if settings.watch_dir is not None:
            from moneyos.services.inbox import Inbox, InboxWatcher

            watcher = InboxWatcher(Inbox(settings.watch_dir, app.state.session_factory, app.state.rules,
                                         user_email=settings.watch_user))
            watcher.start()
        app.state.inbox_watcher = watcher
        stop_gmail = None
        if settings.gmail_fetch and settings.watch_dir is not None:
            stop_gmail = _start_gmail_fetcher(settings)
        yield
        if stop_gmail is not None:
            stop_gmail.set()
        if watcher is not None:
            watcher.stop()

    app = FastAPI(
        title="FinSight API",
        version=__version__,
        description="Local personal-finance ledger. Totals are recorded totals, not bank balances.",
        lifespan=lifespan,
    )
    app.state.inbox_watcher = None
    app.state.settings = settings
    # Size limits and protective headers on every request (api/protect.py).
    app.add_middleware(Protect)
    app.state.rules = load_rules(settings.rules_file)
    app.state.session_factory = init_db(settings.database_url, settings.data_mode)

    for error_type, code in _ERROR_STATUS.items():

        def handler(_request: Request, error: Exception, code: int = code) -> JSONResponse:
            # Service error messages are written for users and never include
            # transaction contents beyond what the caller already sent.
            headers = {"WWW-Authenticate": "Bearer"} if code == status.HTTP_401_UNAUTHORIZED else None
            return JSONResponse({"detail": str(error)}, status_code=code, headers=headers)

        app.add_exception_handler(error_type, handler)

    @app.get("/health", response_model=HealthOut, tags=["meta"])
    def health() -> HealthOut:
        return HealthOut(
            version=__version__,
            data_mode=settings.data_mode.value,
            sample_data=settings.data_mode == DataMode.SAMPLE,
        )

    app.include_router(auth_api.router, prefix="/api/v1")
    # The phone app's alert route: authenticated by the phone's own key, not a sign-in.
    app.include_router(phone_api.device_router, prefix="/api/v1")
    # Everything else needs a signed-in user, and sees only that user's data.
    signed_in = [Depends(current_user)]
    for module_router in (router, analytics_api.router, majra_api.router, ml_api.router, planning_api.router,
                          assistant_api.router, phone_api.router):
        app.include_router(module_router, prefix="/api/v1", dependencies=signed_in)
    # Last: the web app's catch-all route must not shadow any API route.
    webapp.mount(app, settings.frontend_dist)
    return app
