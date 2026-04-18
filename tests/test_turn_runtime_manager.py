from __future__ import annotations

import asyncio

import pytest

from digagent.models import Scope
from tests.runtime_import_stubs import empty_checkpoint
from tests.runtime_turn_fakes import FakeAgent, fake_runtime_factory, wait_for_turn_count


@pytest.mark.asyncio
async def test_sqlite_checkpointer_round_trip(tmp_path) -> None:
    from langgraph.checkpoint.sqlite import SqliteSaver

    db_path = tmp_path / "checkpoints.sqlite"
    config = {"configurable": {"thread_id": "thread-1", "checkpoint_ns": ""}}
    checkpoint = empty_checkpoint()
    checkpoint["id"] = "checkpoint-1"
    checkpoint["ts"] = "2026-04-18T00:00:00Z"
    checkpoint["channel_values"] = {"messages": ["hello"]}
    checkpoint["channel_versions"] = {"messages": "0001"}
    with SqliteSaver.from_conn_string(str(db_path)) as saver:
        saved = saver.put(config, checkpoint, {"step": 1}, {"messages": "0001"})
        saver.put_writes(saved, [("messages", ["hello"])], task_id="task-1")
        loaded = saver.get_tuple(saved)
    assert loaded is not None
    assert loaded.metadata["step"] == 1
    assert loaded.checkpoint["channel_values"]["messages"] == ["hello"]
    assert loaded.pending_writes == [("task-1", "messages", ["hello"])]


@pytest.mark.asyncio
async def test_handle_message_persists_turn_and_events(manager, monkeypatch) -> None:
    agent = FakeAgent()
    monkeypatch.setattr("digagent.deepagents_runtime.session_ops.build_runtime", fake_runtime_factory(agent))
    session = manager.create_session("turn-runtime", "sisyphus-default", Scope())
    session, result = await manager.handle_message(
        session_id=session.session_id,
        content="hello",
        profile_name="sisyphus-default",
        scope=Scope(),
        auto_approve=True,
    )
    turn = manager.get_turn(result.turn_id)
    session_record = manager.storage.load_session(session.session_id)
    messages = manager.list_messages(session.session_id)
    assert session.active_turn_id is None
    assert session_record.turn_ids == [turn.turn_id]
    assert turn.status == "completed"
    assert turn.trigger_message_id == messages[0].message_id
    assert result.assistant_message == "reply:hello"
    assert [message.turn_id for message in messages] == [turn.turn_id, turn.turn_id]
    assert [event.type for event in manager.load_turn_event_history(turn.turn_id)] == [
        "turn_started",
        "langgraph_updates",
        "assistant_message",
        "completed",
    ]


@pytest.mark.asyncio
async def test_new_message_supersedes_active_turn(manager, monkeypatch) -> None:
    agent = FakeAgent()
    monkeypatch.setattr("digagent.deepagents_runtime.session_ops.build_runtime", fake_runtime_factory(agent))
    session = manager.create_session("supersede-turn", "sisyphus-default", Scope())
    first_task = asyncio.create_task(
        manager.handle_message(
            session_id=session.session_id,
            content="slow",
            profile_name="sisyphus-default",
            scope=Scope(),
            auto_approve=True,
        )
    )
    await wait_for_turn_count(manager, session.session_id, 1)
    _, second = await manager.handle_message(
        session_id=session.session_id,
        content="fast",
        profile_name="sisyphus-default",
        scope=Scope(),
        auto_approve=True,
    )
    _, first = await first_task
    first_turn = manager.get_turn(first.turn_id)
    second_turn = manager.get_turn(second.turn_id)
    assert "Superseded by turn" in (first.reason or "")
    assert first_turn.status == "superseded"
    assert second_turn.status == "completed"
    assert second.assistant_message == "reply:fast"


@pytest.mark.asyncio
async def test_approve_resumes_pending_turn(manager, monkeypatch) -> None:
    agent = FakeAgent()
    monkeypatch.setattr("digagent.deepagents_runtime.session_ops.build_runtime", fake_runtime_factory(agent))
    session = manager.create_session("approve-turn", "sisyphus-default", Scope())
    _, result = await manager.handle_message(
        session_id=session.session_id,
        content="needs approval",
        profile_name="sisyphus-default",
        scope=Scope(),
        auto_approve=False,
    )
    approval = await manager.approve(result.approval_ids[0], approved=True)
    turn = manager.get_turn(result.turn_id)
    assert approval.status == "approved"
    assert turn.status == "completed"
    assert any(event.type == "approval_resolved" for event in manager.load_turn_event_history(turn.turn_id))
