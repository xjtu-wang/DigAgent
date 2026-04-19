import { compactText } from "./chat-utils.js";
import { eventSummary, systemEventLabels } from "./timeline-utils.js";
import { turnGoal, turnRecentActionSummary, turnResultSummary, turnStatusLabel, turnTargetSummary } from "./turn-utils.js";

const KEY_CHAT_EVENT_TYPES = new Set(["approval_required", "approval_expired", "approval_superseded"]);
const WORKFLOW_EVENT_TYPES = new Set(["assistant_chunk", "plan", "task_node_started", "task_node_completed", "task_node_waiting_approval", "task_node_waiting_user_input", "graph_op_applied", "aggregate"]);
const TYPE_ORDER = { local_user: 0, turn_card: 1, approval_required: 2, approval_superseded: 3, approval_expired: 4, assistant_message: 5 };
const TOOL_EVENT_TYPES = new Set(["langgraph_tasks", "tool_result"]);

const asArray = (value) => (Array.isArray(value) ? value : []);
const asObject = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : {});

function parseJson(value) {
  if (typeof value !== "string") return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function byCreated(left, right) {
  return new Date(left?.created_at || 0) - new Date(right?.created_at || 0);
}

function groupByTurn(items) {
  const grouped = new Map();
  for (const item of items) {
    if (!item?.turn_id) continue;
    const bucket = grouped.get(item.turn_id) || [];
    bucket.push(item);
    grouped.set(item.turn_id, bucket);
  }
  return grouped;
}

function compareTimeline(left, right) {
  const timeDelta = byCreated(left, right);
  if (timeDelta !== 0) return timeDelta;
  const weightDelta = (TYPE_ORDER[left.type] ?? 10) - (TYPE_ORDER[right.type] ?? 10);
  return weightDelta || String(left.event_id || "").localeCompare(String(right.event_id || ""));
}

function messageEntry(message) {
  return {
    event_id: `msg-${message.message_id}`,
    session_id: message.session_id,
    turn_id: message.turn_id || null,
    type: message.role === "user" ? "local_user" : "assistant_message",
    created_at: message.created_at,
    data: { message: message.content, message_id: message.message_id, evidence_refs: message.evidence_refs || [], artifact_refs: message.artifact_refs || [] },
  };
}

function safeHost(value) {
  if (!value) return "";
  try {
    return new URL(value).host;
  } catch {
    return "";
  }
}

function uniqueChips(values, limit = 4) {
  const chips = [];
  for (const value of values) {
    const text = typeof value === "string" ? value.trim() : "";
    if (!text || chips.includes(text)) continue;
    chips.push(text);
    if (chips.length >= limit) break;
  }
  return chips;
}

function withEventMeta(card, event) {
  return { ...card, created_at: card.created_at || event.created_at, last_event_at: event.created_at };
}

function upsertToolCard(cards, cardId, event, patch) {
  const current = cards.get(cardId) || {};
  cards.set(cardId, withEventMeta({ ...current, ...patch }, event));
}

function registerToolCalls(cards, event) {
  const payload = asObject(event?.data?.payload);
  for (const message of asArray(asObject(payload.result).messages)) {
    for (const toolCall of asArray(message?.tool_calls)) {
      const cardId = toolCall.id || `${payload.id || event.event_id}-${toolCall.name || "tool"}`;
      const current = cards.get(cardId) || {};
      upsertToolCard(cards, cardId, event, {
        tool_call_id: cardId,
        tool_name: toolCall.name || current.tool_name || "tool",
        title: current.title || `工具调用 · ${toolCall.name || "tool"}`,
        summary: current.summary || compactText(message.content || "", 180),
        request_message: current.request_message || String(message.content || ""),
        call_args: asObject(toolCall.args),
      });
    }
  }
}

function registerToolResults(cards, event) {
  const payload = asObject(event?.data?.payload);
  for (const message of asArray(asObject(payload.result).messages)) {
    if (message?.type !== "tool") continue;
    const cardId = message.tool_call_id || `${payload.id || event.event_id}-${message.name || "tool"}`;
    const current = cards.get(cardId) || {};
    const parsed = parseJson(message.content);
    const rawOutput = parsed?.raw_output || current.raw_output || null;
    const rawOutputObject = parseJson(rawOutput);
    upsertToolCard(cards, cardId, event, {
      tool_call_id: cardId,
      tool_name: message.name || current.tool_name || parsed?.source?.tool_name || "tool",
      title: parsed?.title || current.title || `工具结果 · ${message.name || "tool"}`,
      summary: parsed?.summary || current.summary || compactText(message.content, 180),
      tool_status: message.status || current.tool_status || "unknown",
      source_url: parsed?.source?.url || rawOutputObject?.url || current.source_url || null,
      facts: asArray(parsed?.facts),
      call_args: current.call_args || {},
      body_excerpt: rawOutputObject?.body_excerpt || null,
      raw_output: rawOutput,
      raw_output_object: rawOutputObject,
      raw_message: message,
    });
  }
}

function toolCards(turnEvents) {
  const cards = new Map();
  for (const event of turnEvents) {
    if (event.type === "tool_result") {
      const data = asObject(event.data);
      const cardId = String(data.tool_call_id || event.event_id);
      const current = cards.get(cardId) || {};
      upsertToolCard(cards, cardId, event, {
        tool_call_id: cardId,
        tool_name: data.tool_name || current.tool_name || "tool",
        title: data.title || current.title || `工具结果 · ${data.tool_name || "tool"}`,
        summary: data.summary || current.summary || "",
        tool_status: data.status || current.tool_status || "success",
        source_url: data.source_url || current.source_url || null,
        call_args: asObject(data.arguments),
        raw_output: data.raw_output || current.raw_output || null,
      });
      continue;
    }
    if (event.type !== "langgraph_tasks") continue;
    const payload = asObject(event?.data?.payload);
    if (payload.name === "model") registerToolCalls(cards, event);
    if (payload.name === "tools") registerToolResults(cards, event);
  }
  return [...cards.values()]
    .filter((card) => card.summary || card.raw_output || card.request_message)
    .sort(byCreated)
    .map((card) => ({
      ...card,
      summary: compactText(card.summary || card.request_message || card.body_excerpt || "暂无工具摘要。", 180),
      chips: uniqueChips([card.tool_status || "", safeHost(card.source_url), card.facts?.length ? `${card.facts.length} 条事实` : "", Object.keys(asObject(card.call_args)).length ? `${Object.keys(asObject(card.call_args)).length} 个参数` : ""]),
    }));
}

function eventItem(event) {
  const data = asObject(event.data);
  return {
    event_id: event.event_id,
    type: event.type,
    created_at: event.created_at,
    title: systemEventLabels[event.type] || event.type,
    summary: compactText(eventSummary(event), 220),
    chips: uniqueChips([data.status ? String(data.status) : "", data.node_id ? String(data.node_id) : "", data.approval_id ? String(data.approval_id) : "", data.report_id ? String(data.report_id) : "", data.evidence_id ? String(data.evidence_id) : ""], 3),
  };
}

function workflowItems(turnEvents) {
  const items = [];
  const chunks = turnEvents.filter((event) => event.type === "assistant_chunk");
  const detail = chunks.map((item) => item.data?.text || "").join("");
  if (detail.trim()) {
    items.push({ event_id: `assistant-process-${chunks[0].turn_id || "turn"}`, type: "assistant_chunk", created_at: chunks[0].created_at, title: "执行过程", summary: compactText(detail, 220), detail, chips: [`${chunks.length} 段`] });
  }
  return [...items, ...turnEvents.filter((event) => event.type !== "assistant_chunk" && WORKFLOW_EVENT_TYPES.has(event.type)).map(eventItem)];
}

function activityItems(turnEvents) {
  return turnEvents.filter((event) => !WORKFLOW_EVENT_TYPES.has(event.type) && !TOOL_EVENT_TYPES.has(event.type)).map(eventItem);
}

function buildDebug(tools, turn, messages, events) {
  return {
    turn,
    messages,
    recent_events: events.slice(-10),
    tool_calls: tools.map((tool) => ({
      tool_call_id: tool.tool_call_id,
      tool_name: tool.tool_name,
      title: tool.title,
      request_message: tool.request_message || "",
      call_args: tool.call_args || {},
      raw_message: tool.raw_message || null,
      raw_output: tool.raw_output || null,
      raw_output_object: tool.raw_output_object || null,
    })),
  };
}

function turnCard(turn, turnMessages, turnEvents) {
  const orderedMessages = [...turnMessages].sort(byCreated);
  const orderedEvents = turnEvents.map((event) => ({ ...event, data: asObject(event.data) })).sort(byCreated);
  const userMessages = orderedMessages.filter((item) => item.role === "user");
  const assistantMessage = orderedMessages.filter((item) => item.role === "assistant").at(-1) || null;
  const workflow = workflowItems(orderedEvents);
  const tools = toolCards(orderedEvents);
  const activity = activityItems(orderedEvents);
  return {
    event_id: `turn-${turn.turn_id}`,
    session_id: turn.session_id,
    turn_id: turn.turn_id,
    type: "turn_card",
    created_at: userMessages[0]?.created_at || turn.created_at || orderedEvents[0]?.created_at || assistantMessage?.created_at || turn.updated_at,
    data: {
      turn_id: turn.turn_id,
      status: turn.status,
      status_label: turnStatusLabel(turn.status),
      goal: turnGoal(turn, userMessages[0] || null),
      target: turnTargetSummary(turn),
      action_summary: turnRecentActionSummary(turn, orderedEvents),
      result_summary: turnResultSummary(turn, assistantMessage, orderedEvents),
      workflow: { count: workflow.length, items: workflow },
      tools: { count: tools.length, items: tools },
      activity: { count: activity.length, items: activity },
      semantic_action_count: workflow.length + tools.length + activity.length,
      raw_event_count: orderedEvents.length,
      tool_count: tools.length,
      approval_count: Math.max(asArray(turn.pending_approvals).length, asArray(turn.approval_ids).length),
      evidence_count: asArray(turn.evidence_ids).length,
      artifact_count: asArray(turn.artifact_ids).length,
      report_id: turn.report_id || null,
      debug: buildDebug(tools, turn, orderedMessages, orderedEvents),
    },
  };
}

function buildTurnItems(turn, turnMessages, turnEvents) {
  const items = turnMessages.filter((message) => message.role === "user").sort(byCreated).map(messageEntry);
  items.push(turnCard(turn, turnMessages, turnEvents));
  const assistantMessage = turnMessages.filter((message) => message.role === "assistant").sort(byCreated).at(-1);
  if (assistantMessage) items.push(messageEntry(assistantMessage));
  return items;
}

export function buildPrimaryTimeline(messages, events, turns, showKeySystemCards = true) {
  const messagesByTurn = groupByTurn(messages);
  const eventsByTurn = groupByTurn(events);
  const standaloneMessages = asArray(messages).filter((message) => !message.turn_id).map(messageEntry);
  const turnItems = asArray(turns).sort(byCreated).flatMap((turn) => buildTurnItems(turn, messagesByTurn.get(turn.turn_id) || [], eventsByTurn.get(turn.turn_id) || []));
  const keySystemCards = showKeySystemCards ? asArray(events).filter((event) => KEY_CHAT_EVENT_TYPES.has(event.type)).map((event) => ({ ...event, data: asObject(event.data) })) : [];
  return [...standaloneMessages, ...turnItems, ...keySystemCards].sort(compareTimeline);
}
