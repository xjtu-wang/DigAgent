from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

from tests.runtime_import_stubs import Command, empty_checkpoint


@dataclass
class FakeMessage:
    content: str
    type: str = "assistant"
    role: str = "assistant"


@dataclass
class FakeInterrupt:
    id: str
    value: Any


@dataclass
class FakeSnapshot:
    values: Any
    interrupts: tuple[Any, ...] = ()


class FakeGraph:
    def to_json(self, *, with_schemas: bool = True) -> dict[str, Any]:
        return {"kind": "fake-graph", "with_schemas": with_schemas}


class DummyMcpRuntime:
    def close(self) -> None:
        return None


class FakeAgent:
    def __init__(self) -> None:
        self.snapshots: dict[str, FakeSnapshot] = {}
        self.slow_gate = asyncio.Event()

    async def astream(self, input_value: Any, config: dict[str, Any], **_: Any):
        thread_id = config["configurable"]["thread_id"]
        if isinstance(input_value, Command):
            yield ("updates", {"resumed": True})
            self.snapshots[thread_id] = FakeSnapshot({"messages": [FakeMessage("approved")]})
            return
        message = input_value["messages"][0].content
        if message == "slow":
            yield ("updates", {"phase": "slow-start"})
            await self.slow_gate.wait()
            self.snapshots[thread_id] = FakeSnapshot({"messages": [FakeMessage("slow-done")]})
            yield ("updates", {"phase": "slow-end"})
            return
        if message == "needs approval":
            interrupt = FakeInterrupt("interrupt-1", {"action_requests": [{"tool": "edit_file"}]})
            self.snapshots[thread_id] = FakeSnapshot({"messages": []}, interrupts=(interrupt,))
            yield ("updates", {"phase": "approval"})
            return
        reply = f"reply:{message}"
        self.snapshots[thread_id] = FakeSnapshot({"messages": [FakeMessage(reply)]})
        yield ("updates", {"phase": "done", "reply": reply})

    async def aget_state(self, config: dict[str, Any]):
        thread_id = config["configurable"]["thread_id"]
        return self.snapshots.get(thread_id, FakeSnapshot(empty_checkpoint()))

    def get_graph(self, config: dict[str, Any]):
        del config
        return FakeGraph()


def fake_runtime_factory(agent: FakeAgent):
    async def _build_runtime(**_: Any):
        return SimpleNamespace(
            agent=agent,
            backend=None,
            checkpointer=None,
            checkpoint_context=None,
            checkpoint_path="fake",
            mcp_runtime=DummyMcpRuntime(),
            skill_sources=[],
            memory_sources=[],
            tool_names=[],
        )

    return _build_runtime


async def wait_for_turn_count(manager, session_id: str, expected: int) -> None:
    for _ in range(50):
        if len(manager.list_turns(session_id)) >= expected:
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"turn count did not reach {expected}")
