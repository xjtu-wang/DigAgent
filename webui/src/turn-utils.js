const TERMINAL_STATUSES = [
  "completed",
  "failed",
  "timed_out",
  "cancelled",
  "superseded",
  "awaiting_approval",
  "awaiting_user_input",
];

const ACTION_EVENT_TYPES = [
  "tool_result",
  "subagent",
  "task_node_started",
  "task_node_completed",
  "task_node_waiting_approval",
  "task_node_waiting_user_input",
  "aggregate",
  "evidence_added",
  "report_ready",
  "approval_required",
  "approval_resolved",
];

const STATUS_LABELS = {
  created: "已创建",
  planning: "规划中",
  running: "执行中",
  aggregating: "整理中",
  reporting: "撰写中",
  awaiting_approval: "等待审批",
  awaiting_user_input: "等待补充",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  superseded: "已被替代",
  timed_out: "超时",
};

export const TERMINAL_TURN_STATUSES = new Set(TERMINAL_STATUSES);

function compact(value, limit = 160) {
  if (!value) {
    return "";
  }
  const normalized = String(value).replace(/\s+/g, " ").trim();
  if (normalized.length <= limit) {
    return normalized;
  }
  return `${normalized.slice(0, limit - 1).trimEnd()}...`;
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function groupByTurn(items) {
  const grouped = new Map();
  for (const item of items) {
    const turnId = item?.turn_id;
    if (!turnId) {
      continue;
    }
    const bucket = grouped.get(turnId) || [];
    bucket.push(item);
    grouped.set(turnId, bucket);
  }
  return grouped;
}

function compareDesc(left, right) {
  return new Date(right || 0) - new Date(left || 0);
}

function firstMessage(messages, role) {
  return messages.find((item) => item.role === role) || null;
}

function lastMessage(messages, role) {
  const candidates = messages.filter((item) => item.role === role);
  return candidates.at(-1) || null;
}

function targetParts(turn) {
  const scope = asObject(turn.scope);
  const targets = [];
  targets.push(...asArray(scope.repo_paths));
  targets.push(...asArray(scope.allowed_domains));
  targets.push(...asArray(turn.targets));
  if (turn.target) {
    targets.push(turn.target);
  }
  return Array.from(new Set(targets.filter(Boolean).map(String)));
}

function summarizeActionEvent(event) {
  const data = asObject(event?.data);
  if (event?.type === "tool_result") {
    return compact(data.summary || data.title || data.tool_name || "执行了一个工具动作");
  }
  if (event?.type === "subagent") {
    return compact(data.result?.summary || data.task?.goal || "子 Agent 返回结果");
  }
  if (event?.type === "task_node_started" || event?.type === "task_node_completed") {
    return compact(data.title || data.node_id || "更新了一个 workflow 步骤");
  }
  if (event?.type === "task_node_waiting_approval") {
    return compact(data.reason || "workflow 步骤等待审批");
  }
  if (event?.type === "task_node_waiting_user_input") {
    return compact(data.question || data.prompt || "workflow 步骤等待补充信息");
  }
  if (event?.type === "aggregate") {
    return compact(data.summary || "完成了阶段汇总");
  }
  if (event?.type === "evidence_added") {
    return compact(data.title || data.evidence_id || "新增证据");
  }
  if (event?.type === "report_ready") {
    return compact(data.summary || data.report_id || "生成了报告");
  }
  if (event?.type === "approval_required") {
    return "触发了一次审批请求";
  }
  if (event?.type === "approval_resolved") {
    return data.status === "approved" ? "审批已通过，继续执行" : "审批被拒绝";
  }
  return compact(data.summary || data.title || data.reason || event?.type || "");
}

function waitingReason(turn, events) {
  if (turn.awaiting_reason) {
    return turn.awaiting_reason;
  }
  const waitingEvent = events.find((event) => ["awaiting_approval", "awaiting_user_input", "task_node_waiting_approval", "task_node_waiting_user_input"].includes(event.type));
  const data = asObject(waitingEvent?.data);
  return data.reason || data.question || data.prompt || "";
}

export function normalizeTurn(turn) {
  const value = asObject(turn);
  return {
    ...value,
    turn_id: value.turn_id || null,
    session_id: value.session_id || null,
    status: value.status || "created",
    pending_approvals: asArray(value.pending_approvals),
    approval_ids: asArray(value.approval_ids),
    evidence_ids: asArray(value.evidence_ids),
    artifact_ids: asArray(value.artifact_ids),
    turn_ids: asArray(value.turn_ids),
    budget: asObject(value.budget),
    budget_usage: asObject(value.budget_usage),
    scope: asObject(value.scope),
  };
}

export function normalizeTurns(turns) {
  return asArray(turns)
    .map(normalizeTurn)
    .filter((item) => item.turn_id)
    .sort((left, right) => compareDesc(left.created_at, right.created_at));
}

export function normalizeTurnEvent(event) {
  const value = asObject(event);
  const data = asObject(value.data);
  return {
    ...value,
    data,
    turn_id: value.turn_id || data.turn_id || null,
  };
}

export function turnStatusLabel(status) {
  return STATUS_LABELS[status] || String(status || "unknown");
}

export function turnGoal(turn, userMessage = null) {
  return (
    turn.goal
    || turn.user_task
    || turn.task
    || userMessage?.content
    || ""
  );
}

export function turnTargetSummary(turn) {
  const parts = targetParts(turn);
  if (!parts.length) {
    return "";
  }
  return compact(parts.join(" · "), 120);
}

export function turnResultSummary(turn, assistantMessage = null, events = []) {
  if (turn.status === "failed" || turn.status === "timed_out") {
    return compact(turn.error_message || waitingReason(turn, events) || "执行失败。", 180);
  }
  if (turn.status === "superseded") {
    return compact(turn.error_message || "当前执行已被新的消息替代。", 180);
  }
  if (turn.status === "awaiting_approval" || turn.status === "awaiting_user_input") {
    return compact(waitingReason(turn, events) || "执行被挂起，等待进一步处理。", 180);
  }
  return compact(
    turn.result_summary
      || turn.summary
      || assistantMessage?.content
      || turn.final_response
      || (turn.report_id ? "执行已完成，并生成报告。" : ""),
    180,
  );
}

export function turnRecentActionSummary(turn, events = []) {
  const candidate = [...events]
    .sort((left, right) => compareDesc(left.created_at, right.created_at))
    .find((event) => ACTION_EVENT_TYPES.includes(event.type));
  if (!candidate) {
    if (turn.status === "completed") {
      return "本轮执行已完成。";
    }
    if (turn.status === "failed" || turn.status === "timed_out") {
      return compact(turn.error_message || "本轮执行失败。", 140);
    }
    if (turn.status === "superseded") {
      return compact(turn.error_message || "本轮执行已被新的消息替代。", 140);
    }
    return compact(turn.awaiting_reason || "", 140);
  }
  return summarizeActionEvent(candidate);
}

export function buildTurnTimelineEntries(turns, messages = [], events = []) {
  const messagesByTurn = groupByTurn(messages);
  const eventsByTurn = groupByTurn(events.map(normalizeTurnEvent));
  return normalizeTurns(turns).map((turn) => {
    const turnMessages = (messagesByTurn.get(turn.turn_id) || []).sort((left, right) => new Date(left.created_at) - new Date(right.created_at));
    const turnEvents = (eventsByTurn.get(turn.turn_id) || []).sort((left, right) => compareDesc(left.created_at, right.created_at));
    const userMessage = firstMessage(turnMessages, "user");
    const assistantMessage = lastMessage(turnMessages, "assistant");
    const previewEvents = turnEvents.slice(0, 3);
    const createdAt = userMessage?.created_at || turn.created_at || assistantMessage?.created_at || previewEvents.at(-1)?.created_at || new Date().toISOString();
    return {
      event_id: `turn-${turn.turn_id}`,
      type: "turn_card",
      session_id: turn.session_id,
      turn_id: turn.turn_id,
      created_at: createdAt,
      data: {
        turn_id: turn.turn_id,
        status: turn.status,
        status_label: turnStatusLabel(turn.status),
        goal: turnGoal(turn, userMessage),
        target: turnTargetSummary(turn),
        result_summary: turnResultSummary(turn, assistantMessage, turnEvents),
        action_summary: turnRecentActionSummary(turn, turnEvents),
        event_preview: previewEvents.map((event) => ({
          event_id: event.event_id,
          type: event.type,
          created_at: event.created_at,
          summary: summarizeActionEvent(event),
        })),
        event_count: turnEvents.length,
        approval_count: turn.pending_approvals.length || turn.approval_ids.length,
        evidence_count: turn.evidence_ids.length,
        artifact_count: turn.artifact_ids.length,
        report_id: turn.report_id || null,
        raw: {
          turn,
          messages: turnMessages,
          recent_events: turnEvents.slice(0, 8),
        },
      },
    };
  });
}
