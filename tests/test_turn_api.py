from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from digagent.models import Scope
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
