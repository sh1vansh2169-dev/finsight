"""A minimal client for a local Ollama server (https://ollama.com), standard library only.

Uses Ollama's chat endpoint with tool calling. Written against Ollama's
documented API; tested in MoneyOS against a stand-in server, not a real model.
"""

from __future__ import annotations

import ipaddress
import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

TIMEOUT_SECONDS = 120  # a small local model on a laptop CPU can take a while


class AssistantUnavailable(RuntimeError):
    """The model cannot be reached or is not set up; the message says what to do."""


def is_local(url: str) -> bool:
    """True if ``url`` points at this machine."""
    host = urlparse(url).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class OllamaClient:
    def __init__(self, url: str, model: str, *, allow_remote: bool = False):
        if urlparse(url).scheme not in ("http", "https"):
            raise AssistantUnavailable("MONEYOS_OLLAMA_URL must start with http:// or https://")
        if not allow_remote and not is_local(url):
            # The model reads the user's money data; it must not leave the machine by accident.
            raise AssistantUnavailable(
                "the assistant only talks to a model on this computer. To use another machine, set "
                "MONEYOS_ASSISTANT_ALLOW_REMOTE=true (your financial data will be sent there)"
            )
        self.url, self.model = url.rstrip("/"), model

    def _post(self, path: str, body: dict[str, Any] | None = None, *, method: str = "POST") -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.url}{path}", data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - checked URL
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            with error:  # an HTTPError holds the open response; close it
                detail = error.read().decode(errors="replace")[:300]
            if error.code == 404 and "not found" in detail.lower():
                raise AssistantUnavailable(
                    f"the model {self.model!r} is not installed. Run: ollama pull {self.model}") from None
            raise AssistantUnavailable(f"the model server answered {error.code}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AssistantUnavailable(
                f"no model server at {self.url} ({getattr(error, 'reason', error)}). "
                "Install Ollama from https://ollama.com and start it") from None
        except json.JSONDecodeError:
            raise AssistantUnavailable("the model server sent something that is not JSON") from None

    def installed_models(self) -> list[str]:
        return [m.get("name", "") for m in self._post("/api/tags", method="GET").get("models", [])]

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        """One reply: ``{"content": str, "tool_calls": [{"name", "arguments"}]}``."""
        reply = self._post("/api/chat", {
            "model": self.model, "messages": messages, "tools": tools, "stream": False,
            "options": {"temperature": 0},  # repeatable answers; figures come from tools anyway
        })
        message = reply.get("message") or {}
        calls = []
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, str):  # some models send arguments as a JSON string
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"_unparsed": arguments}
            calls.append({"name": function.get("name", ""), "arguments": arguments or {}})
        return {"content": message.get("content") or "", "tool_calls": calls}
