from __future__ import annotations

import asyncio
import time

import pytest

from digagent.models import Scope, TaskEdge, TaskGraph, TaskNode, TaskNodeKind
from digagent.tools import ToolExecutionResult

from tests.helpers import wait_for_run


@pytest.mark.asyncio
async def test_non_exclusive_ready_nodes_run_in_parallel(manager, repo_root):
    timings: dict[str, dict[str, float]] = {}

    async def slow_repo_search(arguments):
        timings["repo_search"] = {"start": time.perf_counter()}
        await asyncio.sleep(0.2)
        timings["repo_search"]["end"] = time.perf_counter()
        return ToolExecutionResult(
            title="Repository Search Results",
            summary="Collected repository matches.",
            raw_output="[]",
            structured_facts=[{"key": "match_count", "value": 0}],
            source={"tool_name": "repo_search", "paths": arguments.get("repo_paths", [])},
        )

    async def slow_vuln_lookup(arguments):
        timings["vuln_kb_lookup"] = {"start": time.perf_counter()}
        await asyncio.sleep(0.2)
        timings["vuln_kb_lookup"]["end"] = time.perf_counter()
        return ToolExecutionResult(
            title="Vulnerability Knowledge Base Lookup",
            summary="Matched 0 records.",
            raw_output="[]",
            structured_facts=[{"key": "match_count", "value": 0}],
            mime_type="application/json",
            artifact_kind="file",
            source={"tool_name": "vuln_kb_lookup"},
        )

    manager.tools.repo_search = slow_repo_search
    manager.tools.vuln_kb_lookup = slow_vuln_lookup

    async def fake_plan_task_graph(**kwargs):
        search = TaskNode(
            node_id="node_search",
            title="Search repository",
            kind=TaskNodeKind.TOOL,
            description="Collect repository evidence.",
            summary="Collect repository evidence.",
            metadata={
                "tool_name": "repo_search",
                "arguments": {"repo_paths": [str(repo_root)], "query": ""},
                "targets": {"paths": [str(repo_root)]},
            },
        )
        kb = TaskNode(
            node_id="node_kb",
            title="Lookup vulnerability knowledge",
            kind=TaskNodeKind.TOOL,
            description="Query the local vulnerability knowledge base.",
            summary="Query the local vulnerability knowledge base.",
            metadata={"tool_name": "vuln_kb_lookup", "arguments": {"query": "openssl", "limit": 3}},
        )
        aggregate = TaskNode(
            node_id="node_aggregate",
            title="Aggregate evidence",
            kind=TaskNodeKind.AGGREGATE,
            description="Aggregate evidence.",
            summary="Aggregate evidence.",
        )
        report = TaskNode(
            node_id="node_report",
            title="Write report",
            kind=TaskNodeKind.REPORT,
            description="Write report.",
            summary="Write report.",
        )
        export = TaskNode(
            node_id="node_export",
            title="Export PDF",
            kind=TaskNodeKind.EXPORT,
            description="Export PDF.",
            summary="Export PDF.",
            metadata={"format": "pdf"},
        )
        return TaskGraph(
            run_id=kwargs["run_id"],
            nodes=[search, kb, aggregate, report, export],
            edges=[
                TaskEdge(source="node_search", target="node_aggregate"),
                TaskEdge(source="node_kb", target="node_aggregate"),
                TaskEdge(source="node_aggregate", target="node_report"),
                TaskEdge(source="node_report", target="node_export"),
            ],
        )

    manager.agent.plan_task_graph = fake_plan_task_graph

    session = manager.create_session(
        title="parallel",
        profile_name="sisyphus-default",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    start = time.perf_counter()
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="请并行收集仓库线索和漏洞知识库线索，然后生成报告",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    duration = time.perf_counter() - start

    assert completed.status.value == "completed"
    assert "repo_search" in timings and "vuln_kb_lookup" in timings
    assert abs(timings["repo_search"]["start"] - timings["vuln_kb_lookup"]["start"]) < 0.12
    assert duration < 0.55
