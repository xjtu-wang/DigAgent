from __future__ import annotations

from pathlib import Path

import pytest

from digagent.models import Scope
from tests.live_helpers import build_live_settings

PROBE_FILENAME = "auto_approve_probe.txt"
PROBE_CONTENT = "AUTO_APPROVE_PROBE_OK"
WRITE_FILE_PROMPT = (
    f"在工作区根目录创建文件 {PROBE_FILENAME}，"
    f"内容必须严格是 {PROBE_CONTENT}，"
    "必须通过工具实际写入文件；完成后只回复 done。"
)

@pytest.mark.asyncio
async def test_deepagents_turn_auto_approve_controls_write_interrupts(tmp_path: Path, repo_root: Path) -> None:
    from digagent.runtime import TurnManager

    settings, _ = build_live_settings(tmp_path, repo_root)
    manager = TurnManager(settings)
    probe_path = settings.workspace_root / PROBE_FILENAME

    blocked_session = manager.create_session("auto-approve-off", "sisyphus-default", Scope())
    _, blocked_turn = await manager.handle_message(
        session_id=blocked_session.session_id,
        content=WRITE_FILE_PROMPT,
        profile_name="sisyphus-default",
        scope=Scope(),
        auto_approve=False,
    )
    blocked_turn_record = manager.storage.find_turn(blocked_turn.turn_id)

    assert blocked_turn_record.status == "awaiting_approval"
    assert manager.pending_approvals_for_turn(blocked_turn_record.turn_id)
    assert not probe_path.exists()

    allowed_session = manager.create_session("auto-approve-on", "sisyphus-default", Scope())
    _, allowed_turn = await manager.handle_message(
        session_id=allowed_session.session_id,
        content=WRITE_FILE_PROMPT,
        profile_name="sisyphus-default",
        scope=Scope(),
        auto_approve=True,
    )
    allowed_turn_record = manager.storage.find_turn(allowed_turn.turn_id)

    assert allowed_turn_record.status == "completed"
    assert not manager.pending_approvals_for_turn(allowed_turn_record.turn_id)
    assert probe_path.read_text(encoding="utf-8") == PROBE_CONTENT
