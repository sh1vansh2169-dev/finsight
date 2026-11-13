"""Routes for the assistant: a local model that answers from FinSight's own figures."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from moneyos.api.routes import SessionDep, SettingsDep
from moneyos.assistant import agent
from moneyos.assistant.ollama import AssistantUnavailable, OllamaClient

router = APIRouter(prefix="/assistant", tags=["assistant"])


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class AskIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=10)


class ToolCallOut(BaseModel):
    name: str
    arguments: Any
    result: Any


class AnswerOut(BaseModel):
    answer: str
    unverified_figures: list[str] = Field(
        description="Figures in the answer that no tool returned; shown to the user as unverified.")
    tool_calls: list[ToolCallOut]
    stopped_early: bool
    model: str


class StatusOut(BaseModel):
    available: bool
    model: str
    message: str


def _client(request: Request) -> OllamaClient:
    """The model client; tests replace it via ``app.state.assistant_model``."""
    settings = request.app.state.settings
    override = getattr(request.app.state, "assistant_model", None)
    if override is not None:
        return override
    return OllamaClient(settings.ollama_url, settings.assistant_model, allow_remote=settings.assistant_allow_remote)


@router.get("/status", response_model=StatusOut)
def assistant_status(request: Request, settings: SettingsDep) -> StatusOut:
    """Whether the local model is installed and running."""
    try:
        client = _client(request)
        if isinstance(client, OllamaClient):
            installed = client.installed_models()
            if not any(m == settings.assistant_model or m.split(":")[0] == settings.assistant_model for m in installed):
                return StatusOut(available=False, model=settings.assistant_model,
                                 message=f"Ollama is running, but the model is not installed. "
                                         f"Run: ollama pull {settings.assistant_model}")
    except AssistantUnavailable as error:
        return StatusOut(available=False, model=settings.assistant_model, message=str(error).capitalize())
    return StatusOut(available=True, model=settings.assistant_model, message="Ready")


@router.post("/ask", response_model=AnswerOut)
def ask(body: AskIn, request: Request, session: SessionDep, settings: SettingsDep) -> AnswerOut:
    """Answer a question from the user's recorded data. Read-only: the assistant cannot change anything."""
    try:
        client = _client(request)
        result = agent.ask(session, settings, client, body.question, [t.model_dump() for t in body.history])
    except AssistantUnavailable as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(error).capitalize()) from None
    return AnswerOut(answer=result.answer, unverified_figures=result.unverified_figures,
                     tool_calls=[ToolCallOut(**c) for c in result.tool_calls],
                     stopped_early=result.stopped_early, model=settings.assistant_model)
