from __future__ import annotations

from pathlib import Path

import pytest

from digagent.models import Scope
from tests.live_helpers import build_live_settings

@pytest.mark.asyncio
async def test_deepagents_runtime_turn_reads_probe_file(tmp_path: Path, repo_root: Path) -> None:
    from digagent.runtime import TurnManager

    settings, token = build_live_settings(tmp_path, repo_root)
    manager = TurnManager(settings)
    session = manager.create_session("runtime-live", "sisyphus-default", Scope())
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="读取工作区根目录的 probe.txt，并且只回复其中的完整 token，不要附加任何其他文字。",
        profile_name="sisyphus-default",
        scope=Scope(),
        auto_approve=True,
    )
    assert turn.assistant_message
    assert turn.turn_id
    assert token in turn.assistant_message
