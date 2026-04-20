from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from langchain.agents.middleware.types import AgentMiddleware
except Exception:  # pragma: no cover - test stubs do not expose langchain internals
    AgentMiddleware = object  # type: ignore[assignment]
from langchain_core.tools import BaseTool


@dataclass(frozen=True)
class RuntimeToolBinding:
    tool: BaseTool
    risk_tags: tuple[str, ...] = ()
    interrupt_on_call: bool = False
    source: str = "project"
    server_name: str | None = None

    @property
    def name(self) -> str:
        return self.tool.name


class ToolAllowlistMiddleware(AgentMiddleware):
    def __init__(self, *, allowed: frozenset[str]) -> None:
        self._allowed = allowed

    def wrap_model_call(
        self,
        request: Any,
        handler,
    ) -> Any:
        return handler(request.override(tools=self._filter(request.tools)))

    async def awrap_model_call(
        self,
        request: Any,
        handler,
    ) -> Any:
        return await handler(request.override(tools=self._filter(request.tools)))

    def _filter(self, tools: list[Any]) -> list[Any]:
        return [tool for tool in tools if getattr(tool, "name", None) in self._allowed]
