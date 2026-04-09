from __future__ import annotations

import asyncio

import pytest

from digagent.models import Scope
from digagent.tools import ToolExecutionResult

from tests.helpers import wait_for_run


@pytest.mark.asyncio
async def test_ctf_acceptance(manager):
    session = manager.create_session(title="ctf", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="一道密码学 CTF 题：一只小羊翻过了 2 个栅栏 `fa{fe13f590lg6d46d0d0}`",
    )
    completed = await wait_for_run(manager, turn.run_id)
    assert completed.status.value == "completed"
    assert "flag{6fde4163df05d900}" in (completed.final_response or "")
    assert completed.report_id
    assert manager.storage.report_markdown_path(completed.report_id).exists()
    assert manager.storage.report_pdf_path(completed.report_id).exists()


@pytest.mark.asyncio
async def test_code_review_acceptance(manager, repo_root):
    session = manager.create_session(
        title="code review",
        profile_name="sisyphus-default",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="请对当前项目做一次源码分析并生成报告",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    completed = await wait_for_run(manager, turn.run_id)
    assert completed.status.value == "completed"
    assert completed.report_id
    report = manager.storage.load_report(completed.report_id)
    assert report.kind == "code_review_report"
    assert report.findings[0].evidence_refs


@pytest.mark.asyncio
async def test_report_kind_follows_graph_and_evidence_not_legacy_task_type(manager):
    session = manager.create_session(title="morse", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content=".... . .-.. .-.. --- / .-- --- .-. .-.. -.. 解密",
    )
    completed = await wait_for_run(manager, turn.run_id)
    assert completed.status.value == "completed"
    report = manager.storage.load_report(completed.report_id)
    assert report.kind == "writeup"
    assert "源码分析" not in report.summary
    assert "code_review" not in report.kind


@pytest.mark.asyncio
async def test_web_analysis_acceptance(manager):
    async def fake_fetch(arguments):
        return ToolExecutionResult(
            title="Web Fetch: https://fixture.test",
            summary="Fetched fixture.test with status 200 and extracted 2 links.",
            raw_output='{"title":"Fixture Site","status_code":200}',
            structured_facts=[
                {"key": "status_code", "value": 200},
                {"key": "content_type", "value": "text/html"},
                {"key": "title", "value": "Fixture Site"},
                {"key": "link_count", "value": 2},
            ],
            mime_type="application/json",
            artifact_kind="html",
            source={"tool_name": "web_fetch", "url": "https://fixture.test"},
        )

    manager.tools.web_fetch = fake_fetch
    session = manager.create_session(
        title="web analysis",
        profile_name="sisyphus-default",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="分析这个站点 https://fixture.test",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_approval", "failed"})
    approval = manager.storage.load_approval(paused.approval_ids[0])
    await manager.approve(approval.approval_id, approved=True, resolver="pytest")
    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert completed.status.value == "completed"
    report = manager.storage.load_report(completed.report_id)
    assert report.kind == "pentest_report"
    assert report.findings[0].evidence_refs


@pytest.mark.asyncio
async def test_layered_memory_outputs_are_created(manager):
    session = manager.create_session(title="memory", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="一道密码学 CTF 题：一只小羊翻过了 2 个栅栏 `fa{fe13f590lg6d46d0d0}`",
    )
    completed = await wait_for_run(manager, turn.run_id)
    assert completed.status.value == "completed"

    memory_md = manager.storage.load_memory_markdown()
    daily_md = manager.storage.load_daily_memory(completed.finished_at[:10])
    memory_index = manager.storage.load_memory_index()
    wiki_entries = manager.storage.list_wiki_entries()

    assert memory_md.startswith("# DigAgent Memory")
    assert "workflow_pattern" not in memory_md
    assert completed.run_id in daily_md
    assert memory_index["items"]
    assert wiki_entries


def test_api_session_routes_and_catalog(app, manager):
    paths = {route.path for route in app.routes}
    assert "/api/health" in paths
    assert "/api/catalog" in paths
    assert "/api/sessions" in paths
    assert "/api/sessions/{session_id}/messages" in paths
    assert "/api/sessions/{session_id}/events" in paths
    assert "/api/runs" in paths

    catalog = manager.catalog()
    assert len(catalog["profiles"]) >= 6
    assert len(catalog["tools"]) >= 2
    assert len(catalog["skills"]) >= 41
    assert any(profile["name"] == "prometheus-planner" for profile in catalog["profiles"])
    assert any(profile["name"] == "report-writer" for profile in catalog["profiles"])
    assert any(profile["name"] == "memory-curator" for profile in catalog["profiles"])
    assert any(tool["name"] == "repo_search" for tool in catalog["tools"])
    assert any(tool["name"] == "memory_search" for tool in catalog["tools"])
    assert any(tool["name"] == "memory_get" for tool in catalog["tools"])
    assert all(tool["name"] != "crypto_helper" for tool in catalog["tools"])
    assert all("executor_adapter" in tool for tool in catalog["tools"])
    assert any(skill["name"] == "ctf-sandbox-orchestrator" for skill in catalog["skills"])
    assert any(plugin["plugin_id"] == "ctf-sandbox-orchestrator" for plugin in catalog["plugins"])
    assert catalog["capabilities"]["memory"] == "layered_memory_with_scoped_search"

    async def run_and_wait():
        session = manager.create_session(title="ctf", profile_name="sisyphus-default")
        _, turn = await manager.handle_message(
            session_id=session.session_id,
            content="一道密码学 CTF 题：一只小羊翻过了 2 个栅栏 `fa{fe13f590lg6d46d0d0}`",
        )
        completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
        return session.session_id, completed.run_id

    session_id, run_id = asyncio.run(run_and_wait())
    assert session_id in manager.event_history
    assert any(event.run_id == run_id and event.type == "completed" for event in manager.event_history[session_id])


@pytest.mark.asyncio
async def test_memory_search_retrieval_is_scoped(manager):
    session = manager.create_session(title="memory search", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="一道密码学 CTF 题：一只小羊翻过了 2 个栅栏 `fa{fe13f590lg6d46d0d0}`",
    )
    completed = await wait_for_run(manager, turn.run_id)
    assert completed.status.value == "completed"

    search = manager.tools.memory_search({"query": "flag rail fence", "session_id": session.session_id, "scope": "session", "limit": 3})
    assert search.structured_facts[0]["value"] >= 1
    payload = search.raw_output
    assert "memory:" in payload or "wiki:" in payload or "daily:" in payload
