from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from digagent.models import Scope
from tests.live_helpers import build_live_settings

@pytest.mark.asyncio
async def test_deepagents_api_session_turn_reads_probe_file(tmp_path: Path, repo_root: Path) -> None:
    from digagent.api import create_app
    from digagent.runtime import TurnManager

    settings, token = build_live_settings(tmp_path, repo_root)
    app = create_app(TurnManager(settings))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        session_response = await client.post(
            "/api/sessions",
            json={"title": "turn live", "profile": "sisyphus-default", "scope": Scope().model_dump(mode="json")},
        )
        session_response.raise_for_status()
        session_id = session_response.json()["session_id"]
        response = await client.post(
            f"/api/sessions/{session_id}/turns",
            json={"content": "读取工作区根目录的 probe.txt，并且只回复其中的完整 token，不要附加任何其他文字。", "profile": "sisyphus-default", "auto_approve": True, "scope": Scope().model_dump(mode="json")},
        )
        response.raise_for_status()
        payload = response.json()
    assert payload["turn_id"]
    assert payload["session"]["session_id"] == session_id
    assert payload["turn"]["turn_id"] == payload["turn_id"]
    assert token in (payload["assistant_message"] or "")
