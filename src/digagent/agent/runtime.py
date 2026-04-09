from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from digagent.agent.bridge import AgentBridge
from digagent.cve import CveKnowledgeBase
from digagent.config import AppSettings, get_settings, load_profiles
from digagent.models import (
    ActionRequest,
    ActionTargets,
    ActionType,
    ApprovalChallenge,
    ApprovalRecord,
    ApprovalStatus,
    ApprovalToken,
    AuditEvent,
    BudgetUsage,
    CVERecord,
    DailyMemoryNote,
    EvidenceRecord,
    DelegationGrant,
    IntentProfile,
    GraphEditOp,
    GraphOpType,
    MemoryHit,
    MessageRoute,
    MessageRoutingDecision,
    MemoryRecord,
    MemoryPromotionCandidate,
    MessageRecord,
    MessageRole,
    PermissionDecision,
    ReportRecord,
    ReportDossier,
    ReportDraft,
    RunEvent,
    RunRecord,
    RunStatus,
    Scope,
    SessionRecord,
    SessionSummary,
    SessionStatus,
    SubagentResult,
    SubagentTask,
    TaskEdge,
    TaskGraph,
    TaskNode,
    TaskNodeKind,
    TaskNodeStatus,
    UserTurnDisposition,
    UserTurnResult,
    WikiEntry,
)
from digagent.permission import PermissionEngine
from digagent.plugins import PluginCatalog
from digagent.report import ReportExporter
from digagent.report.validator import ReportValidationError, ReportValidator
from digagent.skills import SkillCatalog
from digagent.storage import FileStorage
from digagent.storage.memory_search import MemorySearchEngine
from digagent.tools import ToolExecutionResult, ToolRegistry
from digagent.utils import action_digest, new_id, normalize_domain, utc_now

TERMINAL_RUN_STATES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.CANCELLED,
    RunStatus.TIMED_OUT,
}

APPROVE_MARKERS = {"批准", "同意", "approve", "approved", "yes", "继续", "通过"}
REJECT_MARKERS = {"拒绝", "不同意", "reject", "rejected", "deny", "no"}
PLANNER_PROFILE = "prometheus-planner"
WRITER_PROFILE = "report-writer"
CURATOR_PROFILE = "memory-curator"
CLARIFY_SUPERSEDED_REASON = "superseded after clarification"


class GraphManager:
    def refresh(self, graph: TaskGraph) -> None:
        node_map = {node.node_id: node for node in graph.nodes}
        dependencies: dict[str, set[str]] = {node.node_id: set() for node in graph.nodes}
        children: dict[str, set[str]] = {node.node_id: set() for node in graph.nodes}
        for edge in graph.edges:
            if edge.source in node_map and edge.target in node_map:
                dependencies[edge.target].add(edge.source)
                children[edge.source].add(edge.target)
        graph.ready_node_ids = []
        graph.active_node_ids = []
        graph.completed_node_ids = []
        graph.blocked_node_ids = []
        graph.deprecated_node_ids = []
        for node in graph.nodes:
            node.depends_on = sorted(dependencies.get(node.node_id, set()))
            node.children = sorted(children.get(node.node_id, set()))
            if node.superseded_by and node.status != TaskNodeStatus.DEPRECATED:
                node.status = TaskNodeStatus.DEPRECATED
            if node.status == TaskNodeStatus.PENDING and self._dependencies_satisfied(node, node_map):
                node.status = TaskNodeStatus.READY
            node.is_active = node.status == TaskNodeStatus.RUNNING
            if node.status == TaskNodeStatus.READY:
                graph.ready_node_ids.append(node.node_id)
            elif node.status == TaskNodeStatus.RUNNING:
                graph.active_node_ids.append(node.node_id)
            elif node.status == TaskNodeStatus.COMPLETED:
                graph.completed_node_ids.append(node.node_id)
            elif node.status == TaskNodeStatus.DEPRECATED:
                graph.deprecated_node_ids.append(node.node_id)
            elif node.status in {TaskNodeStatus.BLOCKED, TaskNodeStatus.WAITING_APPROVAL, TaskNodeStatus.WAITING_USER_INPUT}:
                graph.blocked_node_ids.append(node.node_id)
        self.validate_acyclic(graph)
        self.validate_clarify_stage(graph)

    def validate_acyclic(self, graph: TaskGraph) -> None:
        edges_from: dict[str, list[str]] = {}
        for edge in graph.edges:
            edges_from.setdefault(edge.source, []).append(edge.target)
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visited:
                return
            if node_id in visiting:
                raise ValueError("task graph contains a cycle")
            visiting.add(node_id)
            for child in edges_from.get(node_id, []):
                visit(child)
            visiting.remove(node_id)
            visited.add(node_id)

        for node in graph.nodes:
            visit(node.node_id)

    def get_node(self, graph: TaskGraph | None, node_id: str | None) -> TaskNode | None:
        if graph is None or not node_id:
            return None
        return next((node for node in graph.nodes if node.node_id == node_id), None)

    def ready_nodes(self, graph: TaskGraph | None) -> list[TaskNode]:
        if graph is None:
            return []
        node_map = {node.node_id: node for node in graph.nodes}
        return [node_map[node_id] for node_id in graph.ready_node_ids if node_id in node_map]

    def all_done(self, graph: TaskGraph | None) -> bool:
        if graph is None or not graph.nodes:
            return False
        active_statuses = {
            TaskNodeStatus.PENDING,
            TaskNodeStatus.READY,
            TaskNodeStatus.RUNNING,
            TaskNodeStatus.WAITING_APPROVAL,
            TaskNodeStatus.WAITING_USER_INPUT,
            TaskNodeStatus.BLOCKED,
        }
        return all(node.status not in active_statuses for node in graph.nodes)

    def waiting_nodes(self, graph: TaskGraph | None, status: TaskNodeStatus) -> list[TaskNode]:
        if graph is None:
            return []
        return [node for node in graph.nodes if node.status == status]

    def apply_ops(self, graph: TaskGraph, ops: list[GraphEditOp]) -> None:
        node_map = {node.node_id: node for node in graph.nodes}
        for op in ops:
            if op.op_type == GraphOpType.ADD_NODE:
                if not op.node:
                    continue
                new_node = TaskNode.model_validate(op.node)
                if new_node.node_id not in node_map:
                    graph.nodes.append(new_node)
                    node_map[new_node.node_id] = new_node
            elif op.op_type == GraphOpType.UPDATE_NODE and op.node_id and op.patch and op.node_id in node_map:
                for key, value in op.patch.items():
                    setattr(node_map[op.node_id], key, value)
            elif op.op_type == GraphOpType.ADD_EDGE and op.edge:
                if not any(edge.source == op.edge.source and edge.target == op.edge.target for edge in graph.edges):
                    graph.edges.append(op.edge)
            elif op.op_type == GraphOpType.REMOVE_EDGE and op.edge:
                graph.edges = [
                    edge
                    for edge in graph.edges
                    if not (edge.source == op.edge.source and edge.target == op.edge.target)
                ]
            elif op.op_type == GraphOpType.DEPRECATE_NODE and op.node_id and op.node_id in node_map:
                node_map[op.node_id].status = TaskNodeStatus.DEPRECATED
                node_map[op.node_id].block_reason = op.reason
        graph.applied_ops.extend(ops)
        graph.graph_version += 1
        self.refresh(graph)

    def descendants(self, graph: TaskGraph | None, node_id: str | None) -> list[TaskNode]:
        if graph is None or not node_id:
            return []
        node_map = {node.node_id: node for node in graph.nodes}
        children: dict[str, list[str]] = {}
        for edge in graph.edges:
            children.setdefault(edge.source, []).append(edge.target)
        ordered: list[TaskNode] = []
        seen: set[str] = set()
        stack = list(children.get(node_id, []))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            if current in node_map:
                ordered.append(node_map[current])
            stack.extend(children.get(current, []))
        return ordered

    def validate_clarify_stage(self, graph: TaskGraph) -> None:
        waiting = [
            node for node in graph.nodes
            if node.status == TaskNodeStatus.WAITING_USER_INPUT and not node.superseded_by
        ]
        if not waiting:
            return
        live_nodes = [
            node for node in graph.nodes
            if node.status != TaskNodeStatus.DEPRECATED and not node.superseded_by
        ]
        if any(node.kind != TaskNodeKind.INPUT for node in live_nodes):
            raise ValueError("clarify stage cannot include executable live nodes")

    def _dependencies_satisfied(self, node: TaskNode, node_map: dict[str, TaskNode]) -> bool:
        for dependency in node.depends_on:
            parent = node_map.get(dependency)
            if parent is None:
                continue
            if parent.status not in {TaskNodeStatus.COMPLETED, TaskNodeStatus.DEPRECATED}:
                return False
        return True


class SessionManager:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.storage = FileStorage(self.settings)
        self.cve = CveKnowledgeBase(self.settings, self.storage)
        self.plugins = PluginCatalog(self.settings)
        self.memory_search = MemorySearchEngine(self.storage)
        self.tools = ToolRegistry(
            self.settings,
            self.cve,
            storage=self.storage,
            memory_search=self.memory_search,
            plugins=self.plugins,
        )
        self.permissions = PermissionEngine(
            self.settings,
            registered_actions=self.tools.registered_action_names(),
        )
        self.skills = SkillCatalog(self.settings)
        self.reporter = ReportExporter(self.settings)
        self.report_validator = ReportValidator()
        self.agent = AgentBridge(self.settings)
        self.profiles = load_profiles(self.settings)
        self.graphs = GraphManager()
        self.event_queues: dict[str, list[asyncio.Queue[RunEvent]]] = {}
        self.event_history: dict[str, list[RunEvent]] = {}
        self.run_tasks: dict[str, asyncio.Task[None]] = {}

    def catalog(self) -> dict[str, Any]:
        return {
            "profiles": [profile.model_dump(mode="json", exclude={"system_prompt"}) for profile in self.profiles.values()],
            "tools": self.tools.catalog(),
            "skills": [skill.model_dump(mode="json", exclude={"markdown"}) for skill in self.skills.load_all().values()],
            "plugins": self.plugins.catalog(),
            "cve": self.cve.state().model_dump(mode="json"),
            "capabilities": {
                "planner": "llm_driven_dag",
                "memory": "layered_memory_with_scoped_search",
                "report_writer": "dedicated_writer_agent",
            },
            "memory_capabilities": {
                "search": "bm25_scoped_retrieval",
                "get": "ref_based_lookup",
            },
        }

    def list_messages(self, session_id: str) -> list[MessageRecord]:
        return self.storage.load_messages(session_id)

    def list_runs(self, session_id: str) -> list[RunRecord]:
        return self.storage.list_runs(session_id)

    def list_sessions(self) -> list[SessionSummary]:
        summaries: list[SessionSummary] = []
        for session in self.storage.list_sessions():
            messages = self.storage.load_messages(session.session_id)
            last_message = messages[-1].content if messages else None
            summaries.append(
                SessionSummary(
                    session_id=session.session_id,
                    title=session.title,
                    status=session.status,
                    updated_at=session.updated_at,
                    active_run_id=session.active_run_id,
                    pending_approval_count=len(session.pending_approval_ids),
                    last_message_preview=self._preview_text(last_message),
                    latest_report_id=session.latest_report_id,
                )
            )
        return summaries

    def archive_session(self, session_id: str) -> SessionRecord:
        session = self.storage.load_session(session_id)
        if session.active_run_id:
            raise RuntimeError("cannot archive a session with an active run")
        archived = self.storage.archive_session(session_id)
        self.event_history.setdefault(session_id, [])
        return archived

    def unarchive_session(self, session_id: str) -> SessionRecord:
        return self.storage.unarchive_session(session_id)

    def get_run_graph(self, run_id: str) -> dict[str, Any]:
        run = self.storage.find_run(run_id)
        if not run.task_graph:
            return TaskGraph(run_id=run.run_id).model_dump(mode="json")
        self.graphs.refresh(run.task_graph)
        return run.task_graph.model_dump(mode="json")

    def get_evidence(self, evidence_id: str) -> EvidenceRecord:
        return self.storage.load_evidence(evidence_id)

    def get_artifact(self, artifact_id: str):
        return self.storage.load_artifact(artifact_id)

    def get_artifact_bytes(self, artifact_id: str) -> bytes:
        return self.storage.load_artifact_bytes(artifact_id)

    async def sync_cve(self, *, max_records: int | None = None) -> dict[str, Any]:
        state = await self.cve.sync(max_records=max_records)
        payload = state.model_dump(mode="json")
        for session_id in list(self.event_queues):
            await self.emit(session_id, None, "cve_sync_updated", payload)
        return payload

    def cve_status(self) -> dict[str, Any]:
        return self.cve.state().model_dump(mode="json")

    def search_cve(
        self,
        *,
        query: str = "",
        cve_id: str | None = None,
        cwe: str | None = None,
        product: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return [
            record.model_dump(mode="json")
            for record in self.cve.search(query=query, cve_id=cve_id, cwe=cwe, product=product, limit=limit)
        ]

    async def cancel_run_by_id(self, run_id: str) -> RunRecord:
        run = self.storage.find_run(run_id)
        session = self.storage.load_session(run.session_id)
        if run.status in TERMINAL_RUN_STATES:
            return run
        if run.task_graph:
            for node in run.task_graph.nodes:
                if node.status not in {TaskNodeStatus.COMPLETED, TaskNodeStatus.FAILED, TaskNodeStatus.DEPRECATED}:
                    node.status = TaskNodeStatus.DEPRECATED
                    node.block_reason = "cancelled by user"
            self.graphs.refresh(run.task_graph)
        run.status = RunStatus.CANCELLED
        run.awaiting_reason = "cancelled by user"
        run.finished_at = utc_now()
        self.storage.save_run(run)
        session.active_run_id = None
        session.pending_approval_ids = []
        session.pending_user_question = None
        session.status = SessionStatus.IDLE
        self.storage.save_session(session)
        await self._emit_task_graph(session.session_id, run)
        await self.emit(session.session_id, run.run_id, "run_status", {"status": run.status.value})
        await self._emit_budget_update(session.session_id, run)
        return run

    def create_session(
        self,
        *,
        title: str,
        profile_name: str = "sisyphus-default",
        scope: Scope | None = None,
    ) -> SessionRecord:
        return self.storage.create_session(title, profile_name, scope or Scope())

    async def handle_message(
        self,
        *,
        content: str,
        session_id: str | None = None,
        profile_name: str = "sisyphus-default",
        scope: Scope | None = None,
        auto_approve: bool = False,
        title: str | None = None,
    ) -> tuple[SessionRecord, UserTurnResult]:
        if session_id:
            session = self.storage.load_session(session_id)
        else:
            initial_scope = self._enrich_scope(content, scope or Scope())
            session = self.create_session(
                title=title or self._session_title_from_message(content),
                profile_name=profile_name,
                scope=initial_scope,
            )

        self._repair_session_state(session)
        if scope:
            session.scope = self._merge_scope(session.scope, scope)
            self.storage.save_session(session)

        user_message = MessageRecord(
            message_id=new_id("msg"),
            session_id=session.session_id,
            run_id=session.active_run_id,
            role=MessageRole.USER,
            sender="user",
            content=content,
            created_at=utc_now(),
        )
        self.storage.append_message(user_message)
        session = self.storage.load_session(session.session_id)

        if session.status == SessionStatus.ARCHIVED and self._is_restore_request(content):
            session.status = SessionStatus.IDLE
            self.storage.save_session(session)
            return session, await self._direct_answer(
                session,
                "session 已恢复为 idle，可继续发起新任务。",
                user_message=user_message,
            )
        if session.status == SessionStatus.ARCHIVED:
            answer = await self._build_archived_answer(session, content)
            return session, await self._direct_answer(
                session,
                answer,
                user_message=user_message,
            )

        active_run = self._active_run(session)

        if active_run:
            route = await self._classify_message(session, active_run, content)
            if route.route == MessageRoute.CANCEL:
                return session, await self._cancel_run(session, active_run, user_message)
            if route.route == MessageRoute.DIRECT_ANSWER:
                answer = await self._build_direct_answer(session, active_run, content)
                return session, await self._direct_answer(
                    session,
                    answer,
                    user_message=user_message,
                    run_id=active_run.run_id,
                )
            if route.route == MessageRoute.APPROVAL_RESPONSE and active_run.status == RunStatus.AWAITING_APPROVAL:
                result = await self._continue_approval_from_message(session, active_run, content, user_message)
                return self.storage.load_session(session.session_id), result
            if route.route == MessageRoute.CLARIFICATION_INPUT and active_run.status == RunStatus.AWAITING_USER_INPUT:
                result = await self._continue_with_user_input(session, active_run, content, user_message, auto_approve=auto_approve)
                return self.storage.load_session(session.session_id), result
            return session, await self._reject_message(
                session,
                reason="当前 session 已有未完成 run。请等待完成、取消，或先处理审批/补充信息。",
                user_message=user_message,
            )

        route = await self._classify_message(session, None, content)
        if route.route == MessageRoute.DIRECT_ANSWER:
            answer = await self._build_direct_answer(session, None, content)
            return session, await self._direct_answer(
                session,
                answer,
                user_message=user_message,
            )

        result = await self._create_run_from_message(
            session,
            content,
            user_message=user_message,
            profile_name=profile_name,
            scope=scope or Scope(),
            auto_approve=auto_approve,
        )
        return self.storage.load_session(session.session_id), result

    async def start_run(
        self,
        *,
        task: str,
        profile_name: str = "sisyphus-default",
        scope: Scope | None = None,
        session_id: str | None = None,
        auto_approve: bool = False,
        title: str | None = None,
    ) -> tuple[SessionRecord, RunRecord]:
        session, result = await self.handle_message(
            content=task,
            session_id=session_id,
            profile_name=profile_name,
            scope=scope,
            auto_approve=auto_approve,
            title=title,
        )
        if not result.run_id:
            raise RuntimeError(f"message did not start a run: {result.disposition.value}")
        return session, self.storage.find_run(result.run_id)

    async def execute_run(self, run_id: str, *, auto_approve: bool = False) -> None:
        run = self.storage.find_run(run_id)
        session = self.storage.load_session(run.session_id)
        if run.status in TERMINAL_RUN_STATES:
            self._repair_session_state(session)
            return

        run.started_at = run.started_at or utc_now()
        run.scope = self._enrich_scope(run.user_task, run.scope)

        if not run.task_graph:
            run.status = RunStatus.PLANNING
            session.status = SessionStatus.ACTIVE_RUN
            self.storage.save_run(run)
            self.storage.save_session(session)
            try:
                planning = await self._plan_bundle(run)
                run.task_graph = planning.task_graph
                run.intent_profile = planning.intent_profile
                run.planner_summary = planning.planner_message
                session.intent_profile = planning.intent_profile
                self.graphs.refresh(run.task_graph)
                self.storage.save_run(run)
                self.storage.save_session(session)
                await self.emit(
                    session.session_id,
                    run.run_id,
                    "plan",
                    {
                        "intent_profile": planning.intent_profile.model_dump(mode="json"),
                        "planner_message": planning.planner_message,
                        "graph_version": run.task_graph.graph_version,
                        "nodes": [node.model_dump(mode="json") for node in run.task_graph.nodes],
                        "edges": [edge.model_dump(mode="json") for edge in run.task_graph.edges],
                    },
                )
                await self._emit_task_graph(session.session_id, run)
                if planning.planner_message:
                    await self._append_assistant_message(session.session_id, run.run_id, planning.planner_message)
            except Exception as exc:
                await self._fail_run(run, session, f"planner returned invalid task graph: {exc}")
                return

        while True:
            run = self.storage.find_run(run_id)
            session = self.storage.load_session(run.session_id)
            if run.status in TERMINAL_RUN_STATES:
                self._repair_session_state(session)
                return
            if run.task_graph is None:
                await self._fail_run(run, session, "task graph is missing")
                return
            self.graphs.refresh(run.task_graph)
            self.storage.save_run(run)

            waiting_approval = self.graphs.waiting_nodes(run.task_graph, TaskNodeStatus.WAITING_APPROVAL)
            if waiting_approval:
                run.status = RunStatus.AWAITING_APPROVAL
                run.awaiting_reason = waiting_approval[0].block_reason
                session.status = SessionStatus.AWAITING_APPROVAL
                session.active_run_id = run.run_id
                self.storage.save_run(run)
                self.storage.save_session(session)
                await self.emit(session.session_id, run.run_id, "run_status", {"status": run.status.value})
                await self._emit_budget_update(session.session_id, run)
                return

            waiting_input = self.graphs.waiting_nodes(run.task_graph, TaskNodeStatus.WAITING_USER_INPUT)
            if waiting_input:
                question = self._clarify_question(waiting_input[0])
                run.status = RunStatus.AWAITING_USER_INPUT
                run.awaiting_reason = question
                session.status = SessionStatus.AWAITING_USER_INPUT
                if waiting_input[0].metadata.get("_question_emitted") != question:
                    waiting_input[0].metadata["_question_emitted"] = question
                    self.storage.save_run(run)
                    await self.emit(
                        session.session_id,
                        run.run_id,
                        "task_node_waiting_user_input",
                        {"node_id": waiting_input[0].node_id, "prompt": question, "question": question},
                    )
                    await self.emit(
                        session.session_id,
                        run.run_id,
                        "awaiting_user_input",
                        {"prompt": question, "question": question, "node_id": waiting_input[0].node_id},
                    )
                    await self._append_assistant_message(session.session_id, run.run_id, question)
                session.pending_user_question = run.awaiting_reason
                session.active_run_id = run.run_id
                self.storage.save_run(run)
                self.storage.save_session(session)
                await self.emit(session.session_id, run.run_id, "run_status", {"status": run.status.value})
                await self._emit_budget_update(session.session_id, run)
                return

            candidate_nodes = self._select_runnable_nodes(run)
            if not candidate_nodes:
                if self.graphs.all_done(run.task_graph):
                    await self._finalize_run(run, session)
                    return
                if await self._attempt_graph_replan(run, session):
                    continue
                await self._fail_run(run, session, "task graph has no runnable nodes and cannot progress")
                return

            planner = self._planner_profile()
            decision = await self.agent.select_execution_batch(
                profile_name=planner.name,
                task=run.user_task,
                intent_profile=run.intent_profile,
                ready_nodes=candidate_nodes,
                graph=run.task_graph,
                evidence_summaries=self._recent_evidence_summaries(run),
                max_parallel_tools=max(0, run.budget.max_parallel_tools - run.budget_usage.active_tools),
                max_parallel_subagents=max(0, run.budget.max_parallel_subagents - run.budget_usage.active_subagents),
            )
            ready_nodes = [node for node in candidate_nodes if node.node_id in decision.node_ids] or candidate_nodes[:1]
            paused = await self._dispatch_ready_nodes(run_id, ready_nodes, auto_approve=auto_approve)
            run = self.storage.find_run(run_id)
            if paused or run.status in TERMINAL_RUN_STATES:
                return

    async def approve(
        self,
        approval_id: str,
        *,
        approved: bool,
        resolver: str,
        reason: str | None = None,
        approval_token: str | None = None,
        resume_run: bool = True,
        background: bool = False,
    ) -> ApprovalRecord:
        approval = self.storage.load_approval(approval_id)
        if approval.challenge:
            expected = self._approval_token_value(approval, approved=approved, resolver=resolver)
            approval_token = approval_token or expected
            if approval_token != expected:
                raise ValueError("approval token does not match the pending challenge")
        approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        approval.resolved_at = utc_now()
        approval.resolver = resolver
        approval.reason = reason
        self.storage.save_approval(approval)

        run = self.storage.find_run(approval.run_id)
        session = self.storage.load_session(run.session_id)
        if approval_id in session.pending_approval_ids:
            session.pending_approval_ids.remove(approval_id)

        node = self._task_node(run, approval.node_id)
        if node is None:
            raise ValueError("approval is no longer attached to a task node")

        if approval.status == ApprovalStatus.REJECTED:
            node.status = TaskNodeStatus.FAILED
            node.block_reason = reason or "approval rejected"
            self.graphs.refresh(run.task_graph)
            self.storage.save_run(run)
            self.storage.save_session(session)
            await self._fail_run(run, session, node.block_reason, node_id=node.node_id, emit_message=False)
            await self._append_assistant_message(session.session_id, run.run_id, f"审批被拒绝，run 已结束：{node.block_reason}")
            return approval

        current_action = self._build_action_for_node(run, node)
        if approval.action_digest != self._approval_digest(current_action):
            await self._fail_run(
                run,
                session,
                "approved action digest no longer matches the pending action",
                node_id=node.node_id,
                emit_message=False,
            )
            return approval

        node.status = TaskNodeStatus.READY
        node.block_reason = None
        run.awaiting_reason = None
        run.resume_from_action_id = approval.action_id
        self.graphs.refresh(run.task_graph)
        session.status = SessionStatus.ACTIVE_RUN
        session.pending_user_question = None
        self.storage.save_run(run)
        self.storage.save_session(session)
        token = ApprovalToken(
            approval_id=approval.approval_id,
            action_id=approval.action_id,
            action_digest=approval.action_digest,
            issued_at=utc_now(),
            resolver=resolver,
            approved=approved,
        )
        await self.emit(
            session.session_id,
            run.run_id,
            "approval_resolved",
            {
                "approval_id": approval.approval_id,
                "status": approval.status.value,
                "token": token.model_dump(mode="json"),
                "node_id": node.node_id,
            },
        )
        await self._emit_task_graph(session.session_id, run)
        if resume_run:
            if background:
                self.run_tasks[run.run_id] = asyncio.create_task(self.execute_run(run.run_id))
            else:
                await self.execute_run(run.run_id)
        return approval

    async def stream_events(self, session_id: str):
        queue: asyncio.Queue[RunEvent] = asyncio.Queue()
        self.event_queues.setdefault(session_id, []).append(queue)
        history = self.event_history.get(session_id, [])
        for event in history:
            yield event
        try:
            while True:
                event = await queue.get()
                yield event
        finally:
            self.event_queues[session_id].remove(queue)

    async def stream_run_events(self, run_id: str):
        run = self.storage.find_run(run_id)
        async for event in self.stream_events(run.session_id):
            if event.run_id == run_id:
                yield event
                if event.type in {"completed", "failed", "cancelled"}:
                    break

    async def emit(self, session_id: str, run_id: str | None, event_type: str, data: dict[str, Any]) -> None:
        event = RunEvent(
            event_id=new_id("evt"),
            session_id=session_id,
            run_id=run_id,
            type=event_type,
            data=data,
            created_at=utc_now(),
        )
        self.event_history.setdefault(session_id, []).append(event)
        for queue in self.event_queues.get(session_id, []):
            await queue.put(event)

    async def _create_run_from_message(
        self,
        session: SessionRecord,
        content: str,
        *,
        user_message: MessageRecord,
        profile_name: str,
        scope: Scope,
        auto_approve: bool,
    ) -> UserTurnResult:
        intents = self._split_intents(content)
        primary = intents[0] if intents else content
        effective_scope = self._enrich_scope(primary, self._merge_scope(session.scope, scope))
        related_intents = intents[1:]
        ignored_intents: list[str] = []

        session.scope = self._merge_scope(session.scope, effective_scope)
        session.status = SessionStatus.ACTIVE_RUN
        session.last_intent_type = UserTurnDisposition.CREATE_RUN.value
        self.storage.save_session(session)

        run = self.storage.create_run(
            session_id=session.session_id,
            profile_name=profile_name,
            task=primary,
            scope=effective_scope,
            budget=self.profiles[profile_name].runtime_budget,
            trigger_message_id=user_message.message_id,
        )
        run.started_at = utc_now()
        run.followup_messages = related_intents
        self.storage.save_run(run)
        session = self.storage.load_session(session.session_id)
        session.active_run_id = run.run_id
        session.status = SessionStatus.ACTIVE_RUN
        session.last_intent_type = UserTurnDisposition.CREATE_RUN.value
        self.storage.save_session(session)
        await self.emit(session.session_id, run.run_id, "run_status", {"status": run.status.value})
        if ignored_intents:
            await self._append_assistant_message(
                session.session_id,
                run.run_id,
                "已启动首个相关任务。以下独立意图未执行，请在当前 run 完成后单独提交：\n- " + "\n- ".join(ignored_intents),
            )
        self.run_tasks[run.run_id] = asyncio.create_task(self.execute_run(run.run_id, auto_approve=auto_approve))
        return UserTurnResult(
            disposition=UserTurnDisposition.CREATE_RUN,
            session_id=session.session_id,
            run_id=run.run_id,
            message_id=user_message.message_id,
            ignored_intents=ignored_intents,
            assistant_message="已创建新 run 并开始执行。",
        )

    async def _continue_approval_from_message(
        self,
        session: SessionRecord,
        run: RunRecord,
        content: str,
        user_message: MessageRecord,
    ) -> UserTurnResult:
        approval_id = session.pending_approval_ids[0] if session.pending_approval_ids else (run.approval_ids[-1] if run.approval_ids else None)
        if not approval_id:
            return await self._reject_message(session, "当前没有可恢复的审批请求。", user_message=user_message)
        approved = self._message_is_approval(content)
        pending = self.storage.load_approval(approval_id)
        token = self._approval_token_value(pending, approved=approved, resolver="session_message")
        approval = await self.approve(
            approval_id,
            approved=approved,
            resolver="session_message",
            reason=content,
            approval_token=token,
        )
        assistant = "已批准当前审批，run 继续执行。" if approved else "已拒绝当前审批，run 已结束。"
        return UserTurnResult(
            disposition=UserTurnDisposition.CONTINUE_RUN,
            session_id=session.session_id,
            run_id=approval.run_id,
            message_id=user_message.message_id,
            assistant_message=assistant,
            approval_ids=[approval.approval_id],
        )

    async def _continue_with_user_input(
        self,
        session: SessionRecord,
        run: RunRecord,
        content: str,
        user_message: MessageRecord,
        *,
        auto_approve: bool,
    ) -> UserTurnResult:
        waiting_nodes = self.graphs.waiting_nodes(run.task_graph, TaskNodeStatus.WAITING_USER_INPUT)
        waiting_node = waiting_nodes[0] if waiting_nodes else None
        if waiting_node:
            artifact = self.storage.save_artifact(
                session_id=session.session_id,
                run_id=run.run_id,
                kind="stdout",
                content=content,
                mime_type="text/plain",
                suffix=".txt",
            )
            evidence = self._create_evidence(
                run=run,
                title="User clarification",
                summary=content,
                evidence_type="user_input",
                source={"tool_name": "user_input", "agent_id": "user"},
                artifact_ids=[artifact.artifact_id],
                content=content,
                facts=[{"key": "clarification", "value": content}],
            )
            self._attach_node_outputs(
                run,
                waiting_node,
                artifact_ids=[artifact.artifact_id],
                evidence_ids=[evidence.evidence_id],
                summary=content,
            )
            waiting_node.status = TaskNodeStatus.COMPLETED
            waiting_node.block_reason = None
            await self.emit(session.session_id, run.run_id, "evidence_added", {"evidence_id": evidence.evidence_id, "title": evidence.title})

        clarify_node_id = waiting_node.node_id if waiting_node else None
        run.followup_messages.append(content)
        run.scope = self._enrich_scope(content, run.scope)
        run.awaiting_reason = None
        run.status = RunStatus.CREATED
        self.graphs.refresh(run.task_graph)
        try:
            await self._replan_after_user_input(run, session, clarify_node_id=clarify_node_id)
        except Exception as exc:
            await self._fail_run(run, session, f"planner returned invalid replan graph: {exc}")
            return UserTurnResult(
                disposition=UserTurnDisposition.CONTINUE_RUN,
                session_id=session.session_id,
                run_id=run.run_id,
                message_id=user_message.message_id,
                assistant_message=f"补充信息已收到，但重规划失败：{exc}",
                reason=str(exc),
            )
        self.storage.save_run(run)

        session.status = SessionStatus.ACTIVE_RUN
        session.pending_user_question = None
        session.last_intent_type = UserTurnDisposition.CONTINUE_RUN.value
        self.storage.save_session(session)

        self.run_tasks[run.run_id] = asyncio.create_task(self.execute_run(run.run_id, auto_approve=auto_approve))
        return UserTurnResult(
            disposition=UserTurnDisposition.CONTINUE_RUN,
            session_id=session.session_id,
            run_id=run.run_id,
            message_id=user_message.message_id,
            assistant_message=run.planner_summary or "已收到补充信息，继续执行当前 run。",
        )

    async def _cancel_run(self, session: SessionRecord, run: RunRecord, user_message: MessageRecord) -> UserTurnResult:
        await self.cancel_run_by_id(run.run_id)
        return await self._direct_answer(
            session,
            "当前 run 已取消。",
            user_message=user_message,
            run_id=run.run_id,
            disposition=UserTurnDisposition.CONTINUE_RUN,
        )

    async def _direct_answer(
        self,
        session: SessionRecord,
        answer: str,
        *,
        user_message: MessageRecord,
        run_id: str | None = None,
        disposition: UserTurnDisposition = UserTurnDisposition.DIRECT_ANSWER,
    ) -> UserTurnResult:
        assistant = await self._append_assistant_message(session.session_id, run_id, answer)
        session = self.storage.load_session(session.session_id)
        session.last_intent_type = disposition.value
        self.storage.save_session(session)
        return UserTurnResult(
            disposition=disposition,
            session_id=session.session_id,
            run_id=run_id,
            message_id=assistant.message_id,
            assistant_message=answer,
        )

    async def _reject_message(self, session: SessionRecord, reason: str, *, user_message: MessageRecord) -> UserTurnResult:
        assistant = await self._append_assistant_message(session.session_id, session.active_run_id, reason)
        session = self.storage.load_session(session.session_id)
        session.last_intent_type = UserTurnDisposition.REJECT.value
        self.storage.save_session(session)
        return UserTurnResult(
            disposition=UserTurnDisposition.REJECT,
            session_id=session.session_id,
            run_id=session.active_run_id,
            message_id=assistant.message_id,
            assistant_message=reason,
            reason=reason,
        )

    async def _append_assistant_message(self, session_id: str, run_id: str | None, content: str) -> MessageRecord:
        message = MessageRecord(
            message_id=new_id("msg"),
            session_id=session_id,
            run_id=run_id,
            role=MessageRole.ASSISTANT,
            sender="sisyphus",
            content=content,
            created_at=utc_now(),
        )
        self.storage.append_message(message)
        await self.emit(session_id, run_id, "assistant_message", {"message": content, "message_id": message.message_id})
        return message

    async def _pause_for_user_input(self, run: RunRecord, session: SessionRecord) -> None:
        planner = self._planner_profile()
        prompt = await self.agent.generate_clarify_question(
            profile_name=planner.name,
            task=run.user_task,
            scope=run.scope.model_dump(mode="json"),
        )
        input_node = TaskNode(
            node_id=new_id("node"),
            title="Clarify scope",
            kind=TaskNodeKind.INPUT,
            status=TaskNodeStatus.WAITING_USER_INPUT,
            description=prompt,
            summary="等待用户补充任务范围",
            block_reason=prompt,
            metadata={"question": prompt},
            max_retries=0,
        )
        run.task_graph = TaskGraph(run_id=run.run_id, nodes=[input_node], edges=[])
        self.graphs.refresh(run.task_graph)
        run.awaiting_reason = prompt
        run.status = RunStatus.AWAITING_USER_INPUT
        self.storage.save_run(run)
        session.status = SessionStatus.AWAITING_USER_INPUT
        session.pending_user_question = prompt
        session.active_run_id = run.run_id
        self.storage.save_session(session)
        input_node.metadata["_question_emitted"] = prompt
        self.storage.save_run(run)
        await self.emit(
            session.session_id,
            run.run_id,
            "task_node_waiting_user_input",
            {"node_id": input_node.node_id, "prompt": prompt, "question": prompt},
        )
        await self.emit(
            session.session_id,
            run.run_id,
            "awaiting_user_input",
            {"prompt": prompt, "question": prompt, "node_id": input_node.node_id},
        )
        await self._emit_task_graph(session.session_id, run)
        await self._append_assistant_message(session.session_id, run.run_id, prompt)

    async def _dispatch_ready_nodes(self, run_id: str, ready_nodes: list[TaskNode], *, auto_approve: bool) -> bool:
        prepared: list[dict[str, Any]] = []

        for selected in ready_nodes:
            run = self.storage.find_run(run_id)
            session = self.storage.load_session(run.session_id)
            current = self._task_node(run, selected.node_id)
            if current is None or current.status != TaskNodeStatus.READY:
                continue
            await self._mark_node_running(run, session, current)
            if current.kind in {TaskNodeKind.TOOL, TaskNodeKind.SUBAGENT}:
                launch = await self._prepare_external_node(run, session, current, auto_approve=auto_approve)
                if launch is None:
                    latest = self.storage.find_run(run_id)
                    return latest.status in TERMINAL_RUN_STATES or latest.status in {
                        RunStatus.AWAITING_APPROVAL,
                        RunStatus.AWAITING_USER_INPUT,
                    }
                prepared.append(launch)
                continue
            paused = await self._execute_task_node(run, session, current, auto_approve=auto_approve)
            latest = self.storage.find_run(run_id)
            if paused or latest.status in TERMINAL_RUN_STATES:
                return True

        if not prepared:
            return False

        results = await asyncio.gather(
            *(self._run_prepared_external_node(item) for item in prepared),
            return_exceptions=True,
        )
        for item, result in zip(prepared, results):
            paused = await self._finalize_external_node(item, result)
            latest = self.storage.find_run(run_id)
            if paused or latest.status in TERMINAL_RUN_STATES:
                return True
        return False

    async def _prepare_external_node(
        self,
        run: RunRecord,
        session: SessionRecord,
        node: TaskNode,
        *,
        auto_approve: bool,
    ) -> dict[str, Any] | None:
        if node.kind == TaskNodeKind.TOOL:
            action = self._build_action_for_node(run, node)
            blocked = await self._authorize_action(run, session, node, action, auto_approve=auto_approve)
            if blocked:
                return None
            latest = self.storage.find_run(run.run_id)
            latest.budget_usage.active_tools += 1
            self.storage.save_run(latest)
            await self._emit_budget_update(session.session_id, latest)
            return {
                "kind": node.kind.value,
                "run_id": run.run_id,
                "session_id": session.session_id,
                "node_id": node.node_id,
                "action": action,
            }

        if node.kind == TaskNodeKind.SUBAGENT:
            latest = self.storage.find_run(run.run_id)
            existing_grant = node.metadata.get("delegation_grant")
            if existing_grant:
                action = ActionRequest.model_validate(node.metadata["delegation_action"])
                grant = DelegationGrant.model_validate(existing_grant)
            else:
                action = self._build_action_for_node(run, node)
                blocked = await self._authorize_action(run, session, node, action, auto_approve=auto_approve)
                if blocked:
                    return None
                latest = self.storage.find_run(run.run_id)
                grant = self._ensure_delegation_grant(latest, node, action)
            latest.budget_usage.active_subagents += 1
            self.storage.save_run(latest)
            await self._emit_budget_update(session.session_id, latest)
            evidence_summaries: list[str] = []
            for evidence_id in latest.evidence_ids[-5:]:
                evidence = self.storage.load_evidence(evidence_id)
                evidence_summaries.append(f"{evidence.title}: {evidence.summary}")
            profile_name = self._subagent_profile_name(node)
            task = SubagentTask(
                task_id=new_id("subtask"),
                run_id=latest.run_id,
                node_id=node.node_id,
                goal=node.description,
                grant_id=grant.grant_id,
                evidence_summaries=evidence_summaries,
                allowed_tools=grant.allowed_tools,
                allowed_paths=grant.allowed_paths,
                allowed_domains=grant.allowed_domains,
            )
            return {
                "kind": node.kind.value,
                "run_id": latest.run_id,
                "session_id": session.session_id,
                "node_id": node.node_id,
                "profile_name": profile_name,
                "task": task,
                "grant": grant.model_dump(mode="json"),
                "auto_approve": auto_approve,
            }

        return None

    async def _run_prepared_external_node(self, item: dict[str, Any]) -> Any:
        if item["kind"] == TaskNodeKind.TOOL.value:
            action = item["action"]
            return await self.tools.execute(action.name, action.arguments)
        return await self._run_subagent_worker(item)

    async def _finalize_external_node(self, item: dict[str, Any], result: Any) -> bool:
        run = self.storage.find_run(item["run_id"])
        session = self.storage.load_session(run.session_id)
        node = self._task_node(run, item["node_id"])
        if node is None:
            return False

        if item["kind"] == TaskNodeKind.TOOL.value:
            run.budget_usage.active_tools = max(0, run.budget_usage.active_tools - 1)
            self.storage.save_run(run)
            await self._emit_budget_update(session.session_id, run)
            if isinstance(result, Exception):
                return await self._handle_node_execution_error(run, session, node, result)
            await self._record_tool_success(run.run_id, node.node_id, item["action"], result)
            refreshed = self.storage.find_run(run.run_id)
            await self._complete_node(refreshed, session, node.node_id)
            return False

        run.budget_usage.active_subagents = max(0, run.budget_usage.active_subagents - 1)
        self.storage.save_run(run)
        await self._emit_budget_update(session.session_id, run)
        if isinstance(result, Exception):
            return await self._handle_node_execution_error(run, session, node, result)
        if isinstance(result, dict) and result.get("status") == "paused":
            return True
        subagent = SubagentResult.model_validate(result)
        profile = self.profiles[item["profile_name"]]
        artifact = self.storage.save_artifact(
            session_id=session.session_id,
            run_id=run.run_id,
            kind="stdout",
            content=subagent.summary,
            mime_type="text/plain",
            suffix=".txt",
        )
        subagent.artifact_ids = [artifact.artifact_id]
        evidence = self._create_evidence(
            run=run,
            title=f"Subagent Result: {profile.name}",
            summary=subagent.summary,
            evidence_type="subagent_result",
            source={"tool_name": "subagent", "agent_id": profile.name},
            artifact_ids=[artifact.artifact_id],
            content=subagent.summary,
            facts=[
                {"key": "subagent_id", "value": subagent.subagent_id},
                {"key": "executed_action_count", "value": len(subagent.executed_action_ids)},
            ],
        )
        subagent.evidence_ids = [*subagent.evidence_ids, evidence.evidence_id]
        self._attach_node_outputs(run, node, artifact_ids=[artifact.artifact_id], evidence_ids=[evidence.evidence_id], summary=subagent.summary)
        delegation = node.metadata.get("delegation_action", node.action_request or {})
        if delegation:
            node.action_request = delegation
            node.action_id = delegation.get("action_id")
        self.storage.save_run(run)
        self.storage.append_audit(
            session.session_id,
            AuditEvent(
                event_id=new_id("audit"),
                timestamp=utc_now(),
                run_id=run.run_id,
                action_id=str(delegation.get("action_id") or new_id("act")),
                actor_agent_id=run.root_agent_id,
                decision=PermissionDecision.ALLOW,
                executor="subagent_runner",
                result="success",
                artifact_ids=[artifact.artifact_id],
                evidence_ids=[evidence.evidence_id],
                detail=subagent.summary,
                node_id=node.node_id,
            ),
        )
        await self.emit(
            session.session_id,
            run.run_id,
            "subagent",
            {"task": item["task"].model_dump(mode="json"), "result": subagent.model_dump(mode="json")},
        )
        await self.emit(session.session_id, run.run_id, "evidence_added", {"evidence_id": evidence.evidence_id, "title": evidence.title})
        await self._complete_node(run, session, node.node_id)
        return False

    async def _handle_node_execution_error(
        self,
        run: RunRecord,
        session: SessionRecord,
        node: TaskNode,
        error: Exception,
    ) -> bool:
        if node.retry_count < node.max_retries:
            node.retry_count += 1
            node.status = TaskNodeStatus.READY
            node.block_reason = f"retrying after error: {error}"
            self.graphs.refresh(run.task_graph)
            self.storage.save_run(run)
            await self._emit_task_graph(session.session_id, run)
            return False
        await self._fail_run(run, session, str(error), node_id=node.node_id)
        return True

    async def _execute_task_node(
        self,
        run: RunRecord,
        session: SessionRecord,
        node: TaskNode,
        *,
        auto_approve: bool,
    ) -> bool:
        if node.kind == TaskNodeKind.SKILL:
            return await self._execute_skill_node(run, session, node)
        if node.kind == TaskNodeKind.TOOL:
            return await self._execute_tool_node(run, session, node, auto_approve=auto_approve)
        if node.kind == TaskNodeKind.SUBAGENT:
            return await self._execute_subagent_node(run, session, node)
        if node.kind == TaskNodeKind.AGGREGATE:
            return await self._execute_aggregate_node(run, session, node)
        if node.kind == TaskNodeKind.REPORT:
            return await self._execute_report_node(run, session, node)
        if node.kind == TaskNodeKind.EXPORT:
            return await self._execute_export_node(run, session, node, auto_approve=auto_approve)
        if node.kind == TaskNodeKind.INPUT:
            return True
        return False

    async def _execute_skill_node(self, run: RunRecord, session: SessionRecord, node: TaskNode) -> bool:
        action = self._build_action_for_node(run, node)
        blocked = await self._authorize_action(run, session, node, action)
        if blocked:
            return True
        manifest = self.skills.load(node.metadata["skill_name"])
        bundle_text = self._skill_bundle_text(manifest)
        artifact = self.storage.save_artifact(
            session_id=session.session_id,
            run_id=run.run_id,
            kind="file",
            content=bundle_text,
            mime_type="text/markdown",
            suffix=".md",
        )
        evidence = self._create_evidence(
            run=run,
            title=f"Skill Loaded: {manifest.name}",
            summary=manifest.description,
            evidence_type="skill_context",
            source={
                "tool_name": "skill_consult",
                "path": manifest.path,
                "references": manifest.references,
                "agent_config_path": manifest.agent_config_path,
                "agent_id": "sisyphus",
            },
            artifact_ids=[artifact.artifact_id],
            content=bundle_text,
            facts=[
                {"key": "skill_name", "value": manifest.name},
                {"key": "reference_count", "value": len(manifest.references)},
                {"key": "allow_implicit_invocation", "value": manifest.allow_implicit_invocation},
                {"key": "downstream_only", "value": manifest.downstream_only},
            ],
        )
        self._attach_node_outputs(run, node, artifact_ids=[artifact.artifact_id], evidence_ids=[evidence.evidence_id], summary=manifest.description)
        self.storage.append_audit(
            session.session_id,
            AuditEvent(
                event_id=new_id("audit"),
                timestamp=utc_now(),
                run_id=run.run_id,
                action_id=action.action_id,
                actor_agent_id=action.actor_agent_id,
                decision=PermissionDecision.ALLOW,
                executor="skill_runner",
                result="success",
                artifact_ids=[artifact.artifact_id],
                evidence_ids=[evidence.evidence_id],
                detail=manifest.description,
                node_id=node.node_id,
            ),
        )
        await self.emit(session.session_id, run.run_id, "evidence_added", {"evidence_id": evidence.evidence_id, "title": evidence.title})
        await self._complete_node(run, session, node.node_id)
        return False

    async def _execute_tool_node(self, run: RunRecord, session: SessionRecord, node: TaskNode, *, auto_approve: bool) -> bool:
        action = self._build_action_for_node(run, node)
        blocked = await self._authorize_action(run, session, node, action, auto_approve=auto_approve)
        if blocked:
            return True
        run.budget_usage.active_tools += 1
        self.storage.save_run(run)
        await self._emit_budget_update(session.session_id, run)
        try:
            result = await self.tools.execute(action.name, action.arguments)
        finally:
            latest = self.storage.find_run(run.run_id)
            latest.budget_usage.active_tools = max(0, latest.budget_usage.active_tools - 1)
            self.storage.save_run(latest)
            await self._emit_budget_update(session.session_id, latest)
        await self._record_tool_success(run.run_id, node.node_id, action, result)
        refreshed = self.storage.find_run(run.run_id)
        await self._complete_node(refreshed, session, node.node_id)
        return False

    async def _execute_subagent_node(self, run: RunRecord, session: SessionRecord, node: TaskNode) -> bool:
        prepared = await self._prepare_external_node(run, session, node, auto_approve=False)
        if prepared is None:
            latest = self.storage.find_run(run.run_id)
            return latest.status in TERMINAL_RUN_STATES or latest.status in {
                RunStatus.AWAITING_APPROVAL,
                RunStatus.AWAITING_USER_INPUT,
            }
        result = await self._run_prepared_external_node(prepared)
        return await self._finalize_external_node(prepared, result)

    def _ensure_delegation_grant(self, run: RunRecord, node: TaskNode, action: ActionRequest) -> DelegationGrant:
        existing = node.metadata.get("delegation_grant")
        if existing:
            grant = DelegationGrant.model_validate(existing)
            node.grant_id = grant.grant_id
            return grant
        owner = self._subagent_profile_name(node)
        root_profile = self.profiles[run.profile_name]
        worker_profile = self.profiles[owner]
        allowed_tools = self._dedupe(
            [
                name
                for name in root_profile.tool_allowlist
                if name in worker_profile.tool_allowlist and name not in {"delegate_subagent", "report_export", "skill_consult"}
            ]
        )
        grant = DelegationGrant(
            grant_id=new_id("grant"),
            parent_action_id=action.action_id,
            run_id=run.run_id,
            node_id=node.node_id,
            delegator_profile_name=run.profile_name,
            delegatee_profile_name=owner,
            allowed_tools=allowed_tools,
            allowed_paths=list(run.scope.repo_paths),
            allowed_domains=list(run.scope.allowed_domains),
            max_tool_calls=min(root_profile.runtime_budget.max_tool_calls, worker_profile.runtime_budget.max_tool_calls),
            expires_at=None,
        )
        node.owner_profile_name = owner
        node.grant_id = grant.grant_id
        node.metadata["delegation_action"] = action.model_dump(mode="json")
        node.metadata["delegation_grant"] = grant.model_dump(mode="json")
        node.metadata.setdefault("worker_history", [])
        node.metadata.setdefault("worker_action_ids", [])
        return grant

    async def _run_subagent_worker(self, item: dict[str, Any]) -> SubagentResult | dict[str, Any]:
        run = self.storage.find_run(item["run_id"])
        session = self.storage.load_session(run.session_id)
        node = self._task_node(run, item["node_id"])
        if node is None:
            raise RuntimeError("subagent node disappeared before execution")
        grant = DelegationGrant.model_validate(item["grant"])
        history = list(node.metadata.get("worker_history", []))
        executed_ids = list(node.metadata.get("worker_action_ids", []))
        resumed = await self._resume_worker_action(run, session, node, grant, history, executed_ids)
        if resumed is not None:
            return resumed
        if self.settings.digagent_use_fake_model:
            summary = await self.agent.run_text_task(profile_name=item["profile_name"], task=self._subagent_summary_prompt(item["task"], history))
            return self._subagent_result(run, node, summary, executed_ids)
        return await self._drive_subagent_worker(run, session, node, item["task"], grant, history, executed_ids)

    async def _resume_worker_action(
        self,
        run: RunRecord,
        session: SessionRecord,
        node: TaskNode,
        grant: DelegationGrant,
        history: list[dict[str, Any]],
        executed_ids: list[str],
    ) -> dict[str, Any] | None:
        payload = node.metadata.get("worker_pending_action")
        if not payload:
            return None
        action = ActionRequest.model_validate(payload)
        result = await self._execute_worker_tool_action(run, session, node, grant, action)
        if isinstance(result, dict):
            return result
        self._record_worker_step(run, node, history, executed_ids, action, result)
        return None

    async def _drive_subagent_worker(
        self,
        run: RunRecord,
        session: SessionRecord,
        node: TaskNode,
        task: SubagentTask,
        grant: DelegationGrant,
        history: list[dict[str, Any]],
        executed_ids: list[str],
    ) -> SubagentResult | dict[str, Any]:
        max_turns = max(1, grant.max_tool_calls + 1)
        for _ in range(max_turns):
            prompt = self._subagent_worker_prompt(run, task, grant, history)
            raw = await self.agent.run_text_task(profile_name=grant.delegatee_profile_name, task=prompt)
            payload = json.loads(raw)
            if payload.get("type") == "final":
                return self._subagent_result(run, node, str(payload.get("summary") or ""), executed_ids, payload)
            action = self._build_worker_action(run, node, grant, payload)
            result = await self._execute_worker_tool_action(run, session, node, grant, action)
            if isinstance(result, dict):
                return result
            self._record_worker_step(run, node, history, executed_ids, action, result)
        raise RuntimeError("subagent exhausted delegated tool budget without returning a final answer")

    def _subagent_worker_prompt(
        self,
        run: RunRecord,
        task: SubagentTask,
        grant: DelegationGrant,
        history: list[dict[str, Any]],
    ) -> str:
        return (
            "Return only JSON.\n"
            "You are a delegated specialist worker inside a controlled runtime.\n"
            "Allowed outputs:\n"
            '1) {"type":"tool_call","tool_name":"...","arguments":{...},"justification":"..."}\n'
            '2) {"type":"final","summary":"...","recommended_next_actions":["..."]}\n'
            "Use only tools from allowed_tools. Do not ask for nested delegation. Do not write reports or memory.\n\n"
            f"user_task: {run.user_task}\n"
            f"goal: {task.goal}\n"
            f"allowed_tools: {json.dumps(grant.allowed_tools, ensure_ascii=False)}\n"
            f"evidence: {json.dumps(task.evidence_summaries, ensure_ascii=False)}\n"
            f"history: {json.dumps(history, ensure_ascii=False)}"
        )

    def _subagent_summary_prompt(self, task: SubagentTask, history: list[dict[str, Any]]) -> str:
        return (
            f"Task: {task.goal}\n\n"
            f"Evidence:\n- " + "\n- ".join(task.evidence_summaries or ["No evidence yet"]) + "\n\n"
            + (f"History:\n{json.dumps(history, ensure_ascii=False)}\n\n" if history else "")
            + "Return a concise expert summary and next actions."
        )

    def _build_worker_action(
        self,
        run: RunRecord,
        node: TaskNode,
        grant: DelegationGrant,
        payload: dict[str, Any],
    ) -> ActionRequest:
        tool_name = str(payload.get("tool_name") or "")
        if tool_name not in grant.allowed_tools:
            raise RuntimeError(f"subagent requested disallowed tool '{tool_name}'")
        manifest = self.tools.load(tool_name)
        arguments = dict(payload.get("arguments") or {})
        inferred = self._infer_action_targets(tool_name, arguments)
        default_targets = manifest.default_targets.model_dump(mode="json")
        return ActionRequest(
            action_id=new_id("act"),
            run_id=run.run_id,
            actor_agent_id=grant.delegatee_profile_name,
            action_type=ActionType.TOOL,
            name=tool_name,
            arguments=arguments,
            targets=ActionTargets(
                paths=self._dedupe(default_targets.get("paths", []) + inferred["paths"]),
                domains=self._dedupe(default_targets.get("domains", []) + inferred["domains"]),
            ),
            justification=str(payload.get("justification") or node.description),
            risk_tags=manifest.risk_tags,
            created_at=utc_now(),
            node_id=node.node_id,
        )

    async def _execute_worker_tool_action(
        self,
        run: RunRecord,
        session: SessionRecord,
        node: TaskNode,
        grant: DelegationGrant,
        action: ActionRequest,
    ) -> ToolExecutionResult | dict[str, Any]:
        node.metadata["worker_pending_action"] = action.model_dump(mode="json")
        self.storage.save_run(run)
        blocked = await self._authorize_action(
            run,
            session,
            node,
            action,
            actor_profile_name=grant.delegatee_profile_name,
            scope_override=Scope(repo_paths=grant.allowed_paths, allowed_domains=grant.allowed_domains),
        )
        if blocked:
            return {"status": "paused"}
        latest = self.storage.find_run(run.run_id)
        latest.budget_usage.active_tools += 1
        self.storage.save_run(latest)
        await self._emit_budget_update(session.session_id, latest)
        try:
            result = await self.tools.execute(action.name, action.arguments)
        finally:
            refreshed = self.storage.find_run(run.run_id)
            refreshed.budget_usage.active_tools = max(0, refreshed.budget_usage.active_tools - 1)
            self.storage.save_run(refreshed)
            await self._emit_budget_update(session.session_id, refreshed)
        await self._record_tool_success(run.run_id, node.node_id, action, result)
        return result

    def _record_worker_step(
        self,
        run: RunRecord,
        node: TaskNode,
        history: list[dict[str, Any]],
        executed_ids: list[str],
        action: ActionRequest,
        result: ToolExecutionResult,
    ) -> None:
        executed_ids.append(action.action_id)
        history.append({"tool": action.name, "summary": result.summary})
        latest = self.storage.find_run(run.run_id)
        current = self._task_node(latest, node.node_id)
        if current is None:
            return
        current.metadata["worker_history"] = history
        current.metadata["worker_action_ids"] = executed_ids
        current.metadata.pop("worker_pending_action", None)
        self.storage.save_run(latest)

    def _subagent_result(
        self,
        run: RunRecord,
        node: TaskNode,
        summary: str,
        executed_ids: list[str],
        payload: dict[str, Any] | None = None,
    ) -> SubagentResult:
        return SubagentResult(
            subagent_id=new_id("sub"),
            status="completed",
            summary=summary,
            evidence_ids=run.evidence_ids[-5:],
            artifact_ids=[],
            recommended_next_actions=list((payload or {}).get("recommended_next_actions") or self._next_action_titles(run, node.node_id)),
            executed_action_ids=executed_ids,
            memory_candidates=[],
        )

    def _infer_action_targets(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, list[str]]:
        if tool_name == "repo_search":
            return {"paths": [str(path) for path in arguments.get("repo_paths", [])], "domains": []}
        if tool_name == "web_fetch":
            hostname = urlparse(str(arguments.get("url") or "")).hostname
            return {"paths": [], "domains": [hostname] if hostname else []}
        if tool_name == "shell_exec":
            cwd = str(arguments.get("cwd") or self.settings.workspace_root)
            return {"paths": [cwd], "domains": []}
        return {"paths": [], "domains": []}

    async def _execute_aggregate_node(self, run: RunRecord, session: SessionRecord, node: TaskNode) -> bool:
        summaries = [self.storage.load_evidence(ev).summary for ev in run.evidence_ids[-6:]]
        prompt = (
            f"用户任务：{run.user_task}\n\n"
            "请基于下面的证据写一段简洁结论。"
            "如果存在最终答案或高置信度结论，请明确指出；如果仍不确定，就明确说明当前只是候选判断。"
            "不要编造未被证据支持的结论。\n\n"
            + "\n".join(f"- {line}" for line in summaries)
        )
        if run.followup_messages:
            prompt += "\n- 用户补充要求: " + "；".join(run.followup_messages)
        aggregate_text = (await self.agent.run_text_task(profile_name=run.profile_name, task=prompt)).strip()
        if not aggregate_text:
            aggregate_text = "已完成证据汇总。" + ("\n" + "\n".join(f"- {line}" for line in summaries) if summaries else "")
        aggregate_facts = [{"key": "intent_labels", "value": ",".join((run.intent_profile.labels if run.intent_profile else []))}]
        aggregate_candidates = self._extract_flag_candidates(aggregate_text)
        if aggregate_candidates:
            aggregate_facts.append({"key": "candidate_flag", "value": aggregate_candidates[0]})
        artifact = self.storage.save_artifact(
            session_id=session.session_id,
            run_id=run.run_id,
            kind="stdout",
            content=aggregate_text,
            mime_type="text/plain",
            suffix=".txt",
        )
        evidence = self._create_evidence(
            run=run,
            title="Aggregated Analysis",
            summary=aggregate_text,
            evidence_type="analysis_summary",
            source={"tool_name": "aggregate", "agent_id": run.root_agent_id},
            artifact_ids=[artifact.artifact_id],
            content=aggregate_text,
            facts=aggregate_facts,
        )
        self._attach_node_outputs(run, node, artifact_ids=[artifact.artifact_id], evidence_ids=[evidence.evidence_id], summary=aggregate_text)
        run.final_response = aggregate_text
        node.summary = aggregate_text
        self.storage.save_run(run)
        await self.emit(run.session_id, run.run_id, "aggregate", {"summary": run.final_response, "node_id": node.node_id})
        await self.emit(run.session_id, run.run_id, "evidence_added", {"evidence_id": evidence.evidence_id, "title": evidence.title})
        await self._complete_node(run, session, node.node_id, summary=run.final_response)
        return False

    async def _execute_report_node(self, run: RunRecord, session: SessionRecord, node: TaskNode) -> bool:
        dossier = self._build_report_dossier(run)
        try:
            validated = await self._validated_report_draft(dossier)
        except Exception as exc:
            await self._fail_run(run, session, f"report generation failed: {exc}", node_id=node.node_id)
            return True
        report = self._report_from_draft(run, validated)
        markdown = self.reporter.render_markdown(report)
        report.export_paths["markdown"] = str(self.storage.report_markdown_path(report.report_id))
        self.storage.save_report(report, markdown)
        run.report_id = report.report_id
        run.memory_candidate_ids = []
        run.final_response = f"{report.summary}\nMarkdown: {report.export_paths['markdown']}"
        node.summary = report.summary
        node.metadata["report_id"] = report.report_id
        self.storage.save_run(run)
        self.storage.append_audit(
            run.session_id,
            AuditEvent(
                event_id=new_id("audit"),
                timestamp=utc_now(),
                run_id=run.run_id,
                action_id=new_id("act"),
                actor_agent_id=run.root_agent_id,
                decision=PermissionDecision.ALLOW,
                executor="report_runner",
                result="success",
                detail="markdown export completed",
                node_id=node.node_id,
            ),
        )
        if report.writer_summary:
            await self._append_assistant_message(run.session_id, run.run_id, report.writer_summary)
        await self.emit(run.session_id, run.run_id, "report_ready", {"report_id": report.report_id, "markdown_path": report.export_paths["markdown"], "node_id": node.node_id})
        await self._complete_node(run, session, node.node_id, summary=report.summary)
        return False

    async def _execute_export_node(self, run: RunRecord, session: SessionRecord, node: TaskNode, *, auto_approve: bool) -> bool:
        if not run.report_id:
            await self._complete_node(run, session, node.node_id, summary="no report to export")
            return False
        report = self.storage.load_report(run.report_id)
        markdown_path = self.storage.report_markdown_path(run.report_id)
        html_path = markdown_path.with_suffix(".html")
        html_path.write_text(self.reporter.render_html(markdown_path.read_text(encoding="utf-8"), report.title), encoding="utf-8")
        action = self._build_action_for_node(run, node)
        blocked = await self._authorize_action(run, session, node, action, auto_approve=auto_approve)
        if blocked:
            return True
        pdf_path = self.storage.report_pdf_path(run.report_id)
        try:
            pdf_bytes = self.reporter.export_pdf(html_path, pdf_path)
        except Exception as exc:
            await self._fail_run(run, session, f"pdf export failed: {exc}", node_id=node.node_id)
            return True
        report.export_paths["pdf"] = str(pdf_path)
        markdown = markdown_path.read_text(encoding="utf-8")
        self.storage.save_report(report, markdown, pdf_bytes=pdf_bytes)
        run.final_response = f"{report.summary}\nMarkdown: {report.export_paths['markdown']}\nPDF: {report.export_paths['pdf']}"
        node.metadata["report_id"] = report.report_id
        node.metadata["pdf_path"] = report.export_paths["pdf"]
        self.storage.save_run(run)
        self.storage.append_audit(
            run.session_id,
            AuditEvent(
                event_id=new_id("audit"),
                timestamp=utc_now(),
                run_id=run.run_id,
                action_id=action.action_id,
                actor_agent_id=run.root_agent_id,
                decision=PermissionDecision.ALLOW,
                executor="report_runner",
                result="success",
                detail="pdf export completed",
                node_id=node.node_id,
            ),
        )
        await self.emit(run.session_id, run.run_id, "export", {"pdf_path": report.export_paths["pdf"], "node_id": node.node_id})
        await self._complete_node(run, session, node.node_id, summary=report.summary)
        return False

    async def _record_tool_success(
        self,
        run_id: str,
        node_id: str,
        action: ActionRequest,
        result: ToolExecutionResult,
    ) -> None:
        run = self.storage.find_run(run_id)
        session = self.storage.load_session(run.session_id)
        node = self._task_node(run, node_id)
        if node is None:
            raise RuntimeError("task node disappeared while recording tool output")
        run.budget_usage.tool_calls_used += 1
        artifact = self.storage.save_artifact(
            session_id=session.session_id,
            run_id=run.run_id,
            kind=result.artifact_kind,
            content=result.raw_output,
            mime_type=result.mime_type,
            suffix=".json" if result.mime_type == "application/json" else ".txt",
        )
        evidence = self._create_evidence(
            run=run,
            title=result.title,
            summary=result.summary,
            evidence_type="tool_output",
            source={**result.source, "agent_id": action.actor_agent_id},
            artifact_ids=[artifact.artifact_id],
            content=result.raw_output,
            facts=result.structured_facts,
        )
        self._attach_node_outputs(run, node, artifact_ids=[artifact.artifact_id], evidence_ids=[evidence.evidence_id], summary=result.summary)
        if action.action_id in run.pending_actions:
            run.pending_actions.remove(action.action_id)
        self.storage.save_run(run)
        self.storage.append_audit(
            session.session_id,
            AuditEvent(
                event_id=new_id("audit"),
                timestamp=utc_now(),
                run_id=run.run_id,
                action_id=action.action_id,
                actor_agent_id=action.actor_agent_id,
                decision=PermissionDecision.ALLOW,
                executor="tool_runner",
                result="success",
                exit_code=next((fact["value"] for fact in result.structured_facts if fact["key"] == "exit_code"), 0),
                artifact_ids=[artifact.artifact_id],
                evidence_ids=[evidence.evidence_id],
                detail=result.summary,
                node_id=node.node_id,
            ),
        )
        await self.emit(
            run.session_id,
            run.run_id,
            "tool_result",
            {"title": result.title, "summary": result.summary, "evidence_id": evidence.evidence_id, "node_id": node.node_id},
        )
        await self.emit(run.session_id, run.run_id, "evidence_added", {"evidence_id": evidence.evidence_id, "title": evidence.title})
        await self._emit_budget_update(session.session_id, run)

    async def _authorize_action(
        self,
        run: RunRecord,
        session: SessionRecord,
        node: TaskNode,
        action: ActionRequest,
        *,
        actor_profile_name: str | None = None,
        scope_override: Scope | None = None,
        auto_approve: bool = False,
    ) -> bool:
        profile = self.profiles[actor_profile_name or run.profile_name]
        self._refresh_budget_usage(run)
        outcome = self.permissions.decide(action, profile, scope_override or run.scope, run.budget_usage)
        node.action_request = action.model_dump(mode="json")
        node.action_id = action.action_id
        node.metadata["permission_reason"] = outcome.reason
        node.metadata["normalized_targets"] = outcome.normalized_targets.model_dump(mode="json")
        self.storage.save_run(run)

        if outcome.decision == PermissionDecision.DENY:
            self.storage.append_audit(
                run.session_id,
                AuditEvent(
                    event_id=new_id("audit"),
                    timestamp=utc_now(),
                    run_id=run.run_id,
                    action_id=action.action_id,
                    actor_agent_id=action.actor_agent_id,
                    decision=PermissionDecision.DENY,
                    executor="policy",
                    result="blocked",
                    detail=outcome.reason,
                    node_id=node.node_id,
                ),
            )
            await self._fail_run(run, session, outcome.reason, node_id=node.node_id)
            return True

        if outcome.decision == PermissionDecision.CONFIRM:
            approval = self._get_or_create_approval(run, node, action)
            if auto_approve and approval.status != ApprovalStatus.APPROVED:
                approval_token = self._approval_token_value(approval, approved=True, resolver="auto")
                await self.approve(
                    approval.approval_id,
                    approved=True,
                    resolver="auto",
                    reason="auto-approve enabled",
                    approval_token=approval_token,
                    resume_run=False,
                )
                approval = self.storage.load_approval(approval.approval_id)
            if approval.status != ApprovalStatus.APPROVED:
                node.status = TaskNodeStatus.WAITING_APPROVAL
                node.block_reason = outcome.reason
                node.approval_id = approval.approval_id
                run.status = RunStatus.AWAITING_APPROVAL
                run.awaiting_reason = outcome.reason
                run.resume_from_action_id = action.action_id
                if approval.approval_id not in run.approval_ids:
                    run.approval_ids.append(approval.approval_id)
                if action.action_id not in run.pending_actions:
                    run.pending_actions.append(action.action_id)
                self.graphs.refresh(run.task_graph)
                self.storage.save_run(run)
                if approval.approval_id not in session.pending_approval_ids:
                    session.pending_approval_ids.append(approval.approval_id)
                session.status = SessionStatus.AWAITING_APPROVAL
                session.active_run_id = run.run_id
                session.pending_user_question = None
                self.storage.save_session(session)
                self.storage.append_audit(
                    run.session_id,
                    AuditEvent(
                        event_id=new_id("audit"),
                        timestamp=utc_now(),
                        run_id=run.run_id,
                        action_id=action.action_id,
                        actor_agent_id=action.actor_agent_id,
                        decision=PermissionDecision.CONFIRM,
                        executor="policy",
                        result="blocked",
                        detail=outcome.reason,
                        node_id=node.node_id,
                    ),
                )
                await self.emit(run.session_id, run.run_id, "task_node_waiting_approval", {"node_id": node.node_id, "reason": outcome.reason})
                await self._emit_task_graph(run.session_id, run)
                await self.emit(
                    run.session_id,
                    run.run_id,
                    "approval_required",
                    {
                        "approval_id": approval.approval_id,
                        "action_id": action.action_id,
                        "name": action.name,
                        "reason": outcome.reason,
                        "targets": action.targets.model_dump(mode="json"),
                        "challenge": self._approval_challenge(approval).model_dump(mode="json"),
                        "node_id": node.node_id,
                    },
                )
                await self.emit(run.session_id, run.run_id, "run_status", {"status": run.status.value})
                return True

            if approval.action_digest != self._approval_digest(action):
                await self._fail_run(
                    run,
                    session,
                    "approved action digest no longer matches the pending action",
                    node_id=node.node_id,
                )
                return True

        return False

    def _get_or_create_approval(self, run: RunRecord, node: TaskNode, action: ActionRequest) -> ApprovalRecord:
        existing_id = node.approval_id or node.metadata.get("approval_id")
        if existing_id:
            approval = self.storage.load_approval(existing_id)
            if not approval.challenge:
                approval.challenge = self._approval_challenge_value(approval.approval_id, approval.action_digest)
                approval.challenge_issued_at = utc_now()
                self.storage.save_approval(approval)
            return approval
        approval = ApprovalRecord(
            approval_id=new_id("apr"),
            action_id=action.action_id,
            run_id=run.run_id,
            status=ApprovalStatus.PENDING,
            action_digest=self._approval_digest(action),
            requested_by=action.actor_agent_id,
            requested_at=utc_now(),
            challenge_issued_at=utc_now(),
            node_id=node.node_id,
        )
        approval.challenge = self._approval_challenge_value(approval.approval_id, approval.action_digest)
        self.storage.save_approval(approval)
        node.approval_id = approval.approval_id
        node.metadata["approval_id"] = approval.approval_id
        return approval

    def _build_action_for_node(self, run: RunRecord, node: TaskNode) -> ActionRequest:
        payload = node.action_request
        if payload:
            return ActionRequest.model_validate(payload)
        if node.kind == TaskNodeKind.SKILL:
            skill_root = self.settings.data_dir / "skills" / node.metadata["skill_name"]
            return ActionRequest(
                action_id=new_id("act"),
                run_id=run.run_id,
                actor_agent_id=run.root_agent_id,
                action_type=ActionType.SKILL,
                name="skill_consult",
                arguments={"skill_name": node.metadata["skill_name"]},
                targets=ActionTargets(paths=[str(skill_root)]),
                justification=node.description,
                risk_tags=[],
                created_at=utc_now(),
                node_id=node.node_id,
            )
        if node.kind == TaskNodeKind.TOOL:
            manifest = self.tools.load(node.metadata["tool_name"])
            target_payload = node.metadata.get("targets", {})
            default_targets = manifest.default_targets.model_dump(mode="json")
            return ActionRequest(
                action_id=new_id("act"),
                run_id=run.run_id,
                actor_agent_id=run.root_agent_id,
                action_type=ActionType.TOOL,
                name=node.metadata["tool_name"],
                arguments=node.metadata.get("arguments", {}),
                targets=ActionTargets(
                    paths=self._dedupe(default_targets.get("paths", []) + target_payload.get("paths", [])),
                    domains=self._dedupe(default_targets.get("domains", []) + target_payload.get("domains", [])),
                ),
                justification=node.description,
                risk_tags=node.metadata.get("risk_tags", manifest.risk_tags),
                created_at=utc_now(),
                node_id=node.node_id,
            )
        if node.kind == TaskNodeKind.EXPORT:
            return ActionRequest(
                action_id=new_id("act"),
                run_id=run.run_id,
                actor_agent_id=run.root_agent_id,
                action_type=ActionType.EXPORT,
                name="report_export",
                arguments={"format": node.metadata.get("format", "pdf")},
                justification=node.description,
                targets=ActionTargets(),
                risk_tags=node.metadata.get("risk_tags", []),
                created_at=utc_now(),
                node_id=node.node_id,
            )
        if node.kind == TaskNodeKind.SUBAGENT:
            owner = self._subagent_profile_name(node)
            return ActionRequest(
                action_id=new_id("act"),
                run_id=run.run_id,
                actor_agent_id=run.root_agent_id,
                action_type=ActionType.SUBAGENT,
                name="delegate_subagent",
                arguments={
                    "owner_profile_name": owner,
                    "goal": node.description,
                    "title": node.title,
                },
                justification=node.description,
                targets=ActionTargets(
                    paths=list(run.scope.repo_paths),
                    domains=list(run.scope.allowed_domains),
                ),
                risk_tags=node.metadata.get("risk_tags", []),
                created_at=utc_now(),
                node_id=node.node_id,
            )
        raise ValueError(f"Unsupported task node for action: {node.kind}")

    def _create_evidence(
        self,
        *,
        run: RunRecord,
        title: str,
        summary: str,
        evidence_type: str,
        source: dict[str, Any],
        artifact_ids: list[str],
        content: str,
        facts: list[dict[str, Any]],
    ) -> EvidenceRecord:
        evidence = EvidenceRecord(
            evidence_id=new_id("ev"),
            session_id=run.session_id,
            run_id=run.run_id,
            type=evidence_type,
            title=title,
            summary=summary,
            source=source,
            artifact_refs=artifact_ids,
            hash=action_digest({"title": title, "summary": summary, "content": content}),
            content_ref=f"artifact://{artifact_ids[0]}" if artifact_ids else None,
            structured_facts=facts,
            created_at=utc_now(),
        )
        self.storage.save_evidence(evidence)
        return evidence

    async def _commit_memory(self, run: RunRecord) -> None:
        report = self.storage.load_report(run.report_id) if run.report_id else None
        evidence_payloads = [self.storage.load_evidence(evidence_id).model_dump(mode="json") for evidence_id in run.evidence_ids]
        if report is None and not evidence_payloads:
            return

        draft = ReportDraft(
            kind=report.kind if report else "analysis_note",
            title=report.title if report else f"Run {run.run_id}",
            summary=report.summary if report else (run.final_response or "阶段性运行结果"),
            findings=report.findings if report else [],
            limitations=report.limitations if report else [],
            writer_summary=report.writer_summary if report else None,
            evidence_refs=report.evidence_refs if report else run.evidence_ids[:6],
        )
        curation = await self.agent.curate_memory(
            profile_name=self._curator_profile().name,
            task=run.user_task,
            intent_profile=run.intent_profile,
            report=draft,
            evidence=evidence_payloads,
            session_id=run.session_id,
            run_id=run.run_id,
        )

        daily_note = DailyMemoryNote.model_validate(curation["daily_note"])
        self.storage.append_daily_memory(daily_note)

        memory_markdown = self.storage.load_memory_markdown().rstrip() + "\n"
        index = self.storage.load_memory_index()
        index_items = index.get("items", [])
        seen_summaries = {item.get("summary") for item in index_items}

        for candidate_payload in curation.get("memory_candidates", []):
            candidate = MemoryPromotionCandidate.model_validate(candidate_payload)
            if candidate.summary in seen_summaries:
                continue
            memory = MemoryRecord(
                memory_id=new_id("mem"),
                kind=candidate.kind,
                summary=candidate.summary,
                content=candidate.content,
                source_session_id=run.session_id,
                source_run_id=run.run_id,
                source_evidence_ids=candidate.source_evidence_ids,
                confidence=candidate.confidence,
                sensitivity=candidate.sensitivity,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            self.storage.save_memory(memory)
            run.memory_candidate_ids.append(memory.memory_id)
            seen_summaries.add(candidate.summary)
            index_items.append(
                {
                    "memory_id": memory.memory_id,
                    "kind": memory.kind,
                    "summary": memory.summary,
                    "source_run_id": memory.source_run_id,
                    "source_evidence_ids": memory.source_evidence_ids,
                    "updated_at": memory.updated_at,
                }
            )
            memory_markdown += f"\n## {memory.kind}: {memory.summary}\n\n"
            memory_markdown += json.dumps(memory.content, ensure_ascii=False, indent=2) + "\n"

        wiki_ids: list[str] = []
        for wiki_payload in curation.get("wiki_entries", []):
            entry = WikiEntry.model_validate(wiki_payload)
            self.storage.save_wiki_entry(entry)
            wiki_ids.append(entry.entry_id)
            index_items.append(
                {
                    "wiki_entry_id": entry.entry_id,
                    "summary": entry.summary,
                    "title": entry.title,
                    "source_run_id": entry.source_run_id,
                    "updated_at": entry.updated_at,
                }
            )

        self.storage.save_memory_markdown(memory_markdown.rstrip() + "\n")
        self.storage.save_memory_index({"items": index_items})
        if wiki_ids:
            run.memory_candidate_ids.extend(wiki_ids)
        self.storage.save_run(run)

    def _extract_flag_candidates(self, text: str | None) -> list[str]:
        if not text:
            return []
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in re.findall(r"[A-Za-z0-9_]+\{[^}\n]+\}", text):
            if candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        return ordered

    def _best_ctf_flag_candidate(self, run: RunRecord, evidences: list[EvidenceRecord]) -> tuple[str | None, list[str]]:
        scored: list[tuple[int, str, list[str]]] = []
        seen: set[str] = set()

        def add_candidate(value: str, refs: list[str], *, base_score: int) -> None:
            if not value or value in seen:
                return
            score = base_score + (25 if value.lower().startswith("flag{") else 0)
            seen.add(value)
            scored.append((score, value, refs[:3]))

        for evidence in evidences:
            refs = [evidence.evidence_id]
            source_name = str(evidence.source.get("tool_name") or "")
            source_bonus = 20 if source_name in {"aggregate", "subagent"} or evidence.type == "subagent_result" else 0
            for fact in evidence.structured_facts:
                if fact.get("key") in {"candidate_flag", "final_flag", "decoded_flag"}:
                    add_candidate(str(fact.get("value") or ""), refs, base_score=70 + source_bonus)
            for candidate in self._extract_flag_candidates(f"{evidence.title}\n{evidence.summary}"):
                add_candidate(candidate, refs, base_score=55 + source_bonus)
            for artifact_id in evidence.artifact_refs[:1]:
                try:
                    artifact_text = self.storage.load_artifact_bytes(artifact_id).decode("utf-8", errors="ignore")
                except OSError:
                    artifact_text = ""
                for candidate in self._extract_flag_candidates(artifact_text):
                    add_candidate(candidate, refs, base_score=50 + source_bonus)

        for candidate in self._extract_flag_candidates(run.final_response):
            add_candidate(candidate, [evidences[-1].evidence_id] if evidences else [], base_score=65)

        if not scored:
            return None, []
        scored.sort(key=lambda item: item[0], reverse=True)
        _, value, refs = scored[0]
        return value, refs

    def _build_report_dossier(self, run: RunRecord) -> ReportDossier:
        evidences = [self.storage.load_evidence(evidence_id) for evidence_id in run.evidence_ids]
        artifacts = [self.storage.load_artifact(artifact_id) for artifact_id in run.artifact_ids]
        memory_hits = self._memory_hits_for_query(run.user_task, session_id=run.session_id, run_id=run.run_id)
        completed_nodes = []
        if run.task_graph:
            completed_nodes = [
                {
                    "node_id": node.node_id,
                    "title": node.title,
                    "kind": node.kind.value,
                    "summary": node.summary,
                    "evidence_refs": node.evidence_refs,
                    "artifact_refs": node.artifact_refs,
                }
                for node in run.task_graph.nodes
                if node.status == TaskNodeStatus.COMPLETED
            ]
        return ReportDossier(
            user_task=run.user_task,
            scope=run.scope,
            intent_profile=run.intent_profile,
            task_graph=run.task_graph or TaskGraph(run_id=run.run_id),
            goal_summary=run.intent_profile.objective if run.intent_profile else run.user_task,
            completed_nodes=completed_nodes,
            completed_node_kinds=[node["kind"] for node in completed_nodes],
            source_evidence_types=sorted({evidence.type for evidence in evidences}),
            evidence=[evidence.model_dump(mode="json") for evidence in evidences],
            artifacts=[artifact.model_dump(mode="json") for artifact in artifacts[:12]],
            retrieved_memory=[hit.model_dump(mode="json") for hit in memory_hits],
            followup_messages=run.followup_messages,
        )

    def _validate_report_draft(self, draft: ReportDraft, dossier: ReportDossier) -> ReportDraft:
        validated = self.report_validator.validate(draft, dossier)
        limitations = validated.limitations
        if dossier.followup_messages:
            limitations = limitations + ["已合并用户补充要求：" + "；".join(dossier.followup_messages)]
        return ReportDraft(
            kind=validated.kind,
            title=validated.title or self._report_title(dossier, validated.kind),
            summary=validated.summary,
            findings=validated.findings,
            limitations=limitations,
            writer_summary=validated.writer_summary or "我已基于当前证据和任务图完成报告整理。",
            evidence_refs=validated.evidence_refs,
        )

    def _report_from_draft(self, run: RunRecord, draft: ReportDraft) -> ReportRecord:
        return ReportRecord(
            report_id=new_id("rep"),
            session_id=run.session_id,
            run_id=run.run_id,
            kind=draft.kind,
            title=draft.title,
            scope={
                "targets": run.scope.artifacts or run.scope.allowed_domains or run.scope.repo_paths,
                "constraints": ["controlled_actions_only"],
            },
            summary=draft.summary,
            findings=draft.findings,
            limitations=draft.limitations,
            export_paths={"markdown": str(self.storage.report_markdown_path("pending"))},
            writer_summary=draft.writer_summary,
            evidence_refs=draft.evidence_refs,
            generated_at=utc_now(),
        )

    async def _validated_report_draft(self, dossier: ReportDossier) -> ReportDraft:
        writer = self._writer_profile().name
        draft = await self.agent.write_report(profile_name=writer, dossier=dossier)
        try:
            return self._validate_report_draft(draft, dossier)
        except ReportValidationError as exc:
            retry_dossier = dossier.model_copy(
                update={
                    "followup_messages": [
                        *dossier.followup_messages,
                        f"validator_feedback: {exc}",
                    ]
                }
            )
            retried = await self.agent.write_report(profile_name=writer, dossier=retry_dossier)
            return self._validate_report_draft(retried, dossier)

    def _report_title(self, dossier: ReportDossier, kind: str) -> str:
        objective = dossier.intent_profile.objective if dossier.intent_profile else dossier.user_task
        compact = re.sub(r"\s+", " ", objective).strip()
        return compact[:80] or f"DigAgent {kind}"

    def _enrich_scope(self, task: str, scope: Scope) -> Scope:
        merged = Scope.model_validate(scope.model_dump(mode="json"))
        if not merged.repo_paths and any(token in task for token in ["源码", "代码", "repo", "项目", "仓库"]):
            merged.repo_paths = [str(self.settings.workspace_root)]
        if not merged.allowed_domains:
            url_matches = re.findall(r"https?://[^\s/$.?#].[^\s]*", task)
            domain_matches = re.findall(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b", task)
            domains = [urlparse(url).netloc for url in url_matches] or domain_matches
            if domains:
                merged.allowed_domains = [normalize_domain(domains[0])]
        return merged

    def _resolve_web_url(self, task: str, domain: str) -> str:
        match = re.search(r"https?://[^\s]+", task)
        if match:
            return match.group(0)
        if domain.startswith("127.0.0.1") or domain.startswith("localhost"):
            return f"http://{domain}"
        return f"https://{domain}"

    def _knowledge_lookup_arguments(self, task: str) -> dict[str, Any] | None:
        cve_match = re.search(r"\bCVE-\d{4}-\d+\b", task, re.IGNORECASE)
        if cve_match:
            return {"cve_id": cve_match.group(0).upper(), "limit": 5}
        cwe_match = re.search(r"\bCWE-\d+\b", task, re.IGNORECASE)
        if cwe_match:
            return {"cwe": cwe_match.group(0).upper(), "limit": 5}
        if "漏洞知识库" in task or "cve" in task.lower():
            return {"query": task[:160], "limit": 5}
        return None

    def _split_intents(self, content: str) -> list[str]:
        parts = re.split(r"(?:\n+|；|;|。|然后|并且|另外)\s*", content)
        intents = [part.strip() for part in parts if part and part.strip()]
        return intents or [content.strip()]

    def _merge_scope(self, base: Scope, overlay: Scope) -> Scope:
        return Scope(
            repo_paths=self._dedupe(base.repo_paths + overlay.repo_paths),
            allowed_domains=self._dedupe([normalize_domain(item) for item in base.allowed_domains + overlay.allowed_domains]),
            artifacts=self._dedupe(base.artifacts + overlay.artifacts),
        )

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            if value and value not in seen:
                seen.add(value)
                ordered.append(value)
        return ordered

    def _repair_session_state(self, session: SessionRecord) -> SessionRecord:
        if not session.active_run_id:
            if session.status != SessionStatus.ARCHIVED:
                session.status = SessionStatus.IDLE
            session.pending_approval_ids = []
            session.pending_user_question = None
            self.storage.save_session(session)
            return session
        try:
            run = self.storage.find_run(session.active_run_id)
        except FileNotFoundError:
            session.active_run_id = None
            session.status = SessionStatus.IDLE
            session.pending_approval_ids = []
            session.pending_user_question = None
            self.storage.save_session(session)
            return session
        if run.status in TERMINAL_RUN_STATES:
            session.active_run_id = None
            session.status = SessionStatus.IDLE
            session.pending_approval_ids = []
            session.pending_user_question = None
        elif run.status == RunStatus.AWAITING_APPROVAL:
            session.status = SessionStatus.AWAITING_APPROVAL
        elif run.status == RunStatus.AWAITING_USER_INPUT:
            session.status = SessionStatus.AWAITING_USER_INPUT
            session.pending_user_question = run.awaiting_reason
        else:
            session.status = SessionStatus.ACTIVE_RUN
        self.storage.save_session(session)
        return session

    def _active_run(self, session: SessionRecord) -> RunRecord | None:
        if not session.active_run_id:
            return None
        try:
            run = self.storage.find_run(session.active_run_id)
        except FileNotFoundError:
            session.active_run_id = None
            session.status = SessionStatus.IDLE
            self.storage.save_session(session)
            return None
        if run.status in TERMINAL_RUN_STATES:
            session.active_run_id = None
            session.status = SessionStatus.IDLE
            self.storage.save_session(session)
            return None
        return run

    async def _classify_message(
        self,
        session: SessionRecord,
        run: RunRecord | None,
        content: str,
    ) -> MessageRoutingDecision:
        graph = run.task_graph.model_dump(mode="json") if run and run.task_graph else {}
        pending_question = run.awaiting_reason if run else session.pending_user_question
        return await self.agent.classify_message(
            profile_name=self._planner_profile().name,
            user_message=content,
            session_status=session.status.value,
            run_status=run.status.value if run else None,
            graph=graph,
            pending_question=pending_question,
            pending_approvals=len(session.pending_approval_ids),
        )

    def _message_is_approval(self, content: str) -> bool:
        lower = content.lower()
        if any(marker in lower for marker in REJECT_MARKERS):
            return False
        return any(marker in lower for marker in APPROVE_MARKERS)

    def _is_restore_request(self, content: str) -> bool:
        lower = content.lower()
        return "恢复" in content or "resume" in lower

    def _session_title_from_message(self, content: str) -> str:
        first_line = content.strip().splitlines()[0] if content.strip() else "DigAgent Session"
        return first_line[:60]

    async def _build_direct_answer(self, session: SessionRecord, run: RunRecord | None, content: str) -> str:
        memory_hits = self._memory_hits_for_query(content, session_id=session.session_id, run_id=run.run_id if run else None)
        if run:
            graph = run.task_graph.model_dump(mode="json") if run.task_graph else {}
            return await self.agent.compose_direct_answer(
                profile_name=run.profile_name,
                user_question=content,
                session_status=session.status.value,
                run_status=run.status.value,
                graph=graph,
                evidence_summaries=self._recent_evidence_summaries(run),
                memory_hits=[hit.model_dump(mode="json") for hit in memory_hits],
                pending_approvals=len(session.pending_approval_ids),
                awaiting_reason=run.awaiting_reason,
                budget={
                    **run.budget.model_dump(mode="json"),
                    **run.budget_usage.model_dump(mode="json"),
                },
            )

        report_id = session.latest_report_id or session.last_report_id
        evidence_summaries: list[str] = []
        if report_id:
            report = self.storage.load_report(report_id)
            evidence_summaries.append(report.summary)
        return await self.agent.compose_direct_answer(
            profile_name=session.root_agent_profile,
            user_question=content,
            session_status=session.status.value,
            run_status=None,
            graph={},
            evidence_summaries=evidence_summaries,
            memory_hits=[hit.model_dump(mode="json") for hit in memory_hits],
            pending_approvals=len(session.pending_approval_ids),
            awaiting_reason=None,
            budget={},
        )

    async def _build_archived_answer(self, session: SessionRecord, content: str) -> str:
        base = await self._build_direct_answer(session, None, content)
        return base + "\n这个 session 目前处于 archived，我可以继续解释历史证据和报告，但不会直接启动新的 run。"

    def _profile(self, profile_name: str):
        return self.profiles[profile_name]

    def _planner_profile(self):
        return self._profile(PLANNER_PROFILE)

    def _writer_profile(self):
        return self._profile(WRITER_PROFILE)

    def _curator_profile(self):
        return self._profile(CURATOR_PROFILE)

    async def _plan_bundle(self, run: RunRecord):
        planner = self._planner_profile()
        memory_hits = self._memory_hits_for_query(run.user_task, session_id=run.session_id, run_id=run.run_id)
        result = await self.agent.plan_task_graph(
            run_id=run.run_id,
            profile_name=planner.name,
            task=run.user_task,
            scope=run.scope.model_dump(mode="json"),
            followup_messages=run.followup_messages,
            tool_allowlist=planner.tool_allowlist,
            available_specialists=self._available_specialist_profiles(),
            available_plugins=self.plugins.catalog(),
            available_skills=sorted(self.skills.load_all()),
            memory_hits=[hit.model_dump(mode="json") for hit in memory_hits],
        )
        bundle = self._normalize_planning_result(run, result)
        for node in bundle.task_graph.nodes:
            node.planning_phase = max(node.planning_phase, 0)
            if node.kind == TaskNodeKind.SUBAGENT:
                node.owner_profile_name = self._subagent_profile_name(node)
        return bundle

    def _subagent_profile_name(self, node: TaskNode) -> str:
        explicit = node.owner_profile_name or node.metadata.get("profile_name") or node.metadata.get("profile")
        if explicit:
            if explicit not in self._available_specialist_profiles():
                allowed = ", ".join(self._available_specialist_profiles())
                raise ValueError(f"subagent node '{node.node_id}' uses unsupported owner_profile_name '{explicit}'. Allowed: {allowed}")
            return explicit
        raise ValueError(f"subagent node '{node.node_id}' is missing owner_profile_name")

    async def _replan_after_user_input(
        self,
        run: RunRecord,
        session: SessionRecord,
        *,
        clarify_node_id: str | None,
    ) -> bool:
        anchor = self._task_node(run, clarify_node_id)
        planning = await self._plan_bundle(run)
        run.intent_profile = planning.intent_profile
        run.planner_summary = planning.planner_message
        if run.task_graph is None or anchor is None:
            run.task_graph = planning.task_graph
            self.graphs.refresh(run.task_graph)
            self.storage.save_run(run)
            await self._append_assistant_message(session.session_id, run.run_id, planning.planner_message)
            await self._emit_task_graph(session.session_id, run)
            return True

        self._replace_clarified_branch(run, anchor, planning.task_graph)
        self.storage.save_run(run)
        await self._append_assistant_message(session.session_id, run.run_id, planning.planner_message)
        await self._emit_task_graph(session.session_id, run)
        return True

    def _replace_clarified_branch(self, run: RunRecord, anchor: TaskNode, planned: TaskGraph) -> None:
        graph = run.task_graph
        if graph is None:
            run.task_graph = planned
            self.graphs.refresh(run.task_graph)
            return
        next_phase = anchor.planning_phase + 1
        roots = self._graph_roots(planned)
        root_source_ids = [node.node_id for node in roots]
        replacement_key = anchor.node_id
        for node in self.graphs.descendants(graph, anchor.node_id):
            node.status = TaskNodeStatus.DEPRECATED
            node.block_reason = CLARIFY_SUPERSEDED_REASON
            node.superseded_by = replacement_key
        existing_ids = {node.node_id for node in graph.nodes}
        remap: dict[str, str] = {}
        for node in planned.nodes:
            original_id = node.node_id
            node.node_id = original_id if original_id not in existing_ids else new_id("node")
            node.planning_phase = next_phase
            node.replanned_from_node_id = anchor.node_id
            remap[original_id] = node.node_id
            graph.nodes.append(node)
        if root_source_ids:
            replacement_key = remap[root_source_ids[0]]
            for node in self.graphs.descendants(graph, anchor.node_id):
                if node.block_reason == CLARIFY_SUPERSEDED_REASON:
                    node.superseded_by = replacement_key
        for edge in planned.edges:
            graph.edges.append(TaskEdge(source=remap[edge.source], target=remap[edge.target]))
        for root_id in root_source_ids:
            graph.edges.append(TaskEdge(source=anchor.node_id, target=remap[root_id]))
        graph.graph_version += 1
        self.graphs.refresh(graph)

    def _graph_roots(self, graph: TaskGraph) -> list[TaskNode]:
        root_ids = {node.node_id for node in graph.nodes}
        for edge in graph.edges:
            root_ids.discard(edge.target)
        return [node for node in graph.nodes if node.node_id in root_ids]

    def _preview_text(self, text: str | None, *, limit: int = 88) -> str | None:
        if not text:
            return None
        compact = " ".join(text.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 1].rstrip() + "…"

    def _recent_evidence_summaries(self, run: RunRecord, *, limit: int = 5) -> list[str]:
        summaries: list[str] = []
        for evidence_id in run.evidence_ids[-limit:]:
            evidence = self.storage.load_evidence(evidence_id)
            summaries.append(f"{evidence.title}: {evidence.summary}")
        return summaries

    def _skill_bundle_text(self, manifest) -> str:
        parts = [manifest.markdown]
        references = self._skill_reference_snippets(manifest)
        if references:
            parts.append("## References\n\n" + "\n\n".join(references))
        if manifest.agent_config_path:
            parts.append(
                "## Agent Interface\n"
                f"- config: {manifest.agent_config_path}\n"
                f"- implicit_invocation: {str(manifest.allow_implicit_invocation).lower()}"
            )
        return "\n\n".join(part for part in parts if part)

    def _skill_reference_snippets(self, manifest) -> list[str]:
        skill_root = Path(manifest.path).parent
        snippets: list[str] = []
        for relative in manifest.references[:6]:
            path = skill_root / relative
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore").strip()
            except OSError:
                continue
            if not text:
                continue
            snippets.append(f"### {relative}\n{text[:2200]}")
        return snippets

    def _memory_hits_for_query(self, query: str, *, session_id: str, run_id: str | None) -> list[MemoryHit]:
        return self.memory_search.search(
            query=query,
            session_id=session_id,
            run_id=run_id,
            scope="session",
            sensitivity="normal",
            limit=5,
        )

    def _available_specialist_profiles(self) -> list[str]:
        return sorted(
            name
            for name in self.profiles
            if name not in {PLANNER_PROFILE, WRITER_PROFILE, CURATOR_PROFILE, "sisyphus-default"}
        )

    def _normalize_planning_result(self, run: RunRecord, planning_result: Any):
        if hasattr(planning_result, "task_graph") and hasattr(planning_result, "intent_profile"):
            return planning_result
        raise TypeError("planner must return PlanningBundle")

    def _approval_digest(self, action: ActionRequest) -> str:
        return action_digest(
            {
                "run_id": action.run_id,
                "actor_agent_id": action.actor_agent_id,
                "name": action.name,
                "arguments": action.arguments,
                "targets": action.targets.model_dump(mode="json"),
                "node_id": action.node_id,
            }
        )

    def _approval_challenge_value(self, approval_id: str, action_digest_value: str) -> str:
        return action_digest({"approval_id": approval_id, "action_digest": action_digest_value, "kind": "approval_challenge"})

    def _approval_challenge(self, approval: ApprovalRecord) -> ApprovalChallenge:
        challenge = approval.challenge or self._approval_challenge_value(approval.approval_id, approval.action_digest)
        return ApprovalChallenge(
            approval_id=approval.approval_id,
            action_id=approval.action_id,
            action_digest=approval.action_digest,
            challenge=challenge,
            issued_at=approval.challenge_issued_at or approval.requested_at,
            expires_at=approval.challenge_expires_at,
        )

    def _approval_token_value(self, approval: ApprovalRecord, *, approved: bool, resolver: str) -> str:
        challenge = approval.challenge or self._approval_challenge_value(approval.approval_id, approval.action_digest)
        return action_digest(
            {
                "approval_id": approval.approval_id,
                "action_id": approval.action_id,
                "action_digest": approval.action_digest,
                "challenge": challenge,
                "approved": approved,
                "resolver": resolver,
            }
        )

    def _refresh_budget_usage(self, run: RunRecord) -> None:
        elapsed = run.budget_usage.runtime_seconds_used
        if run.started_at:
            try:
                started = datetime.fromisoformat(run.started_at.replace("Z", "+00:00"))
                finished_at = run.finished_at or utc_now()
                finished = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
                elapsed = max(0.0, (finished - started).total_seconds())
            except Exception:
                elapsed = run.budget_usage.runtime_seconds_used
        run.budget_usage.runtime_seconds_used = round(elapsed, 3)

    async def _emit_budget_update(self, session_id: str, run: RunRecord) -> None:
        self._refresh_budget_usage(run)
        await self.emit(
            session_id,
            run.run_id,
            "budget_updated",
            {
                "budget": run.budget.model_dump(mode="json"),
                "usage": run.budget_usage.model_dump(mode="json"),
            },
        )

    async def _emit_task_graph(self, session_id: str, run: RunRecord) -> None:
        if not run.task_graph:
            return
        self.graphs.refresh(run.task_graph)
        await self.emit(session_id, run.run_id, "task_graph_updated", run.task_graph.model_dump(mode="json"))

    def _task_node(self, run: RunRecord, node_id: str | None) -> TaskNode | None:
        return self.graphs.get_node(run.task_graph, node_id)

    def _clarify_question(self, node: TaskNode) -> str:
        return (
            str(node.metadata.get("question") or "").strip()
            or (node.block_reason or "").strip()
            or (node.summary or "").strip()
            or node.description
        )

    def _select_runnable_nodes(self, run: RunRecord) -> list[TaskNode]:
        ready_nodes = self.graphs.ready_nodes(run.task_graph)
        if not ready_nodes:
            return []
        selected: list[TaskNode] = []
        tool_slots = max(0, run.budget.max_parallel_tools - run.budget_usage.active_tools)
        subagent_slots = max(0, run.budget.max_parallel_subagents - run.budget_usage.active_subagents)
        for node in ready_nodes:
            if self._node_is_exclusive(node):
                if selected:
                    break
                return [node]
            if node.kind == TaskNodeKind.SUBAGENT:
                if subagent_slots <= 0:
                    continue
                subagent_slots -= 1
                selected.append(node)
                continue
            if node.kind == TaskNodeKind.TOOL:
                if tool_slots <= 0:
                    continue
                tool_slots -= 1
                selected.append(node)
                continue
            selected.append(node)
        return selected

    def _node_is_exclusive(self, node: TaskNode) -> bool:
        if node.kind in {TaskNodeKind.SKILL, TaskNodeKind.EXPORT, TaskNodeKind.INPUT}:
            return True
        risk_tags = set(node.metadata.get("risk_tags", []))
        tool_name = node.metadata.get("tool_name")
        return tool_name == "shell_exec" or bool(risk_tags & {"filesystem_write", "network", "export_sensitive", "shell_exec"})

    async def _mark_node_running(self, run: RunRecord, session: SessionRecord, node: TaskNode) -> None:
        if node.kind == TaskNodeKind.AGGREGATE:
            run.status = RunStatus.AGGREGATING
        elif node.kind in {TaskNodeKind.REPORT, TaskNodeKind.EXPORT}:
            run.status = RunStatus.REPORTING
        else:
            run.status = RunStatus.RUNNING
        session.status = SessionStatus.ACTIVE_RUN
        node.status = TaskNodeStatus.RUNNING
        node.block_reason = None
        self.graphs.refresh(run.task_graph)
        self.storage.save_run(run)
        self.storage.save_session(session)
        await self.emit(session.session_id, run.run_id, "run_status", {"status": run.status.value})
        await self.emit(session.session_id, run.run_id, "task_node_started", {"node_id": node.node_id, "title": node.title})
        await self._emit_task_graph(session.session_id, run)
        await self._emit_budget_update(session.session_id, run)

    async def _complete_node(self, run: RunRecord, session: SessionRecord, node_id: str, *, summary: str | None = None) -> None:
        latest = self.storage.find_run(run.run_id)
        node = self._task_node(latest, node_id)
        if node is None:
            return
        node.status = TaskNodeStatus.COMPLETED
        if summary:
            node.summary = summary
        self.graphs.refresh(latest.task_graph)
        self.storage.save_run(latest)
        await self.emit(session.session_id, latest.run_id, "task_node_completed", {"node_id": node.node_id, "title": node.title, "summary": node.summary})
        await self._emit_task_graph(session.session_id, latest)

    async def _fail_run(
        self,
        run: RunRecord,
        session: SessionRecord,
        error: str,
        *,
        node_id: str | None = None,
        emit_message: bool = True,
    ) -> None:
        latest = self.storage.find_run(run.run_id)
        latest.status = RunStatus.FAILED
        latest.error_message = error
        latest.awaiting_reason = error
        latest.finished_at = utc_now()
        if latest.task_graph and node_id:
            node = self._task_node(latest, node_id)
            if node:
                node.status = TaskNodeStatus.FAILED
                node.block_reason = error
            self.graphs.refresh(latest.task_graph)
        self.storage.save_run(latest)
        session.active_run_id = None
        session.status = SessionStatus.IDLE
        session.pending_approval_ids = []
        session.pending_user_question = None
        self.storage.save_session(session)
        if node_id:
            await self.emit(session.session_id, latest.run_id, "task_node_blocked", {"node_id": node_id, "reason": error})
        await self._emit_task_graph(session.session_id, latest)
        await self.emit(session.session_id, latest.run_id, "failed", {"error": error, "node_id": node_id})
        if emit_message:
            await self._append_assistant_message(session.session_id, latest.run_id, f"run 执行失败：{error}")
        await self._emit_budget_update(session.session_id, latest)

    async def _finalize_run(self, run: RunRecord, session: SessionRecord) -> None:
        await self._commit_memory(run)
        latest = self.storage.find_run(run.run_id)
        latest.status = RunStatus.COMPLETED
        latest.awaiting_reason = None
        latest.finished_at = utc_now()
        self.storage.save_run(latest)
        session = self.storage.load_session(session.session_id)
        session.active_run_id = None
        session.pending_approval_ids = []
        session.pending_user_question = None
        session.status = SessionStatus.IDLE
        session.last_intent_type = UserTurnDisposition.CONTINUE_RUN.value
        if latest.report_id:
            session.latest_report_id = latest.report_id
            session.last_report_id = latest.report_id
        self.storage.save_session(session)
        await self._emit_task_graph(session.session_id, latest)
        await self.emit(
            session.session_id,
            latest.run_id,
            "completed",
            {"run_id": latest.run_id, "report_id": latest.report_id, "final_response": latest.final_response},
        )
        if latest.final_response:
            await self._append_assistant_message(session.session_id, latest.run_id, latest.final_response)
        await self._emit_budget_update(session.session_id, latest)

    async def _attempt_graph_replan(self, run: RunRecord, session: SessionRecord) -> bool:
        if run.task_graph is None or run.graph_edit_rounds >= 3:
            return False
        planner = self._planner_profile()
        ops = await self.agent.propose_graph_edits(
            profile_name=planner.name,
            task=run.user_task,
            graph=run.task_graph.model_dump(mode="json"),
            evidence_summaries=[
                self.storage.load_evidence(evidence_id).summary
                for evidence_id in run.evidence_ids[-5:]
            ],
        )
        if not ops:
            return False
        self.graphs.apply_ops(run.task_graph, ops)
        run.graph_edit_rounds += 1
        self.storage.save_run(run)
        for op in ops:
            await self.emit(session.session_id, run.run_id, "graph_op_applied", op.model_dump(mode="json"))
        await self._append_assistant_message(
            session.session_id,
            run.run_id,
            await self.agent.summarize_graph_update(
                profile_name=planner.name,
                task=run.user_task,
                ops=ops,
                graph=run.task_graph,
            ),
        )
        await self._emit_task_graph(session.session_id, run)
        return True

    def _attach_node_outputs(
        self,
        run: RunRecord,
        node: TaskNode,
        *,
        artifact_ids: list[str] | None = None,
        evidence_ids: list[str] | None = None,
        summary: str | None = None,
    ) -> None:
        artifact_ids = artifact_ids or []
        evidence_ids = evidence_ids or []
        for artifact_id in artifact_ids:
            if artifact_id not in run.artifact_ids:
                run.artifact_ids.append(artifact_id)
            if artifact_id not in node.artifact_refs:
                node.artifact_refs.append(artifact_id)
        for evidence_id in evidence_ids:
            if evidence_id not in run.evidence_ids:
                run.evidence_ids.append(evidence_id)
            if evidence_id not in node.evidence_refs:
                node.evidence_refs.append(evidence_id)
        if summary:
            node.summary = summary

    def _next_action_titles(self, run: RunRecord, node_id: str) -> list[str]:
        node = self._task_node(run, node_id)
        if node is None or not run.task_graph:
            return []
        titles: list[str] = []
        for child_id in node.children:
            child = self._task_node(run, child_id)
            if child:
                titles.append(child.title)
        return titles[:3]

    def _topological_order(self, graph: TaskGraph) -> list[str]:
        indegree = {node.node_id: 0 for node in graph.nodes}
        children: dict[str, list[str]] = {node.node_id: [] for node in graph.nodes}
        for edge in graph.edges:
            if edge.source in indegree and edge.target in indegree:
                indegree[edge.target] += 1
                children[edge.source].append(edge.target)
        queue = [node.node_id for node in graph.nodes if indegree[node.node_id] == 0]
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for child in children.get(current, []):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        return order


RunManager = SessionManager
