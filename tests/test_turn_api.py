from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from digagent.models import RuntimeBudget, Scope, TaskGraph, TaskNode, TaskNodeKind, TaskNodeStatus, TurnEvent
from tests.runtime_turn_fakes import FakeAgent, fake_runtime_factory
from tests.turn_test_utils import parse_sse_events


@pytest.mark.asyncio
async def test_turn_endpoints_expose_turn_records(test_settings, monkeypatch, runtime_modules) -> None:
    turn_manager, create_app = runtime_modules
    agent = FakeAgent()
    monkeypatch.setattr("digagent.deepagents_runtime.session_ops.build_runtime", fake_runtime_factory(agent))
    app = create_app(turn_manager(test_settings))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session = (
            await client.post(
                "/api/sessions",
                json={"title": "api-turns", "profile": "sisyphus-default", "scope": Scope().model_dump(mode="json")},
            )
        ).json()
        created = await client.post(
            f"/api/sessions/{session['session_id']}/turns",
            json={"content": "hello", "profile": "sisyphus-default", "auto_approve": True, "scope": Scope().model_dump(mode="json")},
        )
        created.raise_for_status()
        payload = created.json()
        turn_id = payload["turn"]["turn_id"]
        assert payload["assistant_message"] == "reply:hello"
        assert payload["turn"]["status"] == "completed"
        session_payload = await client.get(f"/api/sessions/{session['session_id']}")
        session_payload.raise_for_status()
        assert session_payload.json()["turn_ids"] == [turn_id]
        assert session_payload.json()["active_turn_id"] is None
        turns = await client.get(f"/api/sessions/{session['session_id']}/turns")
        turns.raise_for_status()
        assert [item["turn_id"] for item in turns.json()] == [turn_id]
        turn = await client.get(f"/api/turns/{turn_id}")
        turn.raise_for_status()
        assert turn.json()["turn_id"] == turn_id
        events = await client.get(f"/api/turns/{turn_id}/events?history_only=true")
        events.raise_for_status()
        assert [item["type"] for item in parse_sse_events(events.text)] == ["turn_started", "langgraph_updates", "assistant_message", "completed"]


@pytest.mark.asyncio
async def test_create_turn_endpoint_creates_session_when_missing(test_settings, monkeypatch, runtime_modules) -> None:
    turn_manager, create_app = runtime_modules
    agent = FakeAgent()
    monkeypatch.setattr("digagent.deepagents_runtime.session_ops.build_runtime", fake_runtime_factory(agent))
    app = create_app(turn_manager(test_settings))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            "/api/turns",
            json={"task": "hello", "profile": "sisyphus-default", "auto_approve": True, "scope": Scope().model_dump(mode="json")},
        )
        response.raise_for_status()
        payload = response.json()
        assert payload["assistant_message"] == "reply:hello"
        assert payload["turn"]["status"] == "completed"
        assert payload["session"]["active_turn_id"] is None
        assert payload["session"]["turn_ids"] == [payload["turn"]["turn_id"]]


@pytest.mark.asyncio
async def test_session_message_endpoint_routes_mentions_into_profile_and_events(test_settings, monkeypatch, runtime_modules) -> None:
    turn_manager, create_app = runtime_modules
    agent = FakeAgent()
    monkeypatch.setattr("digagent.deepagents_runtime.session_ops.build_runtime", fake_runtime_factory(agent))
    app = create_app(turn_manager(test_settings))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session = (
            await client.post(
                "/api/sessions",
                json={"title": "mentions", "profile": "sisyphus-default", "scope": Scope().model_dump(mode="json")},
            )
        ).json()
        created = await client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={
                "content": "@hephaestus-deepworker 检查页面",
                "profile": "sisyphus-default",
                "mentions": ["hephaestus-deepworker", "prometheus-planner"],
                "auto_approve": True,
                "scope": Scope().model_dump(mode="json"),
            },
        )
        created.raise_for_status()
        payload = created.json()
        messages = await client.get(f"/api/sessions/{session['session_id']}/messages")
        messages.raise_for_status()
        events = await client.get(f"/api/sessions/{session['session_id']}/events?history_only=true")
        events.raise_for_status()

    history = parse_sse_events(events.text)
    assert payload["turn"]["profile_name"] == "hephaestus-deepworker"
    assert payload["turn"]["addressed_participants"] == ["hephaestus-deepworker", "prometheus-planner"]
    assert messages.json()[0]["addressed_participants"] == ["hephaestus-deepworker", "prometheus-planner"]
    assert any(
        item["type"] == "participant_handoff"
        and item["data"]["handoff_to"] == "hephaestus-deepworker"
        for item in history
    )
    assert any(
        item["type"] == "assistant_message"
        and item["data"]["speaker_profile"] == "hephaestus-deepworker"
        for item in history
    )


@pytest.mark.asyncio
async def test_session_message_endpoint_rejects_unknown_mentions(test_settings, runtime_modules) -> None:
    turn_manager, create_app = runtime_modules
    manager = turn_manager(test_settings)
    app = create_app(manager)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session = (
            await client.post(
                "/api/sessions",
                json={"title": "mentions", "profile": "sisyphus-default", "scope": Scope().model_dump(mode="json")},
            )
        ).json()
        response = await client.post(
            f"/api/sessions/{session['session_id']}/messages",
            json={
                "content": "@unknown-agent 检查页面",
                "profile": "sisyphus-default",
                "mentions": ["unknown-agent"],
                "auto_approve": True,
                "scope": Scope().model_dump(mode="json"),
            },
        )

    assert response.status_code == 400
    assert "Unknown mentioned agent" in response.json()["detail"]


@pytest.mark.asyncio
async def test_session_snapshot_omits_turn_task_graph(test_settings, runtime_modules) -> None:
    turn_manager, create_app = runtime_modules
    manager = turn_manager(test_settings)
    app = create_app(manager)
    session = manager.create_session("snapshot", "sisyphus-default", Scope())
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="show graph",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    turn.task_graph = TaskGraph(
        turn_id=turn.turn_id,
        nodes=[
            TaskNode(
                node_id="node-1",
                title="Inspect",
                kind=TaskNodeKind.TOOL,
                status=TaskNodeStatus.RUNNING,
                description="inspect repo",
            )
        ],
    )
    manager.storage.save_turn(turn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_response = await client.get(f"/api/sessions/{session.session_id}")
        session_response.raise_for_status()
        turn_response = await client.get(f"/api/turns/{turn.turn_id}")
        turn_response.raise_for_status()
    assert "task_graph" not in session_response.json()["turns"][0]
    assert turn_response.json()["task_graph"]["turn_id"] == turn.turn_id


@pytest.mark.asyncio
async def test_session_event_history_supports_type_filter(test_settings, runtime_modules) -> None:
    turn_manager, create_app = runtime_modules
    manager = turn_manager(test_settings)
    app = create_app(manager)
    session = manager.create_session("history-filter", "sisyphus-default", Scope())
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="filter events",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    manager.storage.append_turn_event(
        session.session_id,
        TurnEvent(
            event_id="evt-approval",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            type="approval_required",
            data={"approval_id": "apr-1"},
            created_at="2026-04-19T01:00:00Z",
        ),
    )
    manager.storage.append_turn_event(
        session.session_id,
        TurnEvent(
            event_id="evt-completed",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            type="completed",
            data={"turn_id": turn.turn_id},
            created_at="2026-04-19T01:00:01Z",
        ),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(
            f"/api/sessions/{session.session_id}/events?history_only=true&event_types=approval_required",
        )
        response.raise_for_status()
    assert [item["type"] for item in parse_sse_events(response.text)] == ["approval_required"]
