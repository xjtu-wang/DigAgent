from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from digagent.models import RuntimeBudget, Scope, TurnEvent
from tests.turn_test_utils import (
    parse_sse_events,
    seed_completed_turn,
    seed_pending_approval_turn,
    seed_superseded_approval_chain,
)

@pytest.mark.asyncio
async def test_session_turn_endpoint_returns_turn_payload_and_persisted_records(app, manager, monkeypatch) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_response = await client.post(
            "/api/sessions",
            json={"title": "turn contract", "profile": "sisyphus-default", "scope": Scope().model_dump(mode="json")},
        )
        session_response.raise_for_status()
        session_id = session_response.json()["session_id"]

        async def stub_handle_message(**kwargs):
            return seed_completed_turn(
                manager,
                session_id=kwargs["session_id"],
                content=kwargs["content"],
                assistant_text="turn contract ok",
                profile_name=kwargs["profile_name"],
                auto_approve=kwargs["auto_approve"],
                scope=kwargs["scope"],
                title=kwargs["title"],
            )

        monkeypatch.setattr(manager, "handle_message", stub_handle_message)

        response = await client.post(
            f"/api/sessions/{session_id}/turns",
            json={"content": "inspect", "profile": "sisyphus-default", "auto_approve": True, "scope": Scope().model_dump(mode="json")},
        )
        response.raise_for_status()
        payload = response.json()

        assert payload["turn_id"]
        assert payload["session"]["session_id"] == session_id
        assert payload["turn"]["turn_id"] == payload["turn_id"]
        assert payload["turn"]["final_response"] == "turn contract ok"
        messages = (await client.get(f"/api/sessions/{session_id}/messages")).json()
        session_payload = (await client.get(f"/api/sessions/{session_id}")).json()
        turns = (await client.get(f"/api/sessions/{session_id}/turns")).json()
        assert [item["role"] for item in messages] == ["user", "assistant"]
        assert [item["turn_id"] for item in messages] == [payload["turn_id"], payload["turn_id"]]
        assert session_payload["turn_ids"] == [payload["turn_id"]]
        assert session_payload["active_turn_id"] is None
        assert [item["turn_id"] for item in turns] == [payload["turn_id"]]


@pytest.mark.asyncio
async def test_session_turn_endpoint_includes_pending_approvals_when_turn_pauses(app, manager, monkeypatch) -> None:
    session = manager.create_session("turn approvals", "sisyphus-default", Scope())

    async def stub_handle_message(**kwargs):
        return seed_pending_approval_turn(
            manager,
            session_id=kwargs["session_id"],
            content=kwargs["content"],
            approval_id="apr_turn_pending",
            profile_name=kwargs["profile_name"],
            auto_approve=kwargs["auto_approve"],
            scope=kwargs["scope"],
            title=kwargs["title"],
        )

    monkeypatch.setattr(manager, "handle_message", stub_handle_message)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post(
            f"/api/sessions/{session.session_id}/turns",
            json={"content": "write file", "profile": "sisyphus-default", "auto_approve": False, "scope": Scope().model_dump(mode="json")},
        )
        response.raise_for_status()
        payload = response.json()

        assert payload["turn_id"] == payload["turn"]["turn_id"]
        assert payload["turn"]["status"] == "awaiting_approval"
        assert [item["approval_id"] for item in payload["turn"]["pending_approvals"]] == ["apr_turn_pending"]
        session_payload = (await client.get(f"/api/sessions/{session.session_id}")).json()
        assert session_payload["active_turn_id"] == payload["turn_id"]
        assert session_payload["pending_approval_ids"] == ["apr_turn_pending"]


@pytest.mark.asyncio
async def test_get_session_ignores_legacy_approval_files(app, manager) -> None:
    session = manager.create_session("legacy approvals", "sisyphus-default", Scope())
    _, result = seed_pending_approval_turn(
        manager,
        session_id=session.session_id,
        content="needs approval",
        approval_id="apr_turn_pending",
    )
    legacy_payload = {
        "approval_id": "apr_legacy_run",
        "action_id": "act_legacy_run",
        "run_id": "run_legacy_only",
        "status": "pending",
        "action_digest": "sha256:legacy-run",
        "requested_by": "sisyphus-default",
        "requested_at": "2026-04-18T12:00:00Z",
        "resolved_at": None,
        "resolver": None,
        "reason": None,
        "challenge": None,
        "challenge_issued_at": None,
        "challenge_expires_at": None,
        "policy_key": None,
        "kind": "primary",
        "parent_approval_id": None,
        "superseded_by": None,
        "node_id": None,
    }
    manager.storage.approval_path("apr_legacy_run").write_text(json.dumps(legacy_payload), encoding="utf-8")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/api/sessions/{session.session_id}")

    response.raise_for_status()
    payload = response.json()
    assert payload["session_id"] == session.session_id
    assert payload["turns"][0]["turn_id"] == result.turn_id
    assert [item["approval_id"] for item in payload["turns"][0]["pending_approvals"]] == ["apr_turn_pending"]


@pytest.mark.asyncio
async def test_legacy_session_endpoints_return_gone_instead_of_crashing(app, manager) -> None:
    legacy_session_dir = manager.storage.session_dir("sess_legacy_run_only")
    legacy_session_dir.mkdir(parents=True, exist_ok=True)
    legacy_session_dir.joinpath("session.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "session_id": "sess_legacy_run_only",
                "title": "legacy run session",
                "created_at": "2026-04-18T12:00:00Z",
                "updated_at": "2026-04-18T12:00:00Z",
                "status": "idle",
                "root_agent_profile": "sisyphus-default",
                "scope": {"repo_paths": [], "allowed_domains": [], "artifacts": []},
                "run_ids": ["run_legacy_only"],
                "active_run_id": None,
                "pending_approval_ids": [],
                "memory_refs": [],
                "evidence_refs": [],
                "report_refs": [],
                "archived_at": None,
                "last_user_message_id": None,
                "last_agent_message_id": None,
                "latest_report_id": None,
                "last_report_id": None,
            }
        ),
        encoding="utf-8",
    )
    legacy_session_dir.joinpath("messages.ndjson").write_text(
        json.dumps(
            {
                "message_id": "msg_legacy_run_only",
                "session_id": "sess_legacy_run_only",
                "run_id": "run_legacy_only",
                "role": "assistant",
                "sender": "assistant",
                "content": "legacy",
                "artifact_refs": [],
                "evidence_refs": [],
                "created_at": "2026-04-18T12:00:01Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_response = await client.get("/api/sessions/sess_legacy_run_only")
        messages_response = await client.get("/api/sessions/sess_legacy_run_only/messages")

    assert session_response.status_code == 410
    assert messages_response.status_code == 410


@pytest.mark.asyncio
async def test_superseded_approval_contract_keeps_only_new_pending_approval(app, manager) -> None:
    session = manager.create_session("supersede contract", "sisyphus-default", Scope())
    turn, _, new_approval = seed_superseded_approval_chain(
        manager,
        session_id=session.session_id,
        content="replan approval",
        old_approval_id="apr_turn_old",
        new_approval_id="apr_turn_new",
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        turn_payload = (await client.get(f"/api/turns/{turn.turn_id}")).json()
        history = parse_sse_events((await client.get(f"/api/sessions/{session.session_id}/events?history_only=true")).text)

        assert [item["approval_id"] for item in turn_payload["pending_approvals"]] == [new_approval.approval_id]
        assert any(
            item["type"] == "approval_superseded"
            and item["data"]["old_approval_id"] == "apr_turn_old"
            and item["data"]["new_approval_id"] == "apr_turn_new"
            for item in history
        )


@pytest.mark.asyncio
async def test_session_events_history_includes_turn_events(app, manager) -> None:
    session = manager.create_session("turn streaming", "sisyphus-default", Scope())
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="stream turn events",
        scope=Scope(),
        budget=RuntimeBudget(),
    )

    manager.storage.append_turn_event(
        session.session_id,
        TurnEvent(
            event_id="evt_stream_turn",
            session_id=session.session_id,
            turn_id=turn.turn_id,
            type="turn_started",
            data={"turn_id": turn.turn_id},
            created_at="2026-04-18T12:00:00Z",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get(f"/api/sessions/{session.session_id}/events?history_only=true")
    history = parse_sse_events(response.text)

    assert any(item["turn_id"] == turn.turn_id and item["type"] == "turn_started" for item in history)
