from __future__ import annotations

import importlib
import sys
import types
from dataclasses import dataclass
from typing import Any


@dataclass
class Command:
    resume: Any = None


@dataclass
class Interrupt:
    id: str
    value: Any


@dataclass
class HumanMessage:
    content: str


@dataclass
class BuiltRuntime:
    agent: Any
    backend: Any = None
    checkpointer: Any = None
    checkpoint_context: Any = None
    checkpoint_path: str = "fake"
    mcp_runtime: Any = None
    skill_sources: list[str] | None = None
    memory_sources: list[str] | None = None
    tool_names: list[str] | None = None


def empty_checkpoint() -> dict[str, dict[str, Any]]:
    return {"channel_values": {}, "channel_versions": {}}


async def _unexpected_build_runtime(**_: Any):
    raise AssertionError("build_runtime must be monkeypatched in tests")


def _package(name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__path__ = []
    for key, value in attrs.items():
        setattr(module, key, value)
    return module


def load_runtime_api(monkeypatch) -> tuple[type[Any], Any]:
    for name in [
        "digagent.api",
        "digagent.runtime",
        "digagent.deepagents_manager",
        "digagent.deepagents_runtime.manager_ops",
        "digagent.deepagents_runtime.factory",
    ]:
        sys.modules.pop(name, None)

    messages_module = types.ModuleType("langchain_core.messages")
    messages_module.HumanMessage = HumanMessage
    types_module = types.ModuleType("langgraph.types")
    types_module.Command = Command
    types_module.Interrupt = Interrupt
    factory_module = types.ModuleType("digagent.deepagents_runtime.factory")
    factory_module.BuiltRuntime = BuiltRuntime
    factory_module.build_runtime = _unexpected_build_runtime

    monkeypatch.setitem(sys.modules, "langchain_core", _package("langchain_core", messages=messages_module))
    monkeypatch.setitem(sys.modules, "langchain_core.messages", messages_module)
    monkeypatch.setitem(sys.modules, "langgraph", _package("langgraph", types=types_module))
    monkeypatch.setitem(sys.modules, "langgraph.types", types_module)
    monkeypatch.setitem(sys.modules, "digagent.deepagents_runtime.factory", factory_module)

    runtime_module = importlib.import_module("digagent.runtime")
    api_module = importlib.import_module("digagent.api")
    return runtime_module.TurnManager, api_module.create_app
