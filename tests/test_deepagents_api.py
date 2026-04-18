from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from digagent.models import Scope
from digagent.session_titles import DEFAULT_SESSION_TITLE
from tests.live_helpers import build_live_settings
from tests.turn_test_utils import parse_sse_events

@pytest.mark.asyncio
async def test_deepagents_api_session_turn_reads_probe_file(tmp_path: Path, repo_root: Path) -> None:
    for module_name in [
        "digagent.api",
        "digagent.runtime",
        "digagent.deepagents_manager",
        "digagent.deepagents_runtime",
        "digagent.deepagents_runtime.manager_ops",
        "digagent.deepagents_runtime.factory",
        "digagent.deepagents_runtime.session_ops",
        "langchain_core",
        "langchain_core.messages",
        "langgraph",
        "langgraph.types",
    ]:
        sys.modules.pop(module_name, None)
    from digagent.api import create_app
    from digagent.runtime import TurnManager

    settings, token = build_live_settings(tmp_path, repo_root)
    app = create_app(TurnManager(settings))
    prompt = "读取工作区根目录的 probe.txt，并且只回复其中的完整 token，不要附加任何其他文字。"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_response = await client.post(
            "/api/sessions",
            json={"title": DEFAULT_SESSION_TITLE, "profile": "sisyphus-default", "scope": Scope().model_dump(mode="json")},
        )
        session_response.raise_for_status()
        session_id = session_response.json()["session_id"]
        response = await client.post(
            f"/api/sessions/{session_id}/turns",
            json={"content": prompt, "profile": "sisyphus-default", "auto_approve": True, "scope": Scope().model_dump(mode="json")},
        )
        response.raise_for_status()
        payload = response.json()
        session_payload = None
        for _ in range(40):
            session_result = await client.get(f"/api/sessions/{session_id}")
            session_result.raise_for_status()
            session_payload = session_result.json()
            assert session_payload["title_status"] != "failed"
            if session_payload["title_status"] == "ready" and session_payload["title_source"] == "model":
                break
            await asyncio.sleep(0.25)
        else:
            raise AssertionError(f"session title did not finish generating: {session_payload}")
        events_response = await client.get(f"/api/sessions/{session_id}/events?history_only=true")
        events_response.raise_for_status()
        history = parse_sse_events(events_response.text)
    assert payload["turn_id"]
    assert payload["session"]["session_id"] == session_id
    assert payload["turn"]["turn_id"] == payload["turn_id"]
    assert "title_status" in payload["session"]
    assert "title_source" in payload["session"]
    assert token in (payload["assistant_message"] or "")
    assert session_payload is not None
    assert session_payload["title_source"] == "model"
    assert session_payload["title_status"] == "ready"
    assert any(
        item["type"] == "session_title_updated"
        and item["data"]["title"] == session_payload["title"]
        and item["data"]["title_source"] == "model"
        for item in history
    )
