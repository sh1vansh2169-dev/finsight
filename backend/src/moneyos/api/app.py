"""FastAPI application factory."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse

from moneyos import __version__
from moneyos.api import analytics as analytics_api
from moneyos.api import auth as auth_api
from moneyos.api import majra as majra_api
from moneyos.api import ml as ml_api
from moneyos.api import planning as planning_api
from moneyos.api import webapp
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


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(
        title="MoneyOS API",
        version=__version__,
        description="Local personal-finance ledger. Totals are recorded totals, not bank balances.",
    )
    app.state.settings = settings
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
    # Everything else needs a signed-in user, and sees only that user's data.
    signed_in = [Depends(current_user)]
    for module_router in (router, analytics_api.router, majra_api.router, ml_api.router, planning_api.router):
        app.include_router(module_router, prefix="/api/v1", dependencies=signed_in)
    # Last: the web app's catch-all route must not shadow any API route.
    webapp.mount(app, settings.frontend_dist)
    return app
