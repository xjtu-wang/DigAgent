from __future__ import annotations

import asyncio

import pytest

from digagent.models import RuntimeBudget, Scope, TurnEvent
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
    assert [message.speaker_profile for message in messages] == ["user", "sisyphus-default"]
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


@pytest.mark.asyncio
async def test_handle_message_routes_mentions_in_serial_order(manager, monkeypatch) -> None:
    profile_agents = {
        "hephaestus-deepworker": FakeAgent(name="hephaestus-deepworker", reply_prefix="hephaestus"),
        "prometheus-planner": FakeAgent(name="prometheus-planner", reply_prefix="prometheus"),
        "sisyphus-default": FakeAgent(name="sisyphus-default", reply_prefix="sisyphus"),
    }
    monkeypatch.setattr(
        "digagent.deepagents_runtime.session_ops.build_runtime",
        fake_runtime_factory(lambda **kwargs: profile_agents[kwargs["profile_name"]]),
    )
    session = manager.create_session("mention-turn", "sisyphus-default", Scope())
    _, result = await manager.handle_message(
        session_id=session.session_id,
        content="inspect chain",
        profile_name="sisyphus-default",
        mentions=["hephaestus-deepworker", "prometheus-planner"],
        scope=Scope(),
        auto_approve=True,
    )

    turn = manager.get_turn(result.turn_id)
    messages = manager.list_messages(session.session_id)
    assistant_messages = [message for message in messages if message.role == "assistant"]
    events = manager.load_turn_event_history(turn.turn_id)

    assert turn.profile_name == "hephaestus-deepworker"
    assert turn.addressed_participants == ["hephaestus-deepworker", "prometheus-planner"]
    assert turn.participant_profile == "prometheus-planner"
    assert [message.speaker_profile for message in assistant_messages] == ["hephaestus-deepworker", "prometheus-planner"]
    assert result.assistant_message == assistant_messages[-1].content
    assert profile_agents["hephaestus-deepworker"].calls[0]["message"] == "inspect chain"
    assert "Prior participant outputs" in profile_agents["prometheus-planner"].calls[0]["message"]
    assert any(
        item.type == "participant_handoff"
        and item.data["handoff_from"] == "sisyphus-default"
        and item.data["handoff_to"] == "hephaestus-deepworker"
        for item in events
    )
    assert any(
        item.type == "participant_handoff"
        and item.data["handoff_from"] == "hephaestus-deepworker"
        and item.data["handoff_to"] == "prometheus-planner"
        for item in events
    )


@pytest.mark.asyncio
async def test_handle_message_rejects_unknown_mentions(manager) -> None:
    session = manager.create_session("mention-error", "sisyphus-default", Scope())

    with pytest.raises(ValueError, match="Unknown mentioned agent"):
        await manager.handle_message(
            session_id=session.session_id,
            content="inspect chain",
            profile_name="sisyphus-default",
            mentions=["unknown-agent"],
            scope=Scope(),
            auto_approve=True,
        )

    assert manager.storage.load_session(session.session_id).turn_ids == []


@pytest.mark.asyncio
async def test_stream_events_defaults_to_tail_only(manager) -> None:
    session = manager.create_session("tail-only", "sisyphus-default", Scope())
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="tail only",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    manager.storage.append_turn_event(
        session.session_id,
        TurnEvent(
            event_id="evt_existing",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            type="turn_started",
            data={"turn_id": turn.turn_id},
            created_at="2026-04-19T00:00:00Z",
        ),
    )
    stream = manager.stream_events(session.session_id)

    async def append_new_event() -> None:
        await asyncio.sleep(0.05)
        manager._emit(session.session_id, turn.turn_id, "completed", {"turn_id": turn.turn_id})

    append_task = asyncio.create_task(append_new_event())
    event = await asyncio.wait_for(anext(stream), timeout=0.3)
    await append_task
    assert event.type == "completed"
    assert event.event_id != "evt_existing"


@pytest.mark.asyncio
async def test_session_event_history_preserves_append_order_for_same_second_events(manager) -> None:
    session = manager.create_session("same-second-order", "sisyphus-default", Scope())
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="keep order",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    for index, event_type in enumerate(["assistant_chunk", "langgraph_tasks", "tool_result"], start=1):
        manager.storage.append_turn_event(
            session.session_id,
            TurnEvent(
                event_id=f"evt_{index}",
                session_id=session.session_id,
                turn_id=turn.turn_id,
                type=event_type,
                data={"turn_id": turn.turn_id, "index": index},
                created_at="2026-04-19T10:00:00Z",
            ),
        )

    turn_history = manager.load_turn_event_history(turn.turn_id)
    session_history = manager.load_session_event_history(session.session_id)

    assert [item.type for item in turn_history] == ["assistant_chunk", "langgraph_tasks", "tool_result"]
    assert [item.turn_event_index for item in turn_history] == [1, 2, 3]
    scoped = [item for item in session_history if item.turn_id == turn.turn_id]
    assert [item.type for item in scoped] == ["assistant_chunk", "langgraph_tasks", "tool_result"]
    assert [item.session_event_index for item in scoped] == [1, 2, 3]
