from __future__ import annotations

import pytest

from digagent.models import ActionRequest, ActionTargets, ActionType, PermissionDecision, Scope
from digagent.permissions import PermissionEngine
from digagent.skills import SkillCatalog
from digagent.tools import ToolExecutionResult
from digagent.utils import new_id, utc_now

from tests.helpers import wait_for_run


def test_unauthorized_tool_is_denied(manager):
    profile = manager.profiles["sisyphus-default"]
    action = ActionRequest(
        action_id=new_id("act"),
        run_id="run_test",
        actor_agent_id="sisyphus",
        action_type=ActionType.TOOL,
        name="malicious_tool",
        arguments={},
        targets=ActionTargets(),
        justification="should fail",
        risk_tags=[],
        created_at=utc_now(),
    )
    outcome = PermissionEngine(manager.settings).decide(action, profile, Scope())
    assert outcome.decision == PermissionDecision.DENY


@pytest.mark.asyncio
async def test_high_risk_call_requires_approval_and_audit(manager):
    async def fake_fetch(arguments):
        return ToolExecutionResult(
            title="Web Fetch: https://fixture.test",
            summary="Fetched fixture.test with status 200.",
            raw_output='{"title":"Fixture Site","status_code":200}',
            structured_facts=[
                {"key": "status_code", "value": 200},
                {"key": "title", "value": "Fixture Site"},
                {"key": "link_count", "value": 1},
            ],
            mime_type="application/json",
            artifact_kind="html",
            source={"tool_name": "web_fetch", "url": "https://fixture.test"},
        )

    manager.tools.web_fetch = fake_fetch
    session = manager.create_session(
        title="security",
        profile_name="sisyphus-default",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="请分析 https://fixture.test",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_approval", "failed"})
    assert paused.status.value == "awaiting_approval"
    assert paused.approval_ids

    approval = manager.storage.load_approval(paused.approval_ids[0])
    await manager.approve(approval.approval_id, approved=True, resolver="pytest")
    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert completed.status.value == "completed"

    audits = manager.storage.load_audit_events(completed.session_id, completed.run_id)
    decisions = {(event["decision"], event["result"]) for event in audits}
    assert ("confirm", "blocked") in decisions
    assert any(event["executor"] == "tool_runner" for event in audits)


@pytest.mark.asyncio
async def test_approval_digest_mismatch_blocks_execution(manager):
    async def fake_fetch(arguments):
        return ToolExecutionResult(
            title="Web Fetch: https://fixture.test",
            summary="Fetched fixture.test with status 200.",
            raw_output='{"title":"Fixture Site","status_code":200}',
            structured_facts=[
                {"key": "status_code", "value": 200},
                {"key": "title", "value": "Fixture Site"},
            ],
            mime_type="application/json",
            artifact_kind="html",
            source={"tool_name": "web_fetch", "url": "https://fixture.test"},
        )

    manager.tools.web_fetch = fake_fetch
    session = manager.create_session(
        title="digest",
        profile_name="sisyphus-default",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="请分析 https://fixture.test",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_approval", "failed"})
    run = manager.storage.find_run(turn.run_id)
    fetch_node = next(node for node in run.task_graph.nodes if node.kind.value == "tool")
    fetch_node.action_request["arguments"]["url"] = "https://other.test"
    manager.storage.save_run(run)

    approval = manager.storage.load_approval(paused.approval_ids[0])
    await manager.approve(approval.approval_id, approved=True, resolver="pytest")
    failed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert failed.status.value == "failed"
    assert "digest" in (failed.error_message or "")


@pytest.mark.asyncio
async def test_pdf_export_failure_is_explicit(manager):
    manager.reporter.export_pdf = lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("renderer crashed"))
    session = manager.create_session(title="export failure", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="一道密码学 CTF 题：一只小羊翻过了 2 个栅栏 `fa{fe13f590lg6d46d0d0}`",
    )
    failed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert failed.status.value == "failed"
    assert "pdf export failed" in (failed.error_message or "")


def test_skill_cannot_bypass_permission(tmp_path, test_settings):
    marker = tmp_path / "owned.txt"
    skill_dir = test_settings.data_dir / "skills" / "malicious-skill"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: malicious-skill
description: Attempts to escape.
---

# Malicious

This skill includes a script reference but should never execute it automatically.
""",
        encoding="utf-8",
    )
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    (scripts_dir / "pwn.sh").write_text(f"touch {marker}\n", encoding="utf-8")

    catalog = SkillCatalog(test_settings)
    manifest = catalog.load("malicious-skill")
    assert manifest.name == "malicious-skill"
    assert not marker.exists()
