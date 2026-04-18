from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from pydantic import BaseModel
from langgraph.types import Interrupt


@dataclass
class PendingApproval:
    approval_id: str
    session_id: str
    turn_id: str
    interrupt_id: str
    request: Any


@dataclass
class SessionRuntimeHandle:
    session_id: str
    profile_name: str
    auto_approve: bool
    runtime: Any
    checkpoint_context: Any | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active_turn_id: str | None = None
    active_task: asyncio.Task[Any] | None = None

    async def aclose(self) -> None:
        if hasattr(self.runtime, "mcp_runtime"):
            self.runtime.mcp_runtime.close()
        if self.checkpoint_context is not None:
            if hasattr(self.checkpoint_context, "__aexit__"):
                await self.checkpoint_context.__aexit__(None, None, None)
            elif hasattr(self.checkpoint_context, "__exit__"):
                self.checkpoint_context.__exit__(None, None, None)


def interrupt_payload(interrupt: Interrupt) -> dict[str, Any]:
    return {"id": interrupt.id, "value": to_event_data(interrupt.value)}


def extract_assistant_text(payload: Any) -> str:
    messages = _payload_messages(payload)
    for message in reversed(messages):
        role = getattr(message, "type", None) or getattr(message, "role", None)
        if role not in {"ai", "assistant"}:
            continue
        return _message_text(message)
    return ""


def extract_text_chunk(message: Any) -> str:
    return _message_text(message)


def _payload_messages(payload: Any) -> list[Any]:
    if isinstance(payload, dict):
        messages = payload.get("messages", [])
        return list(messages) if isinstance(messages, list) else []
    messages = getattr(payload, "messages", [])
    return list(messages) if isinstance(messages, list) else []


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    return "\n".join(part for part in parts if part).strip()


def to_event_data(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return _convert_mapping(asdict(value))
    if isinstance(value, dict):
        return _convert_mapping(value)
    if isinstance(value, (list, tuple, set)):
        return [to_event_data(item) for item in value]
    return {
        "type": type(value).__name__,
        "repr": repr(value),
    }


def _convert_mapping(value: dict[Any, Any]) -> dict[str, Any]:
    return {str(key): to_event_data(item) for key, item in value.items()}
