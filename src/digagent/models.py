from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class DigAgentModel(BaseModel):
    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
    }


LAST_MESSAGE_PREVIEW_LIMIT = 140


class SessionStatus(StrEnum):
    IDLE = "idle"
    ACTIVE_TURN = "active_turn"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_USER_INPUT = "awaiting_user_input"
    ARCHIVED = "archived"


class SessionTitleStatus(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"


class SessionTitleSource(StrEnum):
    MANUAL = "manual"
    SEED = "seed"
    MODEL = "model"


class UserTurnDisposition(StrEnum):
    DIRECT_ANSWER = "direct_answer"
    CREATE_TURN = "create_turn"
    CONTINUE_TURN = "continue_turn"
    REJECT = "reject"


class MessageRoute(StrEnum):
    DIRECT_ANSWER = "direct_answer"
    CLARIFICATION_INPUT = "clarification_input"
    APPROVAL_RESPONSE = "approval_response"
    CANCEL = "cancel"
    NEW_TURN_REQUEST = "new_turn_request"


class TurnStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_USER_INPUT = "awaiting_user_input"
    RUNNING = "running"
    AGGREGATING = "aggregating"
    REPORTING = "reporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    TIMED_OUT = "timed_out"


class TaskNodeKind(StrEnum):
    INPUT = "input"
    TOOL = "tool"
    SKILL = "skill"
    SUBAGENT = "subagent"
    AGGREGATE = "aggregate"
    REPORT = "report"
    EXPORT = "export"


class TaskNodeStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_USER_INPUT = "waiting_user_input"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    DEPRECATED = "deprecated"


class GraphOpType(StrEnum):
    ADD_NODE = "ADD_NODE"
    UPDATE_NODE = "UPDATE_NODE"
    UPDATE_GRAPH = "UPDATE_GRAPH"
    ADD_EDGE = "ADD_EDGE"
    REMOVE_EDGE = "REMOVE_EDGE"
    DEPRECATE_NODE = "DEPRECATE_NODE"


class ActionType(StrEnum):
    TOOL = "tool"
    SKILL = "skill"
    SUBAGENT = "subagent"
    EXPORT = "export"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class PermissionRule(StrEnum):
    INHERIT = "inherit"
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class GraphPlanningState(StrEnum):
    OPEN = "open"
    COMPLETE = "complete"


class Scope(DigAgentModel):
    repo_paths: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


class RuntimeBudget(DigAgentModel):
    max_parallel_tools: int = 2
    max_parallel_subagents: int = 3
    max_tool_calls: int = 50
    max_runtime_seconds: int = 1800


class BudgetUsage(DigAgentModel):
    tool_calls_used: int = 0
    runtime_seconds_used: float = 0.0
    active_subagents: int = 0
    active_tools: int = 0


class SessionPermissionOverrides(DigAgentModel):
    tool_rules: dict[str, PermissionRule] = Field(default_factory=dict)
    mcp_server_rules: dict[str, PermissionRule] = Field(default_factory=dict)
    risk_tag_rules: dict[str, PermissionRule] = Field(default_factory=dict)
    auto_approve: bool = False
    budget_override: RuntimeBudget | None = None

    def is_empty(self) -> bool:
        return (
            not self.tool_rules
            and not self.mcp_server_rules
            and not self.risk_tag_rules
            and not self.auto_approve
            and self.budget_override is None
        )


CONFIDENCE_ALIASES = {
    "very_low": 0.2,
    "low": 0.4,
    "medium": 0.65,
    "high": 0.85,
    "very_high": 0.95,
}


class IntentProfile(DigAgentModel):
    objective: str
    labels: list[str] = Field(default_factory=list)
    report_kind_hint: str | None = None
    confidence: float = 0.75

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        confidence = payload.get("confidence")
        if isinstance(confidence, str):
            normalized = confidence.strip().lower().replace(" ", "_")
            if normalized in CONFIDENCE_ALIASES:
                payload["confidence"] = CONFIDENCE_ALIASES[normalized]
            else:
                try:
                    payload["confidence"] = float(confidence)
                except ValueError:
                    pass
        return payload


class TaskEdge(DigAgentModel):
    source: str
    target: str

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        payload["source"] = payload.get("source") or payload.get("from_node_id") or payload.get("from")
        payload["target"] = payload.get("target") or payload.get("to_node_id") or payload.get("to")
        payload.pop("from_node_id", None)
        payload.pop("to_node_id", None)
        payload.pop("type", None)
        return payload


class GraphEditOp(DigAgentModel):
    op_type: GraphOpType
    node_id: str | None = None
    node: dict[str, Any] | None = None
    edge: TaskEdge | None = None
    patch: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        payload["op_type"] = payload.get("op_type") or payload.get("type")
        if payload.get("edge") is None:
            edge_keys = {"source", "target", "from_node_id", "to_node_id", "from", "to"}
            if edge_keys & payload.keys():
                payload["edge"] = {
                    key: payload.pop(key)
                    for key in list(edge_keys | {"type"})
                    if key in payload
                }
        return payload


class TaskNode(DigAgentModel):
    node_id: str
    title: str
    kind: TaskNodeKind
    status: TaskNodeStatus = TaskNodeStatus.PENDING
    description: str
    summary: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    block_reason: str | None = None
    action_id: str | None = None
    action_request: dict[str, Any] | None = None
    approval_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_refs: list[str] = Field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 1
    planning_phase: int = 0
    replanned_from_node_id: str | None = None
    superseded_by: str | None = None
    owner_profile_name: str | None = None
    grant_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = False

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        payload.pop("plugin_id", None)
        payload.pop("command_name", None)
        metadata = dict(payload.get("metadata") or {})
        if payload.get("kind") in {TaskNodeKind.SUBAGENT, TaskNodeKind.SUBAGENT.value}:
            payload["owner_profile_name"] = payload.get("owner_profile_name") or metadata.get("owner_profile_name")
        payload["metadata"] = _normalize_legacy_tool_metadata(payload.get("kind"), metadata)
        if payload.get("kind") in {TaskNodeKind.SUBAGENT, TaskNodeKind.SUBAGENT.value} and not payload.get("owner_profile_name"):
            alias = (
                metadata.get("owner_profile_name")
                or metadata.get("profile_name")
                or metadata.get("profile")
            )
            if alias:
                payload["owner_profile_name"] = str(alias)
        return payload


LEGACY_TOOL_ARGUMENT_ALIASES = {
    "web_search": {
        "max_results": "limit",
    },
    "vuln_kb_lookup": {
        "keyword": "query",
    },
}


def _normalize_legacy_tool_metadata(kind: Any, metadata: dict[str, Any]) -> dict[str, Any]:
    if kind not in {TaskNodeKind.TOOL, TaskNodeKind.TOOL.value}:
        return metadata
    if metadata.get("tool_name") or not metadata.get("tool"):
        return metadata
    tool_name = str(metadata.get("tool") or "").strip()
    if not tool_name:
        return metadata
    aliases = LEGACY_TOOL_ARGUMENT_ALIASES.get(tool_name, {})
    arguments = dict(metadata.get("arguments") or {})
    for key, value in metadata.items():
        if key in {"tool", "tool_name", "arguments"}:
            continue
        arguments.setdefault(aliases.get(key, key), value)
    normalized = dict(metadata)
    normalized["tool_name"] = tool_name
    normalized["arguments"] = arguments
    return normalized


def _normalize_graph_payload(payload: dict[str, Any]) -> dict[str, Any]:
    graph = dict(payload)
    nodes = [dict(node) for node in graph.get("nodes", [])]
    edges = [
        edge if isinstance(edge, dict) else edge.model_dump(mode="json")
        for edge in graph.get("edges", [])
    ]
    node_ids = [node.get("node_id") for node in nodes if node.get("node_id")]
    depends_on: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    children: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        source = edge.get("source")
        target = edge.get("target")
        if source in children and target in depends_on:
            children[source].add(target)
            depends_on[target].add(source)
    ready_node_ids: list[str] = []
    active_node_ids: list[str] = []
    completed_node_ids: list[str] = []
    blocked_node_ids: list[str] = []
    deprecated_node_ids: list[str] = []
    for node in nodes:
        node_id = node["node_id"]
        metadata = dict(node.get("metadata") or {})
        node["metadata"] = metadata
        node["depends_on"] = sorted(set(node.get("depends_on", [])) | depends_on.get(node_id, set()))
        node["children"] = sorted(set(node.get("children", [])) | children.get(node_id, set()))
        status = node.get("status", TaskNodeStatus.PENDING.value)
        if node.get("superseded_by"):
            status = TaskNodeStatus.DEPRECATED.value
            node["status"] = status
        if status == TaskNodeStatus.WAITING_USER_INPUT.value:
            question = metadata.get("question") or node.get("block_reason") or node.get("summary") or node.get("description")
            if question:
                metadata["question"] = question
        if status == TaskNodeStatus.PENDING.value and not node["depends_on"]:
            status = TaskNodeStatus.READY.value
            node["status"] = status
        node["is_active"] = status == TaskNodeStatus.RUNNING.value
        if status == TaskNodeStatus.READY.value:
            ready_node_ids.append(node_id)
        elif status == TaskNodeStatus.RUNNING.value:
            active_node_ids.append(node_id)
        elif status == TaskNodeStatus.COMPLETED.value:
            completed_node_ids.append(node_id)
        elif status in {TaskNodeStatus.BLOCKED.value, TaskNodeStatus.WAITING_APPROVAL.value, TaskNodeStatus.WAITING_USER_INPUT.value}:
            blocked_node_ids.append(node_id)
        elif status == TaskNodeStatus.DEPRECATED.value:
            deprecated_node_ids.append(node_id)
    graph["nodes"] = nodes
    graph["edges"] = edges
    graph["ready_node_ids"] = ready_node_ids
    graph["active_node_ids"] = active_node_ids
    graph["completed_node_ids"] = completed_node_ids
    graph["blocked_node_ids"] = blocked_node_ids
    graph["deprecated_node_ids"] = deprecated_node_ids
    graph.setdefault("planning_state", GraphPlanningState.COMPLETE.value)
    graph.setdefault("graph_version", 1)
    graph.setdefault("applied_ops", [])
    return graph


class TaskGraph(DigAgentModel):
    turn_id: str
    planning_state: GraphPlanningState = GraphPlanningState.COMPLETE
    graph_version: int = 1
    nodes: list[TaskNode] = Field(default_factory=list)
    edges: list[TaskEdge] = Field(default_factory=list)
    ready_node_ids: list[str] = Field(default_factory=list)
    active_node_ids: list[str] = Field(default_factory=list)
    completed_node_ids: list[str] = Field(default_factory=list)
    blocked_node_ids: list[str] = Field(default_factory=list)
    deprecated_node_ids: list[str] = Field(default_factory=list)
    applied_ops: list[GraphEditOp] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return _normalize_graph_payload(value)


class PlanningBundle(DigAgentModel):
    intent_profile: IntentProfile
    task_graph: TaskGraph
    planner_message: str
    clarify_message: str | None = None


class ExecutionBatchDecision(DigAgentModel):
    node_ids: list[str] = Field(default_factory=list)
    planner_message: str | None = None
    rationale: str | None = None


class MessageRoutingDecision(DigAgentModel):
    route: MessageRoute
    rationale: str | None = None


class ActionTargets(DigAgentModel):
    paths: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class ActionRequest(DigAgentModel):
    action_id: str
    turn_id: str
    actor_agent_id: str
    action_type: ActionType
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    targets: ActionTargets = Field(default_factory=ActionTargets)
    justification: str
    risk_tags: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    created_at: str
    node_id: str | None = None


class DelegationGrant(DigAgentModel):
    grant_id: str
    parent_action_id: str
    turn_id: str
    node_id: str
    delegator_profile_name: str
    delegatee_profile_name: str
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)
    max_tool_calls: int = 0
    expires_at: str | None = None


class PermissionOutcome(DigAgentModel):
    decision: PermissionDecision
    reason: str
    normalized_targets: ActionTargets = Field(default_factory=ActionTargets)


class ApprovalToken(DigAgentModel):
    approval_id: str
    action_id: str
    action_digest: str
    issued_at: str
    resolver: str
    approved: bool


class ApprovalChallenge(DigAgentModel):
    approval_id: str
    action_id: str
    action_digest: str
    challenge: str
    issued_at: str
    expires_at: str | None = None


class ApprovalRecord(DigAgentModel):
    approval_id: str
    action_id: str
    turn_id: str
    status: ApprovalStatus
    action_digest: str
    policy_key: str | None = None
    kind: str = "primary"
    parent_approval_id: str | None = None
    superseded_by: str | None = None
    requested_by: str
    requested_at: str
    resolved_at: str | None = None
    resolver: str | None = None
    reason: str | None = None
    challenge: str | None = None
    challenge_issued_at: str | None = None
    challenge_expires_at: str | None = None
    node_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_payload(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        payload.pop("run_id", None)
        return payload


class AuditEvent(DigAgentModel):
    event_id: str
    timestamp: str
    turn_id: str
    action_id: str
    actor_agent_id: str
    decision: PermissionDecision
    executor: str
    result: str
    exit_code: int | None = None
    artifact_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    detail: str | None = None
    node_id: str | None = None


class MessageRecord(DigAgentModel):
    message_id: str
    session_id: str
    turn_id: str | None = None
    role: MessageRole
    sender: str
    content: str
    speaker_profile: str | None = None
    addressed_participants: list[str] = Field(default_factory=list)
    participant_profile: str | None = None
    handoff_from: str | None = None
    handoff_to: str | None = None
    artifact_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: str


class SessionRecord(DigAgentModel):
    schema_version: str = "2.0"
    session_id: str
    title: str
    title_status: SessionTitleStatus = SessionTitleStatus.READY
    title_source: SessionTitleSource = SessionTitleSource.MANUAL
    created_at: str
    updated_at: str
    status: SessionStatus = SessionStatus.IDLE
    root_agent_profile: str
    intent_profile: IntentProfile | None = None
    scope: Scope = Field(default_factory=Scope)
    permission_overrides: SessionPermissionOverrides = Field(default_factory=SessionPermissionOverrides)
    turn_ids: list[str] = Field(default_factory=list)
    active_turn_id: str | None = None
    pending_approval_ids: list[str] = Field(default_factory=list)
    pending_user_question: str | None = None
    conversation_summary: str | None = None
    last_intent_type: str | None = None
    speaker_profile: str | None = None
    addressed_participants: list[str] = Field(default_factory=list)
    participant_profile: str | None = None
    handoff_from: str | None = None
    handoff_to: str | None = None
    last_user_message_id: str | None = None
    last_agent_message_id: str | None = None
    last_message_preview: str | None = None
    memory_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    report_refs: list[str] = Field(default_factory=list)
    latest_report_id: str | None = None
    last_report_id: str | None = None
    archived_at: str | None = None


class SessionSummary(DigAgentModel):
    session_id: str
    title: str
    title_status: SessionTitleStatus = SessionTitleStatus.READY
    title_source: SessionTitleSource = SessionTitleSource.MANUAL
    status: SessionStatus
    updated_at: str
    active_turn_id: str | None = None
    pending_approval_count: int = 0
    speaker_profile: str | None = None
    addressed_participants: list[str] = Field(default_factory=list)
    participant_profile: str | None = None
    handoff_from: str | None = None
    handoff_to: str | None = None
    last_message_preview: str | None = None
    latest_report_id: str | None = None


class ArtifactRecord(DigAgentModel):
    artifact_id: str
    kind: str
    session_id: str
    turn_id: str
    filename: str | None = None
    storage_path: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: str


class EvidenceRecord(DigAgentModel):
    evidence_id: str
    session_id: str
    turn_id: str
    type: str
    title: str
    summary: str
    source: dict[str, Any]
    artifact_refs: list[str] = Field(default_factory=list)
    hash: str
    content_ref: str | None = None
    structured_facts: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.8
    sensitivity: str = "low"
    created_at: str


class MemoryRecord(DigAgentModel):
    memory_id: str
    kind: str
    summary: str
    content: dict[str, Any]
    source_session_id: str
    source_turn_id: str
    source_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.75
    sensitivity: str = "low"
    created_at: str
    updated_at: str
    expires_at: str | None = None


class MemoryPromotionCandidate(DigAgentModel):
    kind: str
    summary: str
    content: dict[str, Any]
    source_evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.75
    sensitivity: str = "low"


class DailyMemoryNote(DigAgentModel):
    heading: str
    body: str
    source_session_id: str
    source_turn_id: str
    evidence_refs: list[str] = Field(default_factory=list)
    created_at: str


class WikiClaim(DigAgentModel):
    claim: str
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 0.75


class WikiEntry(DigAgentModel):
    entry_id: str
    title: str
    summary: str
    source_session_id: str
    source_turn_id: str
    claims: list[WikiClaim] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class Finding(DigAgentModel):
    finding_id: str
    title: str
    severity: str
    confidence: float
    claim: str
    evidence_refs: list[str] = Field(default_factory=list)
    reproduction_steps: list[str] = Field(default_factory=list)
    remediation: str


class ReportRecord(DigAgentModel):
    report_id: str
    session_id: str
    turn_id: str
    kind: str
    title: str
    scope: dict[str, Any]
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    export_paths: dict[str, str] = Field(default_factory=dict)
    writer_summary: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    generated_at: str


class ReportDossier(DigAgentModel):
    user_task: str
    scope: Scope
    intent_profile: IntentProfile | None = None
    task_graph: TaskGraph
    goal_summary: str | None = None
    completed_nodes: list[dict[str, Any]] = Field(default_factory=list)
    completed_node_kinds: list[str] = Field(default_factory=list)
    source_evidence_types: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_memory: list[dict[str, Any]] = Field(default_factory=list)
    followup_messages: list[str] = Field(default_factory=list)


class ReportDraft(DigAgentModel):
    kind: str
    title: str
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    writer_summary: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class AgentProfile(DigAgentModel):
    name: str
    description: str
    provider: str = "openai-compatible"
    model: str | None = None
    system_prompt: str
    subagents: list[str] = Field(default_factory=list)
    tool_allowlist: list[str] = Field(default_factory=list)
    mcp_server_allowlist: list[str] = Field(default_factory=list)
    network_scope: list[str] = Field(default_factory=list)
    filesystem_scope: list[str] = Field(default_factory=list)
    runtime_budget: RuntimeBudget = Field(default_factory=RuntimeBudget)


class ToolManifest(DigAgentModel):
    name: str
    description: str
    path: str | None = None
    version: int | None = None
    function: str
    args_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    risk_tags: list[str] = Field(default_factory=list)
    timeout_sec: int | None = None
    env_policy: str = "inherit"
    working_dir: str | None = None
    interrupt_on_call: bool = False
    memory_hooks: dict[str, Any] = Field(default_factory=dict)
    report_hooks: dict[str, Any] = Field(default_factory=dict)


class SkillManifest(DigAgentModel):
    name: str
    description: str
    path: str
    version: str | None = None
    entrypoints: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    recommended_tools: list[str] = Field(default_factory=list)
    risk_level: str | None = None
    references: list[str] = Field(default_factory=list)
    agent_config_path: str | None = None
    agent_display_name: str | None = None
    short_description: str | None = None
    agent_policy: dict[str, Any] = Field(default_factory=dict)
    allow_implicit_invocation: bool = False
    downstream_only: bool = False
    markdown: str


class SubagentTask(DigAgentModel):
    task_id: str
    turn_id: str
    node_id: str
    goal: str
    grant_id: str | None = None
    evidence_summaries: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)


class MemorySearchQuery(DigAgentModel):
    query: str
    session_id: str | None = None
    turn_id: str | None = None
    scope: str = "session"
    sensitivity: str = "normal"
    limit: int = 5


class MemoryHit(DigAgentModel):
    ref: str
    source_type: str
    title: str
    summary: str
    content: str
    score: float
    sensitivity: str = "low"
    source_session_id: str | None = None
    source_turn_id: str | None = None
    updated_at: str | None = None


class CVERecord(DigAgentModel):
    cve_id: str
    published_at: str | None = None
    updated_at: str | None = None
    descriptions: list[str] = Field(default_factory=list)
    cwes: list[str] = Field(default_factory=list)
    affected_products: list[str] = Field(default_factory=list)
    cvss: dict[str, Any] = Field(default_factory=dict)
    references: list[dict[str, Any]] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    kev: bool = False
    kev_date_added: str | None = None
    kev_due_date: str | None = None
    known_ransomware_campaign_use: str | None = None
    source: str = "nvd"
    source_hash: str


class CveSyncState(DigAgentModel):
    status: str = "idle"
    source: str = "nvd+kev"
    base_url: str = "https://services.nvd.nist.gov/rest/json/cves/2.0"
    total_records: int = 0
    normalized_records: int = 0
    kev_records: int = 0
    last_synced_at: str | None = None
    last_error: str | None = None
    last_source_hash: str | None = None
    next_start_index: int = 0
    page_size: int = 2000
    running: bool = False


class TurnRecord(DigAgentModel):
    schema_version: str = "2.0"
    turn_id: str
    session_id: str
    root_agent_id: str = "sisyphus"
    profile_name: str
    status: TurnStatus
    auto_approve: bool = False
    intent_profile: IntentProfile | None = None
    user_task: str
    speaker_profile: str | None = None
    addressed_participants: list[str] = Field(default_factory=list)
    participant_profile: str | None = None
    handoff_from: str | None = None
    handoff_to: str | None = None
    scope: Scope = Field(default_factory=Scope)
    task_graph: TaskGraph | None = None
    pending_actions: list[str] = Field(default_factory=list)
    active_subagents: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    memory_candidate_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    approval_ids: list[str] = Field(default_factory=list)
    followup_messages: list[str] = Field(default_factory=list)
    trigger_message_id: str | None = None
    resume_from_action_id: str | None = None
    awaiting_reason: str | None = None
    report_id: str | None = None
    budget: RuntimeBudget = Field(default_factory=RuntimeBudget)
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)
    graph_edit_rounds: int = 0
    final_response: str | None = None
    planner_summary: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class TurnEvent(DigAgentModel):
    event_id: str
    session_id: str
    turn_id: str | None = None
    type: str
    data: dict[str, Any]
    turn_event_index: int | None = None
    session_event_index: int | None = None
    speaker_profile: str | None = None
    addressed_participants: list[str] = Field(default_factory=list)
    participant_profile: str | None = None
    handoff_from: str | None = None
    handoff_to: str | None = None
    created_at: str


class SubagentResult(DigAgentModel):
    subagent_id: str
    status: str
    summary: str
    evidence_ids: list[str] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    executed_action_ids: list[str] = Field(default_factory=list)
    memory_candidates: list[dict[str, Any]] = Field(default_factory=list)


class UserTurnResult(DigAgentModel):
    disposition: UserTurnDisposition
    session_id: str
    turn_id: str | None = None
    message_id: str | None = None
    assistant_message: str | None = None
    speaker_profile: str | None = None
    addressed_participants: list[str] = Field(default_factory=list)
    participant_profile: str | None = None
    handoff_from: str | None = None
    handoff_to: str | None = None
    approval_ids: list[str] = Field(default_factory=list)
    ignored_intents: list[str] = Field(default_factory=list)
    reason: str | None = None
