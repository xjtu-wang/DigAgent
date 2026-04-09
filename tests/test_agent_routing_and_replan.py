from __future__ import annotations

import pytest

from digagent.models import (
    DailyMemoryNote,
    Finding,
    IntentProfile,
    PlanningBundle,
    ReportDraft,
    RunStatus,
    Scope,
    SessionStatus,
    TaskEdge,
    TaskGraph,
    TaskNode,
    TaskNodeKind,
    TaskNodeStatus,
    WikiEntry,
)
from digagent.tools import ToolExecutionResult
from digagent.utils import new_id, utc_now

from tests.helpers import wait_for_run


def _simple_report_draft() -> ReportDraft:
    return ReportDraft(
        kind="analysis_note",
        title="test",
        summary="done",
        findings=[
            Finding(
                finding_id=new_id("fd"),
                title="ok",
                severity="info",
                confidence=0.9,
                claim="done",
                evidence_refs=[],
                remediation="none",
            )
        ],
        evidence_refs=[],
    )


@pytest.mark.asyncio
async def test_user_input_replan_supersedes_old_descendants(manager, repo_root):
    session = manager.create_session(
        title="clarify-replan",
        profile_name="sisyphus-default",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    run = manager.storage.create_run(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="帮我分析一下",
        scope=Scope(repo_paths=[str(repo_root)]),
        budget=manager.profiles["sisyphus-default"].runtime_budget,
    )
    clarify = TaskNode(
        node_id="clarify_0",
        title="Clarify",
        kind=TaskNodeKind.INPUT,
        status=TaskNodeStatus.WAITING_USER_INPUT,
        description="请补充信息。",
        summary="等待补充信息",
        metadata={"question": "请补充信息。"},
    )
    old_aggregate = TaskNode(
        node_id="aggregate_old",
        title="Old aggregate",
        kind=TaskNodeKind.AGGREGATE,
        status=TaskNodeStatus.COMPLETED,
        description="old aggregate",
        summary="old aggregate",
    )
    old_report = TaskNode(
        node_id="report_old",
        title="Old report",
        kind=TaskNodeKind.REPORT,
        status=TaskNodeStatus.COMPLETED,
        description="old report",
        summary="old report",
    )
    old_export = TaskNode(
        node_id="export_old",
        title="Old export",
        kind=TaskNodeKind.EXPORT,
        status=TaskNodeStatus.COMPLETED,
        description="old export",
        summary="old export",
        metadata={"format": "pdf"},
    )
    run.task_graph = TaskGraph(
        run_id=run.run_id,
        nodes=[clarify, old_aggregate, old_report, old_export],
        edges=[
            TaskEdge(source="clarify_0", target="aggregate_old"),
            TaskEdge(source="aggregate_old", target="report_old"),
            TaskEdge(source="report_old", target="export_old"),
        ],
    )
    run.status = RunStatus.AWAITING_USER_INPUT
    manager.storage.save_run(run)
    session.active_run_id = run.run_id
    session.status = SessionStatus.AWAITING_USER_INPUT
    session.pending_user_question = "请补充信息。"
    manager.storage.save_session(session)

    async def repo_search(arguments):
        return ToolExecutionResult(
            title="Repository Search Results",
            summary="Collected repository matches.",
            raw_output="[]",
            structured_facts=[{"key": "match_count", "value": 0}],
            source={"tool_name": "repo_search", "paths": arguments.get("repo_paths", [])},
        )

    async def fake_plan_task_graph(**kwargs):
        return PlanningBundle(
            intent_profile=IntentProfile(
                objective="做一次源码分析",
                labels=["code_review"],
                report_kind_hint="code_review_report",
                confidence=0.9,
            ),
            planner_message="我已根据补充信息替换旧分支，改为只保留源码分析路径。",
            task_graph=TaskGraph(
                run_id=kwargs["run_id"],
                nodes=[
                    TaskNode(
                        node_id="repo_collect",
                        title="Collect repository evidence",
                        kind=TaskNodeKind.TOOL,
                        description="collect repo evidence",
                        summary="collect repo evidence",
                        metadata={
                            "tool_name": "repo_search",
                            "arguments": {"repo_paths": [str(repo_root)], "query": ""},
                            "targets": {"paths": [str(repo_root)]},
                        },
                    ),
                    TaskNode(
                        node_id="aggregate_new",
                        title="Aggregate evidence",
                        kind=TaskNodeKind.AGGREGATE,
                        description="aggregate",
                        summary="aggregate",
                    ),
                    TaskNode(
                        node_id="report_new",
                        title="Write report",
                        kind=TaskNodeKind.REPORT,
                        description="report",
                        summary="report",
                    ),
                    TaskNode(
                        node_id="export_new",
                        title="Export PDF",
                        kind=TaskNodeKind.EXPORT,
                        description="export",
                        summary="export",
                        metadata={"format": "pdf"},
                    ),
                ],
                edges=[
                    TaskEdge(source="repo_collect", target="aggregate_new"),
                    TaskEdge(source="aggregate_new", target="report_new"),
                    TaskEdge(source="report_new", target="export_new"),
                ],
            ),
        )

    manager.tools.repo_search = repo_search
    manager.agent.plan_task_graph = fake_plan_task_graph

    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="请对当前项目做一次源码分析并生成报告",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert completed.status.value == "completed"

    repaired = manager.storage.find_run(run.run_id)
    node_map = {node.node_id: node for node in repaired.task_graph.nodes}
    assert node_map["aggregate_old"].status == TaskNodeStatus.DEPRECATED
    assert node_map["report_old"].status == TaskNodeStatus.DEPRECATED
    assert node_map["export_old"].status == TaskNodeStatus.DEPRECATED
    assert node_map["aggregate_old"].superseded_by == "repo_collect"
    assert node_map["repo_collect"].replanned_from_node_id == "clarify_0"


@pytest.mark.asyncio
async def test_profile_driven_agents_are_used(manager, repo_root):
    calls: dict[str, list[str]] = {"planner": [], "scheduler": [], "subagent": [], "writer": [], "curator": []}

    async def fake_plan_task_graph(**kwargs):
        calls["planner"].append(kwargs["profile_name"])
        return PlanningBundle(
            intent_profile=IntentProfile(
                objective="解出这道题",
                labels=["ctf"],
                report_kind_hint="writeup",
                confidence=0.9,
            ),
            planner_message="我会先让专项 agent 分析，再汇总写报告。",
            task_graph=TaskGraph(
                run_id=kwargs["run_id"],
                nodes=[
                    TaskNode(
                        node_id="solve",
                        title="Analyze challenge evidence",
                        kind=TaskNodeKind.SUBAGENT,
                        description="solve the ctf challenge",
                        summary="solve the ctf challenge",
                        owner_profile_name="hackey-ctf",
                    ),
                    TaskNode(
                        node_id="aggregate",
                        title="Aggregate evidence",
                        kind=TaskNodeKind.AGGREGATE,
                        description="aggregate",
                        summary="aggregate",
                    ),
                    TaskNode(
                        node_id="report",
                        title="Write report",
                        kind=TaskNodeKind.REPORT,
                        description="report",
                        summary="report",
                    ),
                    TaskNode(
                        node_id="export",
                        title="Export PDF",
                        kind=TaskNodeKind.EXPORT,
                        description="export",
                        summary="export",
                        metadata={"format": "pdf"},
                    ),
                ],
                edges=[
                    TaskEdge(source="solve", target="aggregate"),
                    TaskEdge(source="aggregate", target="report"),
                    TaskEdge(source="report", target="export"),
                ],
            ),
        )

    async def fake_select_execution_batch(**kwargs):
        calls["scheduler"].append(kwargs["profile_name"])
        return type("Decision", (), {"node_ids": [node.node_id for node in kwargs["ready_nodes"]], "planner_message": "继续执行", "rationale": "test"})()

    async def fake_run_text_task(*, profile_name=None, system_prompt=None, task):
        if profile_name in {"hackey-ctf", "hephaestus-deepworker"}:
            calls["subagent"].append(profile_name)
        return "subagent summary"

    async def fake_write_report(*, profile_name, dossier):
        calls["writer"].append(profile_name)
        evidence_id = dossier.evidence[0]["evidence_id"]
        return ReportDraft(
            kind="writeup",
            title="ctf",
            summary="done",
            findings=[
                Finding(
                    finding_id=new_id("fd"),
                    title="flag",
                    severity="info",
                    confidence=0.95,
                    claim="flag found",
                    evidence_refs=[evidence_id],
                    remediation="none",
                )
            ],
            writer_summary="writer done",
            evidence_refs=[evidence_id],
        )

    async def fake_curate_memory(*, profile_name, task, intent_profile, report, evidence, session_id, run_id):
        calls["curator"].append(profile_name)
        return {
            "daily_note": DailyMemoryNote(
                heading=f"Run {run_id}",
                body="done",
                source_session_id=session_id,
                source_run_id=run_id,
                evidence_refs=[evidence[0]["evidence_id"]],
                created_at=utc_now(),
            ).model_dump(mode="json"),
            "memory_candidates": [],
            "wiki_entries": [
                WikiEntry(
                    entry_id=new_id("wiki"),
                    title="ctf",
                    summary="done",
                    source_session_id=session_id,
                    source_run_id=run_id,
                    claims=[],
                    created_at=utc_now(),
                    updated_at=utc_now(),
                ).model_dump(mode="json")
            ],
        }

    manager.agent.plan_task_graph = fake_plan_task_graph
    manager.agent.select_execution_batch = fake_select_execution_batch
    manager.agent.run_text_task = fake_run_text_task
    manager.agent.write_report = fake_write_report
    manager.agent.curate_memory = fake_curate_memory

    session = manager.create_session(title="ctf", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="一道密码学 CTF 题：一只小羊翻过了 2 个栅栏 `fa{fe13f590lg6d46d0d0}`",
    )
    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert completed.status.value == "completed"
    run = manager.storage.find_run(turn.run_id)
    solve_node = next(node for node in run.task_graph.nodes if node.node_id == "solve")
    assert calls["planner"] == ["prometheus-planner"]
    assert calls["scheduler"]
    assert all(profile == "prometheus-planner" for profile in calls["scheduler"])
    assert "hackey-ctf" in calls["subagent"]
    assert calls["writer"] == ["report-writer"]
    assert calls["curator"] == ["memory-curator"]
    assert solve_node.action_request["name"] == "delegate_subagent"
    assert solve_node.owner_profile_name == "hackey-ctf"


def test_subagent_routing_requires_explicit_owner(manager):
    node = TaskNode(
        node_id="sub",
        title="Inspect repo",
        kind=TaskNodeKind.SUBAGENT,
        description="inspect repo",
        summary="inspect repo",
    )
    with pytest.raises(ValueError):
        manager._subagent_profile_name(node)

    node.owner_profile_name = "hephaestus-deepworker"
    assert manager._subagent_profile_name(node) == "hephaestus-deepworker"
