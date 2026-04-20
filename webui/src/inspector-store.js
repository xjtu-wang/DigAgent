import { compactText } from "./chat-utils.js";
import { turnGoal, turnResultSummary } from "./turn-utils.js";

const NODE_STATUS_BY_TURN_STATUS = {
  created: "running",
  planning: "running",
  running: "running",
  aggregating: "running",
  reporting: "running",
  awaiting_approval: "waiting_approval",
  awaiting_user_input: "waiting_user_input",
  completed: "completed",
  failed: "failed",
  cancelled: "failed",
  timed_out: "failed",
};

const RECORDED_BUDGET_FIELDS = ["tool_calls_used", "runtime_seconds_used", "active_subagents", "active_tools"];

function durationSeconds(start, end) {
  if (!start || !end) {
    return null;
  }
  const seconds = (new Date(end).getTime() - new Date(start).getTime()) / 1000;
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

function formatDuration(seconds) {
  if (seconds == null) {
    return "未记录";
  }
  if (seconds < 60) {
    return `${seconds.toFixed(1)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${(seconds % 60).toFixed(1)}s`;
}

function sortByCreatedAt(items, descending = false) {
  return [...items].sort((left, right) => {
    const delta = new Date(left.created_at || 0) - new Date(right.created_at || 0);
    return descending ? -delta : delta;
  });
}

function turnMessages(messages, turn) {
  return messages.filter((message) => message.turn_id === turn?.turn_id);
}

function userMessageForTurn(messages, turn) {
  return turnMessages(messages, turn).find((message) => message.role === "user") || null;
}

function assistantMessageForTurn(messages, turn) {
  return sortByCreatedAt(turnMessages(messages, turn).filter((message) => message.role === "assistant")).at(-1) || null;
}

function extractOrderedSteps(text) {
  if (!text) {
    return [];
  }
  const steps = [];
  for (const line of String(text).split("\n")) {
    const match = line.trim().match(/^\d+\.\s+(.*)$/);
    if (!match?.[1]) {
      continue;
    }
    const step = match[1].trim();
    if (step && !steps.includes(step)) {
      steps.push(step);
    }
  }
  return steps.slice(0, 8);
}

function buildNode(node) {
  return {
    children: [],
    block_reason: null,
    action_id: null,
    action_request: null,
    approval_id: null,
    evidence_refs: [],
    artifact_refs: [],
    retry_count: 0,
    max_retries: 1,
    planning_phase: 0,
    replanned_from_node_id: null,
    superseded_by: null,
    owner_profile_name: null,
    grant_id: null,
    is_active: node.status === "running",
    ...node,
  };
}

function buildEdges(nodes) {
  return nodes.flatMap((node) => (node.depends_on || []).map((dependency) => ({ source: dependency, target: node.node_id })));
}

function finalizedGraph(graph, source, label) {
  const nodes = (graph?.nodes || []).map((node) => ({ ...node }));
  return {
    turn_id: graph?.turn_id || null,
    planning_state: graph?.planning_state || "complete",
    graph_version: graph?.graph_version || 1,
    nodes,
    edges: buildEdges(nodes),
    ready_node_ids: nodes.filter((node) => node.status === "ready").map((node) => node.node_id),
    active_node_ids: nodes.filter((node) => node.status === "running").map((node) => node.node_id),
    completed_node_ids: nodes.filter((node) => node.status === "completed").map((node) => node.node_id),
    blocked_node_ids: nodes.filter((node) => ["waiting_approval", "waiting_user_input", "blocked"].includes(node.status)).map((node) => node.node_id),
    deprecated_node_ids: nodes.filter((node) => node.status === "deprecated").map((node) => node.node_id),
    applied_ops: graph?.applied_ops || [],
    source,
    source_label: label,
  };
}

function recordedBudgetUsage(turn) {
  const usage = turn?.budget_usage || {};
  const hasUsage = RECORDED_BUDGET_FIELDS.some((field) => Number(usage[field] || 0) > 0);
  return { usage, hasUsage };
}

export function buildInspectorGraph(turn, messages = []) {
  if (!turn) {
    return null;
  }
  if (turn.task_graph?.nodes?.length) {
    return finalizedGraph(turn.task_graph, "task_graph", "真实任务图");
  }
  const userMessage = userMessageForTurn(messages, turn);
  const assistantMessage = assistantMessageForTurn(messages, turn);
  const responseText = assistantMessage?.content || turn.final_response || turn.error_message || "";
  const nodeStatus = NODE_STATUS_BY_TURN_STATUS[turn.status] || "pending";
  const nodes = [];

  if (turnGoal(turn, userMessage)) {
    nodes.push(buildNode({
      node_id: `turn-input-${turn.turn_id}`,
      title: "收到目标",
      kind: "input",
      status: "completed",
      description: turnGoal(turn, userMessage),
      summary: compactText(turnGoal(turn, userMessage), 180),
      depends_on: [],
      metadata: {
        message_id: userMessage?.message_id || null,
        turn_id: turn.turn_id,
        created_at: userMessage?.created_at || turn.created_at,
        completed_at: userMessage?.created_at || turn.created_at,
        source: "durable_record",
      },
    }));
  }

  let previousNodeId = nodes.at(-1)?.node_id || null;
  for (const [index, step] of extractOrderedSteps(responseText).entries()) {
    const nodeId = `turn-step-${turn.turn_id}-${index + 1}`;
    nodes.push(buildNode({
      node_id: nodeId,
      title: `答复步骤 ${index + 1}`,
      kind: "aggregate",
      status: nodeStatus === "failed" ? "failed" : "completed",
      description: step,
      summary: compactText(step, 180),
      depends_on: previousNodeId ? [previousNodeId] : [],
      metadata: {
        turn_id: turn.turn_id,
        created_at: turn.created_at,
        completed_at: turn.finished_at || assistantMessage?.created_at,
        derived_from: "assistant_response",
        source: "durable_record",
      },
    }));
    previousNodeId = nodeId;
  }

  nodes.push(buildNode({
    node_id: `turn-output-${turn.turn_id}`,
    title: turn.status === "failed" ? "执行失败" : turn.status === "awaiting_approval" ? "等待确认" : turn.status === "awaiting_user_input" ? "等待补充" : "最终结果",
    kind: "report",
    status: nodeStatus,
    description: responseText || "当前没有持久化的中间执行流程记录。",
    summary: compactText(turnResultSummary(turn, assistantMessage), 220),
    depends_on: previousNodeId ? [previousNodeId] : [],
    metadata: {
      turn_id: turn.turn_id,
      message_id: assistantMessage?.message_id || null,
      created_at: turn.created_at,
      completed_at: turn.finished_at || assistantMessage?.created_at,
      derived_from: responseText ? "assistant_response" : "turn_record",
      source: "durable_record",
    },
  }));

  return finalizedGraph({ turn_id: turn.turn_id, planning_state: "complete", graph_version: 1, nodes, applied_ops: [] }, "durable_trace", "基于已保存记录重建");
}

function buildDerivedActivityEvents(turns, messages) {
  return turns.flatMap((turn) => {
    const userMessage = userMessageForTurn(messages, turn);
    const assistantMessage = assistantMessageForTurn(messages, turn);
    const responseText = assistantMessage?.content || turn.final_response || "";
    const items = [
      {
        event_id: `derived-turn-${turn.turn_id}`,
        session_id: turn.session_id,
        turn_id: turn.turn_id,
        type: "turn_recorded",
        created_at: turn.created_at,
        data: { turn_id: turn.turn_id, status: turn.status, goal: turnGoal(turn, userMessage) },
      },
    ];
    if (userMessage) {
      items.push({
        event_id: `derived-user-${userMessage.message_id}`,
        session_id: turn.session_id,
        turn_id: turn.turn_id,
        type: "user_task_recorded",
        created_at: userMessage.created_at,
        data: { message_id: userMessage.message_id, goal: compactText(userMessage.content, 240) },
      });
    }
    if (assistantMessage) {
      items.push({
        event_id: `derived-assistant-${assistantMessage.message_id}`,
        session_id: turn.session_id,
        turn_id: turn.turn_id,
        type: "assistant_response_recorded",
        created_at: assistantMessage.created_at,
        data: { message_id: assistantMessage.message_id, preview: compactText(assistantMessage.content, 240), response_chars: assistantMessage.content.length },
      });
    }
    if (turn.finished_at) {
      items.push({
        event_id: `derived-finish-${turn.turn_id}`,
        session_id: turn.session_id,
        turn_id: turn.turn_id,
        type: "turn_terminal_recorded",
        created_at: turn.finished_at,
        data: {
          status: turn.status,
          duration_seconds: durationSeconds(turn.created_at, turn.finished_at),
          response_chars: responseText.length,
          evidence_count: (turn.evidence_ids || []).length,
          artifact_count: (turn.artifact_ids || []).length,
          approval_count: (turn.approval_ids || []).length,
        },
      });
    }
    return items;
  });
}

export function buildInspectorActivityEvents(events = [], turns = [], messages = [], focusTurnId = null) {
  const scopedEvents = focusTurnId ? events.filter((item) => !item.turn_id || item.turn_id === focusTurnId) : events;
  const derivedEvents = focusTurnId
    ? buildDerivedActivityEvents(turns.filter((item) => item.turn_id === focusTurnId), messages)
    : buildDerivedActivityEvents(turns, messages);
  return [...scopedEvents, ...derivedEvents].sort((left, right) => new Date(right.created_at || 0) - new Date(left.created_at || 0));
}

export function buildTurnInspectorStats(turn, messages = [], activityEvents = [], graph = null) {
  if (!turn) {
    return null;
  }
  const assistantMessage = assistantMessageForTurn(messages, turn);
  const responseText = assistantMessage?.content || turn.final_response || turn.error_message || "";
  const { usage, hasUsage } = recordedBudgetUsage(turn);
  return {
    durationLabel: formatDuration(durationSeconds(turn.created_at, turn.finished_at)),
    responseChars: responseText.length,
    eventCount: activityEvents.filter((item) => !item.turn_id || item.turn_id === turn.turn_id).length,
    nodeCount: graph?.nodes?.length || 0,
    graphSourceLabel: graph?.source_label || "无",
    evidenceCount: (turn.evidence_ids || []).length,
    artifactCount: (turn.artifact_ids || []).length,
    approvalCount: (turn.approval_ids || []).length,
    hasRecordedBudgetUsage: hasUsage,
    budgetUsage: usage,
    budgetMax: turn.budget || { max_tool_calls: 0, max_runtime_seconds: 0, max_parallel_subagents: 0, max_parallel_tools: 0 },
  };
}
