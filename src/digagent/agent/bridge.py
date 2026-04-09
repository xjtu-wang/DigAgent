from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from langchain_openai import ChatOpenAI

from digagent.config import AppSettings, get_settings, load_profiles
from digagent.models import (
    DailyMemoryNote,
    ExecutionBatchDecision,
    Finding,
    GraphEditOp,
    IntentProfile,
    MessageRoute,
    MessageRoutingDecision,
    PlanningBundle,
    ReportDossier,
    ReportDraft,
    Scope,
    TaskEdge,
    TaskGraph,
    TaskNode,
    TaskNodeKind,
    TaskNodeStatus,
    WikiClaim,
    WikiEntry,
)
from digagent.utils import new_id, utc_now


class AgentBridge:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.profiles = load_profiles(self.settings)

    def _profile(self, profile_name: str) -> Any:
        if profile_name not in self.profiles:
            available = ", ".join(sorted(self.profiles))
            raise KeyError(f"Unknown agent profile '{profile_name}'. Available: {available}")
        return self.profiles[profile_name]

    def _is_test_mode(self) -> bool:
        return self.settings.digagent_use_fake_model

    def _chat_model(self, *, profile_name: str | None = None) -> ChatOpenAI:
        profile = self._profile(profile_name) if profile_name else None
        if not self.settings.can_use_model:
            raise RuntimeError("Model configuration is unavailable")
        return ChatOpenAI(
            model=(profile.model if profile and profile.model else self.settings.model),
            api_key=self.settings.openai_api_key,
            base_url=self.settings.base_url,
            temperature=0.1,
        )

    async def run_text_task(
        self,
        *,
        task: str,
        profile_name: str | None = None,
        system_prompt: str | None = None,
    ) -> str:
        resolved_prompt = system_prompt or self._profile(profile_name or "sisyphus-default").system_prompt
        if self._is_test_mode():
            return self._test_response(task)
        model = self._chat_model(profile_name=profile_name)
        result = await model.ainvoke(
            [
                ("system", resolved_prompt),
                ("user", task),
            ]
        )
        return getattr(result, "content", str(result))

    def _extract_output(self, result: Any) -> str:
        if isinstance(result, dict):
            messages = result.get("messages") or []
            if messages:
                content = getattr(messages[-1], "content", messages[-1])
                if isinstance(content, list):
                    return "\n".join(
                        block.get("text", "") if isinstance(block, dict) else str(block)
                        for block in content
                    ).strip()
                return str(content).strip()
        return str(result).strip()

    async def plan_task_graph(
        self,
        *,
        run_id: str,
        profile_name: str,
        task: str,
        scope: dict[str, Any] | Scope | None = None,
        followup_messages: list[str] | None = None,
        tool_allowlist: list[str] | None = None,
    ) -> PlanningBundle:
        normalized_scope = scope if isinstance(scope, Scope) else Scope.model_validate(scope or {})
        if self._is_test_mode():
            return self.build_test_planning_bundle(
                run_id=run_id,
                task=task,
                scope=normalized_scope,
                followup_messages=followup_messages,
            )
        if not self.settings.can_use_model:
            raise RuntimeError("planner model configuration is unavailable")

        prompt = (
            "Return only JSON.\n"
            "Produce a planning bundle for a controlled agent runtime.\n"
            "Top-level keys: intent_profile, planner_message, clarify_message, task_graph.\n"
            "intent_profile must contain objective, labels, report_kind_hint, confidence.\n"
            "task_graph must contain run_id, nodes, and edges.\n"
            "Each node must include node_id, title, kind, status, description, summary, metadata.\n"
            "Valid kinds: input, tool, skill, subagent, aggregate, report, export.\n"
            "Every subagent node must include owner_profile_name.\n"
            "If clarification is required, create an input node in waiting_user_input and set metadata.question.\n"
            "If execution can proceed, keep the graph minimal and auditable. End with aggregate -> report -> export.\n"
            "Use prometheus-planner as planner only. Choose specialist owners explicitly on each subagent node.\n"
            "Use tool manifests and skill bundles already available to the runtime. Avoid inventing unavailable tools.\n"
            "planner_message must be natural Chinese and tell the user what you understood and what happens next.\n"
            "clarify_message should be null unless the graph waits for user input.\n\n"
            f"run_id: {run_id}\n"
            f"scope: {json.dumps(normalized_scope.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"followups: {json.dumps(followup_messages or [], ensure_ascii=False)}\n"
            f"allowed_tools: {json.dumps(tool_allowlist or [], ensure_ascii=False)}\n"
            f"task: {task}"
        )
        try:
            text = await self.run_text_task(profile_name=profile_name, task=prompt)
            payload = json.loads(text)
            if isinstance(payload, dict):
                payload.setdefault("task_graph", {})
                payload["task_graph"].setdefault("run_id", run_id)
            bundle = PlanningBundle.model_validate(payload)
            if not bundle.task_graph.nodes:
                raise ValueError("planner returned empty graph")
            waiting = [node for node in bundle.task_graph.nodes if node.status == TaskNodeStatus.WAITING_USER_INPUT]
            if waiting and not bundle.clarify_message:
                bundle.clarify_message = self._clarify_question(waiting[0])
            return bundle
        except Exception as exc:
            raise RuntimeError(f"planner failed: {exc}") from exc

    async def classify_message(
        self,
        *,
        profile_name: str,
        user_message: str,
        session_status: str,
        run_status: str | None,
        graph: dict[str, Any] | None,
        pending_question: str | None,
        pending_approvals: int,
    ) -> MessageRoutingDecision:
        if self._is_test_mode():
            return self._classify_message_for_tests(
                user_message=user_message,
                session_status=session_status,
                run_status=run_status,
                pending_question=pending_question,
                pending_approvals=pending_approvals,
            )
        if not self.settings.can_use_model:
            raise RuntimeError("message router model configuration is unavailable")
        prompt = (
            "Return only JSON.\n"
            "Classify the latest user message for a session-driven agent.\n"
            "Allowed route values: direct_answer, clarification_input, approval_response, cancel, new_run_request.\n"
            "Use clarification_input only when the message clearly answers the pending clarification question.\n"
            "Use direct_answer for conceptual Q&A, progress/status questions, or explanatory follow-up that should not mutate the task graph.\n"
            "Use new_run_request only when the user is asking to start or switch to a different executable task.\n"
            "Top-level keys: route, rationale.\n\n"
            f"user_message: {user_message}\n"
            f"session_status: {session_status}\n"
            f"run_status: {run_status}\n"
            f"pending_question: {pending_question}\n"
            f"pending_approvals: {pending_approvals}\n"
            f"graph: {json.dumps(graph or {}, ensure_ascii=False)}"
        )
        try:
            text = await self.run_text_task(profile_name=profile_name, task=prompt)
            return MessageRoutingDecision.model_validate(json.loads(text))
        except Exception as exc:
            raise RuntimeError(f"message router failed: {exc}") from exc

    async def select_execution_batch(
        self,
        *,
        profile_name: str,
        task: str,
        intent_profile: IntentProfile | None,
        ready_nodes: list[TaskNode],
        graph: TaskGraph,
        evidence_summaries: list[str],
        max_parallel_tools: int,
        max_parallel_subagents: int,
    ) -> ExecutionBatchDecision:
        if not ready_nodes:
            return ExecutionBatchDecision(node_ids=[], planner_message="当前没有可执行节点。")
        if self._is_test_mode():
            node_ids = self._test_batch_selection(ready_nodes, max_parallel_tools=max_parallel_tools, max_parallel_subagents=max_parallel_subagents)
            names = [node.title for node in ready_nodes if node.node_id in node_ids]
            return ExecutionBatchDecision(
                node_ids=node_ids,
                planner_message=f"我先推进这些节点：{'；'.join(names)}。",
                rationale="offline_selection",
            )
        if not self.settings.can_use_model:
            raise RuntimeError("scheduler model configuration is unavailable")

        prompt = (
            "Return only JSON.\n"
            "You are the root scheduler for a task DAG.\n"
            "Choose which ready nodes to execute now.\n"
            "Output keys: node_ids, planner_message, rationale.\n"
            "Only choose from the provided ready nodes. Respect limited parallelism.\n"
            "Prefer making progress while avoiding unnecessary blocking.\n\n"
            f"task: {task}\n"
            f"intent_profile: {json.dumps(intent_profile.model_dump(mode='json') if intent_profile else {}, ensure_ascii=False)}\n"
            f"max_parallel_tools: {max_parallel_tools}\n"
            f"max_parallel_subagents: {max_parallel_subagents}\n"
            f"ready_nodes: {json.dumps([node.model_dump(mode='json') for node in ready_nodes], ensure_ascii=False)}\n"
            f"recent_evidence: {json.dumps(evidence_summaries, ensure_ascii=False)}\n"
            f"graph_snapshot: {json.dumps(graph.model_dump(mode='json'), ensure_ascii=False)}"
        )
        try:
            text = await self.run_text_task(profile_name=profile_name, task=prompt)
            decision = ExecutionBatchDecision.model_validate(json.loads(text))
            allowed = {node.node_id for node in ready_nodes}
            decision.node_ids = [node_id for node_id in decision.node_ids if node_id in allowed]
            if decision.node_ids:
                return decision
            raise RuntimeError("scheduler returned an empty execution batch")
        except Exception as exc:
            raise RuntimeError(f"scheduler failed: {exc}") from exc

    async def propose_graph_edits(
        self,
        *,
        profile_name: str,
        task: str,
        graph: dict[str, Any],
        evidence_summaries: list[str],
    ) -> list[GraphEditOp]:
        if self._is_test_mode():
            return []
        if not self.settings.can_use_model:
            return []
        prompt = (
            "Return only JSON.\n"
            "You are repairing a task DAG.\n"
            "Return a JSON array of graph edit operations.\n"
            "Supported op_type values: ADD_NODE, UPDATE_NODE, ADD_EDGE, REMOVE_EDGE, DEPRECATE_NODE.\n"
            "Prefer local repair over rebuilding the whole graph.\n\n"
            f"Task:\n{task}\n\n"
            f"Graph:\n{json.dumps(graph, ensure_ascii=False)}\n\n"
            f"Evidence:\n{json.dumps(evidence_summaries, ensure_ascii=False)}"
        )
        try:
            text = await self.run_text_task(profile_name=profile_name, task=prompt)
            payload = json.loads(text)
            if not isinstance(payload, list):
                return []
            return [GraphEditOp.model_validate(item) for item in payload]
        except Exception as exc:
            raise RuntimeError(f"graph replan failed: {exc}") from exc

    async def summarize_graph_update(
        self,
        *,
        profile_name: str,
        task: str,
        ops: list[GraphEditOp],
        graph: TaskGraph,
    ) -> str:
        if not ops:
            return "我调整了任务图，接下来会按新的路径继续推进。"
        if self._is_test_mode():
            changed = "；".join(
                op.node_id or (op.node or {}).get("title") or (op.edge.source if op.edge else op.op_type.value)
                for op in ops[:3]
            )
            return f"我根据新的线索调整了任务图，重点变化是：{changed}。接下来继续执行新的可运行节点。"
        if not self.settings.can_use_model:
            raise RuntimeError("planner summary model configuration is unavailable")
        prompt = (
            "用简短自然的中文说明这次任务图更新给用户听。不要列 JSON，不要超过 3 句。\n\n"
            f"task: {task}\n"
            f"ops: {json.dumps([op.model_dump(mode='json') for op in ops], ensure_ascii=False)}\n"
            f"graph: {json.dumps(graph.model_dump(mode='json'), ensure_ascii=False)}"
        )
        text = (await self.run_text_task(profile_name=profile_name, task=prompt)).strip()
        return text or "我调整了任务图，接下来会按新的路径继续推进。"

    async def generate_clarify_question(
        self,
        *,
        profile_name: str,
        task: str,
        scope: dict[str, Any] | Scope | None = None,
    ) -> str:
        normalized_scope = scope if isinstance(scope, Scope) else Scope.model_validate(scope or {})
        fallback = self._friendly_clarify_question(task, scope=normalized_scope)
        if self._is_test_mode():
            return fallback
        if not self.settings.can_use_model:
            raise RuntimeError("clarify model configuration is unavailable")
        prompt = (
            "写一句简短自然的中文追问，只索取继续执行这个任务所缺的最小范围信息。"
            "不要拒绝用户，不要分点，不要模板腔。\n\n"
            f"scope: {json.dumps(normalized_scope.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"task: {task}"
        )
        try:
            text = (await self.run_text_task(profile_name=profile_name, task=prompt)).strip()
            return text or fallback
        except Exception as exc:
            raise RuntimeError(f"clarify generation failed: {exc}") from exc

    async def curate_memory(
        self,
        *,
        profile_name: str,
        task: str,
        intent_profile: IntentProfile | None,
        report: ReportDraft,
        evidence: list[dict[str, Any]],
        session_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        if self._is_test_mode():
            return self._test_memory_curation(
                task=task,
                intent_profile=intent_profile,
                report=report,
                evidence=evidence,
                session_id=session_id,
                run_id=run_id,
            )
        if not self.settings.can_use_model:
            raise RuntimeError("memory curator model configuration is unavailable")
        prompt = (
            "Return only JSON.\n"
            "Curate layered memory for an agent system.\n"
            "Top-level keys: daily_note, memory_candidates, wiki_entries.\n"
            "daily_note must contain heading and body.\n"
            "memory_candidates must only contain durable cross-run knowledge backed by evidence.\n"
            "wiki_entries must summarize reusable claims with evidence_refs.\n"
            "Do not dump raw run metadata into long-term memory.\n\n"
            f"task: {task}\n"
            f"intent_profile: {json.dumps(intent_profile.model_dump(mode='json') if intent_profile else {}, ensure_ascii=False)}\n"
            f"report: {json.dumps(report.model_dump(mode='json'), ensure_ascii=False)}\n"
            f"evidence: {json.dumps(evidence, ensure_ascii=False)}"
        )
        try:
            text = await self.run_text_task(profile_name=profile_name, task=prompt)
            payload = json.loads(text)
            payload.setdefault("daily_note", {})
            payload["daily_note"].setdefault("source_session_id", session_id)
            payload["daily_note"].setdefault("source_run_id", run_id)
            payload["daily_note"].setdefault("created_at", utc_now())
            payload["daily_note"] = DailyMemoryNote.model_validate(payload["daily_note"]).model_dump(mode="json")
            payload["memory_candidates"] = payload.get("memory_candidates", [])
            payload["wiki_entries"] = payload.get("wiki_entries", [])
            return payload
        except Exception as exc:
            raise RuntimeError(f"memory curation failed: {exc}") from exc

    async def write_report(self, *, profile_name: str, dossier: ReportDossier) -> ReportDraft:
        if self._is_test_mode():
            return self._test_report(dossier)
        if not self.settings.can_use_model:
            raise RuntimeError("report writer model configuration is unavailable")
        prompt = (
            "Return only JSON.\n"
            "You are a dedicated report writer.\n"
            "Write an evidence-backed report draft.\n"
            "Top-level keys: kind, title, summary, findings, limitations, writer_summary, evidence_refs.\n"
            "Every finding must have evidence_refs.\n"
            "Use only evidence-supported claims. If evidence is weak, say so in limitations.\n\n"
            f"dossier: {json.dumps(dossier.model_dump(mode='json'), ensure_ascii=False)}"
        )
        try:
            text = await self.run_text_task(profile_name=profile_name, task=prompt)
            draft = ReportDraft.model_validate(json.loads(text))
            return draft
        except Exception as exc:
            raise RuntimeError(f"report writer failed: {exc}") from exc

    async def compose_direct_answer(
        self,
        *,
        profile_name: str,
        user_question: str,
        session_status: str,
        run_status: str | None,
        graph: dict[str, Any] | None,
        evidence_summaries: list[str],
        memory_context: dict[str, Any],
        pending_approvals: int,
        awaiting_reason: str | None,
        budget: dict[str, Any] | None = None,
    ) -> str:
        if self._is_test_mode():
            return self._test_direct_answer(
                user_question=user_question,
                session_status=session_status,
                run_status=run_status,
                graph=graph or {},
                evidence_summaries=evidence_summaries,
                memory_context=memory_context,
                pending_approvals=pending_approvals,
                awaiting_reason=awaiting_reason,
                budget=budget or {},
            )
        if not self.settings.can_use_model:
            raise RuntimeError("direct answer model configuration is unavailable")
        prompt = (
            "用自然中文回答用户消息。"
            "如果用户在问当前任务状态、证据、审批或下一步，只基于当前图状态、最近证据、待审批信息和记忆摘要回答。"
            "如果用户是在问概念解释或术语说明，而且不需要触发新执行，可以直接做简洁答疑。"
            "不要暴露内部实现细节，不要编造。\n\n"
            f"user_question: {user_question}\n"
            f"session_status: {session_status}\n"
            f"run_status: {run_status}\n"
            f"graph: {json.dumps(graph or {}, ensure_ascii=False)}\n"
            f"evidence: {json.dumps(evidence_summaries, ensure_ascii=False)}\n"
            f"memory: {json.dumps(memory_context, ensure_ascii=False)}\n"
            f"pending_approvals: {pending_approvals}\n"
            f"awaiting_reason: {awaiting_reason}\n"
            f"budget: {json.dumps(budget or {}, ensure_ascii=False)}"
        )
        text = (await self.run_text_task(profile_name=profile_name, task=prompt)).strip()
        if not text:
            raise RuntimeError("direct answer model returned empty content")
        return text

    def _classify_message_for_tests(
        self,
        *,
        user_message: str,
        session_status: str,
        run_status: str | None,
        pending_question: str | None,
        pending_approvals: int,
    ) -> MessageRoutingDecision:
        lower = user_message.lower()
        if any(marker in lower for marker in {"取消", "停止", "终止", "cancel", "stop"}):
            return MessageRoutingDecision(route=MessageRoute.CANCEL, rationale="cancel_request")
        if pending_approvals and any(marker in lower for marker in {"批准", "同意", "approve", "yes", "继续", "通过", "拒绝", "不同意", "reject", "no"}):
            return MessageRoutingDecision(route=MessageRoute.APPROVAL_RESPONSE, rationale="approval_reply")
        explain_markers = {"解释", "介绍", "说明", "什么是", "what is", "why", "为什么"}
        status_markers = {"进度", "状态", "证据", "发现", "下一步", "审批", "summary", "status", "evidence", "approval"}
        if any(marker in lower for marker in explain_markers | status_markers) or user_message.strip().endswith(("?", "？")):
            return MessageRoutingDecision(route=MessageRoute.DIRECT_ANSWER, rationale="qa_message")
        if run_status == "awaiting_user_input" or session_status == "awaiting_user_input" or pending_question:
            return MessageRoutingDecision(route=MessageRoute.CLARIFICATION_INPUT, rationale="clarification_reply")
        return MessageRoutingDecision(route=MessageRoute.NEW_RUN_REQUEST, rationale="new_task")

    def build_test_planning_bundle(
        self,
        *,
        run_id: str,
        task: str,
        scope: Scope,
        followup_messages: list[str] | None = None,
    ) -> PlanningBundle:
        intent = self._test_intent_profile(task, scope)
        graph = self.build_test_task_graph(
            run_id=run_id,
            task=task,
            scope=scope,
            followup_messages=followup_messages,
            intent_profile=intent,
        )
        waiting = [node for node in graph.nodes if node.status == TaskNodeStatus.WAITING_USER_INPUT]
        clarify = self._clarify_question(waiting[0]) if waiting else None
        planner_message = self._test_planner_message(intent, graph, clarify_message=clarify)
        return PlanningBundle(
            intent_profile=intent,
            task_graph=graph,
            planner_message=planner_message,
            clarify_message=clarify,
        )

    def build_test_task_graph(
        self,
        *,
        run_id: str,
        task: str,
        scope: Scope,
        followup_messages: list[str] | None = None,
        intent_profile: IntentProfile | None = None,
    ) -> TaskGraph:
        intent = intent_profile or self._test_intent_profile(task, scope)
        if self._test_needs_clarification(task, scope, intent):
            prompt = self._friendly_clarify_question(task, scope=scope)
            return TaskGraph(
                run_id=run_id,
                nodes=[
                    TaskNode(
                        node_id=new_id("node"),
                        title="Clarify objective",
                        kind=TaskNodeKind.INPUT,
                        status=TaskNodeStatus.WAITING_USER_INPUT,
                        description=prompt,
                        summary="等待用户补充关键信息",
                        block_reason=prompt,
                        metadata={"question": prompt},
                        max_retries=0,
                    )
                ],
                edges=[],
            )

        nodes: list[TaskNode] = []
        edges: list[TaskEdge] = []

        def add_node(
            *,
            title: str,
            description: str,
            kind: TaskNodeKind,
            metadata: dict[str, Any] | None = None,
            max_retries: int = 1,
        ) -> TaskNode:
            node = TaskNode(
                node_id=new_id("node"),
                title=title,
                kind=kind,
                description=description,
                summary=description,
                metadata=metadata or {},
                max_retries=max_retries,
            )
            nodes.append(node)
            return node

        def connect(source: TaskNode, target: TaskNode) -> None:
            edges.append(TaskEdge(source=source.node_id, target=target.node_id))

        upstream: list[TaskNode] = []
        labels = set(intent.labels)
        if "ctf" in labels:
            orchestrator = add_node(
                title="Load CTF orchestrator skill",
                description="Load the vendored CTF orchestrator skill and inspect the challenge context.",
                kind=TaskNodeKind.SKILL,
                metadata={"skill_name": "ctf-sandbox-orchestrator"},
            )
            upstream_node = orchestrator
            specialist_name = self._test_ctf_specialist_skill(task)
            if specialist_name:
                specialist = add_node(
                    title="Load routed specialist skill",
                    description=f"Load downstream specialist skill {specialist_name} for the dominant challenge path.",
                    kind=TaskNodeKind.SKILL,
                    metadata={"skill_name": specialist_name},
                )
                connect(orchestrator, specialist)
                upstream_node = specialist
            solve = add_node(
                title="Analyze challenge evidence",
                description="Use the loaded skills, challenge text, and current evidence to derive the most plausible result.",
                kind=TaskNodeKind.SUBAGENT,
                metadata={"task_mode": "ctf_solve"},
            )
            solve.owner_profile_name = "hackey-ctf"
            connect(upstream_node, solve)
            upstream.append(solve)
        elif "web_analysis" in labels:
            domain = scope.allowed_domains[0] if scope.allowed_domains else self._test_guess_domain(task)
            url = self._test_resolve_web_url(task, domain or "")
            fetch = add_node(
                title="Fetch target page",
                description="Fetch the approved target page and turn the response into evidence.",
                kind=TaskNodeKind.TOOL,
                metadata={
                    "tool_name": "web_fetch",
                    "arguments": {"url": url, "method": "GET"},
                    "targets": {"domains": [domain]} if domain else {},
                },
            )
            analyze = add_node(
                title="Interpret collected web evidence",
                description="Inspect the fetched evidence and summarize the most relevant observations.",
                kind=TaskNodeKind.SUBAGENT,
            )
            analyze.owner_profile_name = "hephaestus-deepworker"
            connect(fetch, analyze)
            upstream.append(analyze)
        else:
            repo_paths = scope.repo_paths or [str(self.settings.workspace_root)]
            search = add_node(
                title="Collect repository evidence",
                description="Search the allowed repository scope and collect code or configuration evidence.",
                kind=TaskNodeKind.TOOL,
                metadata={
                    "tool_name": "repo_search",
                    "arguments": {"repo_paths": repo_paths, "query": ""},
                    "targets": {"paths": repo_paths},
                },
            )
            analyze = add_node(
                title="Interpret repository evidence",
                description="Summarize the codebase structure, notable modules, and likely focus areas.",
                kind=TaskNodeKind.SUBAGENT,
            )
            analyze.owner_profile_name = "hephaestus-deepworker"
            connect(search, analyze)
            upstream.append(analyze)

        kb_arguments = self._test_knowledge_lookup_arguments(task)
        if kb_arguments:
            kb = add_node(
                title="Query vulnerability knowledge base",
                description="Look up local vulnerability knowledge that may contextualize the task.",
                kind=TaskNodeKind.TOOL,
                metadata={"tool_name": "vuln_kb_lookup", "arguments": kb_arguments},
            )
            upstream.append(kb)

        aggregate = add_node(
            title="Aggregate evidence",
            description="Aggregate completed evidence and align it with the user goal.",
            kind=TaskNodeKind.AGGREGATE,
            metadata={"followups": followup_messages or []},
        )
        report = add_node(
            title="Write report",
            description="Use a dedicated writer to produce an evidence-backed report draft.",
            kind=TaskNodeKind.REPORT,
        )
        export = add_node(
            title="Export PDF",
            description="Export the report for delivery.",
            kind=TaskNodeKind.EXPORT,
            metadata={"format": "pdf"},
        )
        for parent in upstream:
            connect(parent, aggregate)
        connect(aggregate, report)
        connect(report, export)
        return TaskGraph(run_id=run_id, nodes=nodes, edges=edges)

    def _test_planner_message(self, intent: IntentProfile, graph: TaskGraph, *, clarify_message: str | None) -> str:
        if clarify_message:
            return f"我先确认一下目标边界。{clarify_message}"
        node_titles = "；".join(node.title for node in graph.nodes[:4])
        return f"我理解这次目标是：{intent.objective}。我先按这条路径推进：{node_titles}。"

    def _test_intent_profile(self, task: str, scope: Scope) -> IntentProfile:
        lower = task.lower()
        labels: list[str] = []
        report_kind_hint = "analysis_note"
        objective = task.strip()[:120] or "继续当前任务"
        if scope.allowed_domains or "http://" in lower or "https://" in lower or "www." in lower:
            labels.append("web_analysis")
            report_kind_hint = "pentest_report"
        if scope.repo_paths or any(token in task for token in ["源码", "代码", "仓库", "项目", "repo"]):
            labels.append("code_review")
            report_kind_hint = "code_review_report"
        if any(token in lower for token in ["ctf", "crypto", "rail", "rot13", "morse", "cipher", "decode", "flag"]) or any(
            token in task for token in ["栅栏", "题目", "密文", "解密", "摩斯", "附件"]
        ):
            labels = [label for label in labels if label != "code_review"]
            if "ctf" not in labels:
                labels.insert(0, "ctf")
            report_kind_hint = "writeup"
        if not labels:
            labels = ["general"]
        return IntentProfile(
            objective=objective,
            labels=labels,
            report_kind_hint=report_kind_hint,
            confidence=0.74,
        )

    def _test_needs_clarification(self, task: str, scope: Scope, intent: IntentProfile) -> bool:
        labels = set(intent.labels)
        if labels == {"general"} and not scope.allowed_domains and not scope.repo_paths and not scope.artifacts:
            return True
        if "web_analysis" in labels and not scope.allowed_domains and not self._test_guess_domain(task):
            return True
        if "code_review" in labels and not scope.repo_paths:
            return False
        return False

    def _friendly_clarify_question(self, task: str, *, scope: Scope) -> str:
        if scope.repo_paths or any(token in task for token in ["源码", "代码", "仓库", "项目", "repo"]):
            return "我可以继续做源码分析。告诉我想聚焦的目录、模块或风险主题，我就继续细化任务图。"
        if scope.allowed_domains or re.search(r"https?://|\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b", task):
            return "我可以继续做这个 Web 分析。把目标域名或完整 URL 确认一下，如果有访问约束也一起告诉我。"
        if scope.artifacts or any(token in task.lower() for token in ["ctf", "flag", "decode", "cipher"]) or any(
            token in task for token in ["栅栏", "题目", "密文", "解密", "附件"]
        ):
            return "我可以继续拆这道题。把题目原文、密文或附件路径贴给我，我就继续规划求解步骤。"
        return "我先确认一下你的目标：这次是要分析仓库、网站，还是一道题目？你可以直接补充仓库路径、目标域名或题面附件。"

    def _clarify_question(self, node: TaskNode) -> str:
        return (
            str(node.metadata.get("question") or "").strip()
            or (node.block_reason or "").strip()
            or (node.summary or "").strip()
            or node.description
        )

    def _test_guess_domain(self, task: str) -> str | None:
        match = re.search(r"https?://([^\s/]+)", task)
        if match:
            return match.group(1)
        domain_match = re.search(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b", task)
        if domain_match:
            return domain_match.group(0)
        return None

    def _test_resolve_web_url(self, task: str, domain: str) -> str:
        match = re.search(r"https?://[^\s]+", task)
        if match:
            return match.group(0)
        if domain.startswith("127.0.0.1") or domain.startswith("localhost"):
            return f"http://{domain}"
        if domain:
            return f"https://{domain}"
        return "https://example.invalid"

    def _test_knowledge_lookup_arguments(self, task: str) -> dict[str, Any] | None:
        cve_match = re.search(r"\bCVE-\d{4}-\d+\b", task, re.IGNORECASE)
        if cve_match:
            return {"cve_id": cve_match.group(0).upper(), "limit": 5}
        cwe_match = re.search(r"\bCWE-\d+\b", task, re.IGNORECASE)
        if cwe_match:
            return {"cwe": cwe_match.group(0).upper(), "limit": 5}
        if "漏洞知识库" in task or "cve" in task.lower():
            return {"query": task[:160], "limit": 5}
        return None

    def _test_ctf_specialist_skill(self, task: str) -> str | None:
        lower = task.lower()
        tokens = ["crypto", "rail", "stego", "mobile", "decode", "cipher", "base64", "rot", "xor", "morse"]
        if any(token in lower for token in tokens) or any(token in task for token in ["栅栏", "密文", "编码", "解码", "图片", "音频", "安卓", "苹果", "摩斯"]):
            return "competition-crypto-mobile"
        return None

    def _test_batch_selection(
        self,
        ready_nodes: list[TaskNode],
        *,
        max_parallel_tools: int,
        max_parallel_subagents: int,
    ) -> list[str]:
        selected: list[str] = []
        tool_slots = max_parallel_tools
        subagent_slots = max_parallel_subagents
        for node in ready_nodes:
            if self._node_is_exclusive(node):
                if selected:
                    break
                return [node.node_id]
            if node.kind == TaskNodeKind.TOOL:
                if tool_slots <= 0:
                    continue
                tool_slots -= 1
            elif node.kind == TaskNodeKind.SUBAGENT:
                if subagent_slots <= 0:
                    continue
                subagent_slots -= 1
            selected.append(node.node_id)
        return selected[: max(1, max_parallel_tools + max_parallel_subagents)]

    def _node_is_exclusive(self, node: TaskNode) -> bool:
        if node.kind in {TaskNodeKind.SKILL, TaskNodeKind.EXPORT, TaskNodeKind.INPUT, TaskNodeKind.REPORT}:
            return True
        risk_tags = set(node.metadata.get("risk_tags", []))
        tool_name = node.metadata.get("tool_name")
        return tool_name == "shell_exec" or bool(risk_tags & {"filesystem_write", "network", "export_sensitive", "shell_exec"})

    def _test_memory_curation(
        self,
        *,
        task: str,
        intent_profile: IntentProfile | None,
        report: ReportDraft,
        evidence: list[dict[str, Any]],
        session_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        primary_refs = [item["evidence_id"] for item in evidence[:3] if item.get("evidence_id")]
        daily_note = DailyMemoryNote(
            heading=f"Run {run_id}",
            body=f"目标：{intent_profile.objective if intent_profile else task}\n结论：{report.summary}",
            source_session_id=session_id,
            source_run_id=run_id,
            evidence_refs=primary_refs,
            created_at=utc_now(),
        )
        memory_candidates: list[dict[str, Any]] = []
        if any("markdown" in (task or "").lower() for task in [task, report.summary]):
            memory_candidates.append(
                {
                    "kind": "operator_preference",
                    "summary": "用户倾向可读性较高的 Markdown 风格输出",
                    "content": {"preference": "markdown_friendly"},
                    "source_evidence_ids": primary_refs,
                    "confidence": 0.72,
                    "sensitivity": "low",
                }
            )
        wiki_entries: list[dict[str, Any]] = []
        if report.findings:
            claims = [
                WikiClaim(
                    claim=finding.claim,
                    evidence_refs=finding.evidence_refs,
                    confidence=finding.confidence,
                )
                for finding in report.findings[:3]
            ]
            wiki_entries.append(
                WikiEntry(
                    entry_id=new_id("wiki"),
                    title=report.title,
                    summary=report.summary,
                    source_session_id=session_id,
                    source_run_id=run_id,
                    claims=claims,
                    tags=(intent_profile.labels if intent_profile else [])[:4],
                    created_at=utc_now(),
                    updated_at=utc_now(),
                ).model_dump(mode="json")
            )
        return {
            "daily_note": daily_note.model_dump(mode="json"),
            "memory_candidates": memory_candidates,
            "wiki_entries": wiki_entries,
        }

    def _test_report(self, dossier: ReportDossier) -> ReportDraft:
        evidence = dossier.evidence
        evidence_ids = [item["evidence_id"] for item in evidence if item.get("evidence_id")]
        labels = set((dossier.intent_profile.labels if dossier.intent_profile else []) or [])
        kind = dossier.intent_profile.report_kind_hint if dossier.intent_profile and dossier.intent_profile.report_kind_hint else "analysis_note"
        findings: list[Finding] = []
        limitations: list[str] = []

        flag = self._best_flag_from_evidence(evidence)
        status_code = self._first_fact_value(evidence, "status_code")
        title = self._first_fact_value(evidence, "title")
        repo_hit = next((item for item in evidence if item.get("source", {}).get("tool_name") == "repo_search"), None)

        if "ctf" in labels or flag:
            kind = "writeup"
            if flag:
                findings.append(
                    Finding(
                        finding_id=new_id("fd"),
                        title="得到当前最可信答案",
                        severity="info",
                        confidence=0.95,
                        claim=f"结合 skill、分析过程和现有证据，当前最可信的最终答案为 {flag}。",
                        evidence_refs=self._best_flag_refs(evidence, flag) or evidence_ids[:3],
                        reproduction_steps=["加载相关技能与题面线索", "汇总转换链证据", "复核最终候选值"],
                        remediation="保留完整转换链和关键证据，便于复核最终答案。",
                    )
                )
                summary = f"题目已完成求解，当前最可信的最终答案为 {flag}。"
            else:
                summary = "题目已形成阶段性分析结果，但最终答案仍需更多证据确认。"
                limitations.append("现有证据不足以支持高置信度最终答案。")
        elif "web_analysis" in labels or status_code is not None:
            kind = "pentest_report"
            claim = f"目标站点当前返回状态 {status_code}，页面标题为 {title or '未知'}。" if status_code is not None else "已完成站点公开信息观察。"
            findings.append(
                Finding(
                    finding_id=new_id("fd"),
                    title="完成公开面取证",
                    severity="info",
                    confidence=0.86 if status_code is not None else 0.72,
                    claim=claim,
                    evidence_refs=evidence_ids[:3],
                    reproduction_steps=["抓取授权页面", "抽取标题、状态码和链接摘要", "整理证据形成结论"],
                    remediation="如需更深分析，请进一步限定页面范围或目标路径。",
                )
            )
            summary = "Web 分析已完成当前范围内的公开取证。"
            limitations.append("当前结论仅覆盖已授权页面和非破坏性观察。")
        elif "code_review" in labels or repo_hit:
            kind = "code_review_report"
            titles = "；".join(item.get("title", "") for item in evidence[:3] if item.get("title")) or "当前证据"
            findings.append(
                Finding(
                    finding_id=new_id("fd"),
                    title="形成结构化源码分析结论",
                    severity="info",
                    confidence=0.84 if evidence else 0.66,
                    claim=f"当前源码分析结论主要建立在这些证据之上：{titles}。",
                    evidence_refs=evidence_ids[:3],
                    reproduction_steps=["在授权仓库范围内收集证据", "阅读实现线索", "汇总结论与限制"],
                    remediation="如需更深入的缺陷审计，请继续限定模块、文件或风险主题。",
                )
            )
            summary = "源码分析任务已完成，报告以当前沉淀的 evidence 组织结论。"
            limitations.append("当前分析不代表已覆盖全部逻辑路径。")
        else:
            kind = "analysis_note"
            summary = "本次任务已完成阶段性分析，当前输出以证据摘要为主。"
            limitations.append("当前缺少足够强的证据来支撑更具体的结论。")

        if not findings:
            limitations.append("未形成高置信度 finding，保留现有证据供后续继续分析。")

        return ReportDraft(
            kind=kind,
            title=self._report_title(dossier, kind),
            summary=summary,
            findings=findings,
            limitations=limitations,
            writer_summary="我已基于当前任务图、已完成节点和证据生成最终报告草稿。",
            evidence_refs=evidence_ids[:6],
        )

    def _report_title(self, dossier: ReportDossier, kind: str) -> str:
        objective = dossier.intent_profile.objective if dossier.intent_profile else dossier.user_task
        compact = re.sub(r"\s+", " ", objective).strip()
        return compact[:80] or f"DigAgent {kind}"

    def _first_fact_value(self, evidence: list[dict[str, Any]], key: str) -> Any:
        for item in evidence:
            for fact in item.get("structured_facts", []):
                if fact.get("key") == key:
                    return fact.get("value")
        return None

    def _best_flag_from_evidence(self, evidence: list[dict[str, Any]]) -> str | None:
        candidates: list[str] = []
        for item in evidence:
            haystacks = [item.get("title", ""), item.get("summary", "")]
            for fact in item.get("structured_facts", []):
                if fact.get("key") in {"candidate_flag", "final_flag", "decoded_flag"}:
                    haystacks.append(str(fact.get("value") or ""))
            for haystack in haystacks:
                for candidate in re.findall(r"[A-Za-z0-9_]+\{[^}\n]+\}", haystack):
                    if candidate.lower().startswith("flag{"):
                        return candidate
                    candidates.append(candidate)
        return candidates[0] if candidates else None

    def _best_flag_refs(self, evidence: list[dict[str, Any]], flag: str | None) -> list[str]:
        if not flag:
            return []
        refs: list[str] = []
        for item in evidence:
            if flag in f"{item.get('title', '')}\n{item.get('summary', '')}":
                refs.append(item.get("evidence_id"))
                continue
            for fact in item.get("structured_facts", []):
                if str(fact.get("value") or "") == flag:
                    refs.append(item.get("evidence_id"))
                    break
        return [ref for ref in refs if ref][:3]

    def _test_direct_answer(
        self,
        *,
        user_question: str,
        session_status: str,
        run_status: str | None,
        graph: dict[str, Any],
        evidence_summaries: list[str],
        memory_context: dict[str, Any],
        pending_approvals: int,
        awaiting_reason: str | None,
        budget: dict[str, Any],
    ) -> str:
        lower_question = user_question.lower()
        if "什么是ctf" in lower_question or "解释一下什么是ctf" in lower_question:
            return "CTF 是 Capture The Flag，一类以解题、取证、逆向、Web、密码学等方向为主的安全竞赛。通常会给出题面、附件或目标环境，参赛者需要在受控范围内分析并拿到 flag。"
        if any(marker in lower_question for marker in {"解释", "介绍", "说明", "what is"}):
            return f"这是一个答疑消息，不会改动当前任务图。就这条问题本身看，我理解你是在请求解释：{user_question.strip()}。"
        lines = [f"当前 session 状态是 {session_status}。"]
        if run_status:
            lines.append(f"当前 run 状态是 {run_status}。")
        nodes = graph.get("nodes", [])
        running = [node["title"] for node in nodes if node.get("status") == "running"]
        ready = [node["title"] for node in nodes if node.get("status") == "ready"]
        blocked = [node["title"] for node in nodes if node.get("status") in {"blocked", "waiting_approval", "waiting_user_input"}]
        if running:
            lines.append("正在执行：" + "；".join(running[:3]) + "。")
        if ready:
            lines.append("接下来可推进：" + "；".join(ready[:3]) + "。")
        if blocked:
            lines.append("当前阻塞节点：" + "；".join(blocked[:3]) + "。")
        if awaiting_reason:
            lines.append(f"阻塞原因：{awaiting_reason}")
        if evidence_summaries:
            lines.append("最近证据：" + "；".join(evidence_summaries[:3]) + "。")
        if memory_context.get("memory_items"):
            lines.append("相关长期记忆：" + "；".join(memory_context["memory_items"][:2]) + "。")
        if pending_approvals:
            lines.append(f"当前还有 {pending_approvals} 个待审批动作。")
        if budget:
            lines.append(
                "预算使用："
                f"工具 {budget.get('tool_calls_used', 0)}/{budget.get('max_tool_calls', 0)}，"
                f"活跃 tool {budget.get('active_tools', 0)}/{budget.get('max_parallel_tools', 0)}，"
                f"活跃 subagent {budget.get('active_subagents', 0)}/{budget.get('max_parallel_subagents', 0)}。"
            )
        if "审批" in user_question or "approval" in user_question.lower():
            lines.append("需要审批是因为这个动作被权限层判定为高风险，必须先对精确动作摘要做人工确认。")
        return "\n".join(lines)

    def _test_response(self, task: str) -> str:
        candidate = self._test_ctf_response(task)
        if candidate:
            return candidate
        task = task.strip()
        if len(task) > 180:
            task = task[:180] + "..."
        return f"离线模式摘要：{task}"

    def _test_ctf_response(self, task: str) -> str | None:
        token = self._extract_ctf_blob(task)
        lower = task.lower()
        if not token:
            return None
        if any(marker in task for marker in ["2 个栅栏", "2个栅栏"]) or "rail" in lower:
            decoded = self._rail_fence_decode(token, 2)
            if decoded and decoded != token:
                return f"根据题面提到的 2 个栅栏，按 rail fence 2 解码后得到 {decoded}。这是当前最可信的最终答案。"
        return None

    def _extract_ctf_blob(self, task: str) -> str | None:
        quoted = re.findall(r"`([^`]+)`", task)
        if quoted:
            return quoted[0]
        flag_like = re.findall(r"[A-Za-z0-9_]+\{[^}]+\}", task)
        if flag_like:
            return flag_like[0]
        morse = re.findall(r"[.\-/ ]{6,}", task)
        if morse:
            return morse[0].strip()
        return None

    def _rail_fence_decode(self, cipher: str, rails: int) -> str:
        if rails <= 1 or not cipher:
            return cipher
        pattern = list(range(rails)) + list(range(rails - 2, 0, -1))
        rail_counts = [0] * rails
        for idx in range(len(cipher)):
            rail_counts[pattern[idx % len(pattern)]] += 1
        rails_data = []
        start = 0
        for count in rail_counts:
            rails_data.append(list(cipher[start : start + count]))
            start += count
        positions = [0] * rails
        result = []
        for idx in range(len(cipher)):
            rail = pattern[idx % len(pattern)]
            result.append(rails_data[rail][positions[rail]])
            positions[rail] += 1
        return "".join(result)
