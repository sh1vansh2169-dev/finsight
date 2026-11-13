"""Routes for the FinSight phone app: pairing phones and receiving their SMS alerts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from pydantic import BaseModel, ConfigDict, Field

from moneyos.api.deps import current_user
from moneyos.api.routes import SessionDep
from moneyos.db.tables import User
from moneyos.db.tenancy import system_session, user_session
from moneyos.services import phone

DEVICE_HEADER = "X-FinSight-Device"
CurrentUser = Annotated[User, Depends(current_user)]

# Signed-in routes (the web app, including inside the phone app).
router = APIRouter(prefix="/phone", tags=["phone"])
# The phone's own route: authenticated by the phone key, not a sign-in.
device_router = APIRouter(prefix="/phone", tags=["phone"])


class DeviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(default="Phone", min_length=1, max_length=100)


class DeviceOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    last_seen_at: datetime | None


class PairedOut(DeviceOut):
    key: str = Field(description="Shown once. Only the phone app keeps it.")


class AlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str = Field(min_length=1, max_length=40)
    timestamp_ms: int = Field(gt=0)
    body: str = Field(min_length=1, max_length=2000)


class AlertsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alerts: list[AlertIn] = Field(min_length=1, max_length=phone.MAX_ALERTS_PER_CALL)


class ReceivedOut(BaseModel):
    received: int
    kept: int = Field(description="New bank or UPI transaction alerts now waiting for review")
    batch_id: int | None


def _out(d) -> DeviceOut:
    return DeviceOut(id=d.id, name=d.name, created_at=d.created_at, last_seen_at=d.last_seen_at)


@router.post("/devices", response_model=PairedOut, status_code=status.HTTP_201_CREATED)
def pair(body: DeviceIn, session: SessionDep, user: CurrentUser) -> PairedOut:
    """Pair the phone this request comes from. The key in the reply is shown once."""
    device, key = phone.create_device(session, user, body.name)
    return PairedOut(**_out(device).model_dump(), key=key)


@router.get("/devices", response_model=list[DeviceOut])
def devices(session: SessionDep, user: CurrentUser) -> list[DeviceOut]:
    return [_out(d) for d in phone.list_devices(session, user)]


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(device_id: int, session: SessionDep, user: CurrentUser) -> None:
    """The phone's key stops working at once."""
    phone.revoke_device(session, user, device_id)


@device_router.post("/alerts", response_model=ReceivedOut)
def alerts(body: AlertsIn, request: Request,
           key: str = Header(alias=DEVICE_HEADER, min_length=10, max_length=100)) -> ReceivedOut:
    """SMS alerts from a paired phone. Only transaction alerts are kept, for the user to review."""
    factory = request.app.state.session_factory
    with system_session(factory) as session:
        user_id = phone.device_owner(session, key)
    with user_session(factory, user_id) as session:
        result = phone.receive_alerts(session, [(a.sender, a.timestamp_ms, a.body) for a in body.alerts],
                                      request.app.state.rules)
    return ReceivedOut(received=result.received, kept=result.kept, batch_id=result.batch_id)
