import { compactText } from "./chat-utils.js";

const KEY_CHAT_EVENT_TYPES = new Set([
  "approval_required",
  "approval_expired",
  "approval_superseded",
]);

const TYPE_ORDER = {
  local_user: 0,
  approval_required: 1,
  approval_superseded: 1,
  approval_expired: 1,
  assistant_process: 2,
  tool_summary_card: 3,
  assistant_message: 4,
  turn_summary_card: 5,
};

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

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function compareTimeline(left, right) {
  const timeDelta = new Date(left.created_at || 0) - new Date(right.created_at || 0);
  if (timeDelta !== 0) {
    return timeDelta;
  }
  const leftWeight = TYPE_ORDER[left.type] ?? 10;
  const rightWeight = TYPE_ORDER[right.type] ?? 10;
  if (leftWeight !== rightWeight) {
    return leftWeight - rightWeight;
  }
  return String(left.event_id || "").localeCompare(String(right.event_id || ""));
}

function parseJson(value) {
  if (typeof value !== "string") {
    return null;
  }
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
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

function firstMessage(messages, role) {
  return messages.find((item) => item.role === role) || null;
}

function lastMessage(messages, role) {
  return messages.filter((item) => item.role === role).at(-1) || null;
}

function normalizeToolCard(card, event) {
  return {
    ...card,
    created_at: card.created_at || event.created_at,
    last_event_at: event.created_at,
  };
}

function registerToolCalls(cards, event) {
  const payload = asObject(event?.data?.payload);
  const taskResult = asObject(payload.result);
  const messages = asArray(taskResult.messages);
  for (const message of messages) {
    const toolCalls = asArray(message?.tool_calls);
    for (const toolCall of toolCalls) {
      const cardId = toolCall.id || `${payload.id || event.event_id}-${toolCall.name || "tool"}`;
      const current = cards.get(cardId) || {};
      cards.set(cardId, normalizeToolCard({
        ...current,
        tool_call_id: cardId,
        tool_name: toolCall.name || current.tool_name || "tool",
        title: current.title || `工具调用 · ${toolCall.name || "tool"}`,
        summary: current.summary || (message.content ? compactText(message.content, 220) : ""),
        request_message: current.request_message || String(message.content || ""),
        call_args: asObject(toolCall.args),
      }, event));
    }
  }
}

function registerToolResults(cards, event) {
  const payload = asObject(event?.data?.payload);
  const taskResult = asObject(payload.result);
  const messages = asArray(taskResult.messages);
  for (const message of messages) {
    if (message?.type !== "tool") {
      continue;
    }
    const cardId = message.tool_call_id || `${payload.id || event.event_id}-${message.name || "tool"}`;
    const current = cards.get(cardId) || {};
    const parsed = parseJson(message.content);
    const rawOutput = parsed?.raw_output || null;
    const rawOutputObject = parseJson(rawOutput);
    cards.set(cardId, normalizeToolCard({
      ...current,
      tool_call_id: cardId,
      tool_name: message.name || current.tool_name || parsed?.source?.tool_name || "tool",
      title: parsed?.title || current.title || `工具结果 · ${message.name || "tool"}`,
      summary: parsed?.summary || current.summary || compactText(message.content, 220),
      tool_status: message.status || "unknown",
      source_url: parsed?.source?.url || rawOutputObject?.url || null,
      facts: asArray(parsed?.facts),
      call_args: current.call_args || {},
      body_excerpt: rawOutputObject?.body_excerpt || null,
      raw_output: rawOutput,
      raw_output_object: rawOutputObject,
      raw_message: message,
    }, event));
  }
}

function extractToolCards(turnEvents) {
  const cards = new Map();
  for (const event of turnEvents) {
    if (event.type === "tool_result") {
      const data = asObject(event.data);
      const cardId = String(data.tool_call_id || event.event_id);
      const current = cards.get(cardId) || {};
      cards.set(cardId, normalizeToolCard({
        ...current,
        tool_call_id: cardId,
        tool_name: data.tool_name || current.tool_name || "tool",
        title: data.title || current.title || `工具结果 · ${data.tool_name || "tool"}`,
        summary: data.summary || current.summary || "",
        raw_output: data.raw_output || current.raw_output || null,
        call_args: asObject(data.arguments),
      }, event));
      continue;
    }
    if (event.type !== "langgraph_tasks") {
      continue;
    }
    const payload = asObject(event?.data?.payload);
    if (payload.name === "model") {
      registerToolCalls(cards, event);
      continue;
    }
    if (payload.name === "tools") {
      registerToolResults(cards, event);
    }
  }
  return [...cards.values()]
    .filter((card) => card.summary || card.raw_output || card.request_message)
    .sort((left, right) => new Date(left.created_at || 0) - new Date(right.created_at || 0));
}

function buildProcessItem(turn, chunks) {
  if (!chunks.length) {
    return null;
  }
  const content = chunks.map((item) => item.data?.text || "").join("");
  if (!content.trim()) {
    return null;
  }
  return {
    event_id: `process-${turn.turn_id}`,
    session_id: turn.session_id,
    turn_id: turn.turn_id,
    type: "assistant_process",
    created_at: chunks[0].created_at,
    data: {
      title: "执行过程",
      message: content,
      preview: compactText(content, 220),
      chunk_count: chunks.length,
    },
  };
}

function buildToolItems(turn, toolCards) {
  return toolCards.map((card, index) => ({
    event_id: `tool-${turn.turn_id}-${card.tool_call_id || index}`,
    session_id: turn.session_id,
    turn_id: turn.turn_id,
    type: "tool_summary_card",
    created_at: card.created_at,
    data: {
      tool_name: card.tool_name,
      title: card.title,
      summary: card.summary,
      status: card.tool_status || "success",
      source_url: card.source_url,
      facts: card.facts || [],
      call_args: card.call_args || {},
      request_message: card.request_message || "",
      body_excerpt: card.body_excerpt,
      raw_output: card.raw_output,
      raw_output_object: card.raw_output_object,
      raw_message: card.raw_message || null,
    },
  }));
}

function buildTurnSummaryItem(turn, assistantMessage, toolCards, turnEvents) {
  const semanticActionCount = toolCards.length
    + turnEvents.filter((event) => KEY_CHAT_EVENT_TYPES.has(event.type)).length
    + (assistantMessage ? 1 : 0);
  return {
    event_id: `turn-summary-${turn.turn_id}`,
    session_id: turn.session_id,
    turn_id: turn.turn_id,
    type: "turn_summary_card",
    created_at: assistantMessage?.created_at || turn.finished_at || turn.updated_at || turn.created_at,
    data: {
      turn_id: turn.turn_id,
      status: turn.status,
      status_label: STATUS_LABELS[turn.status] || String(turn.status || "unknown"),
      event_count: semanticActionCount,
      semantic_action_count: semanticActionCount,
      raw_event_count: turnEvents.length,
      tool_count: toolCards.length,
      approval_count: asArray(turn.approval_ids).length,
      evidence_count: asArray(turn.evidence_ids).length,
      artifact_count: asArray(turn.artifact_ids).length,
      report_id: turn.report_id || null,
      result_summary: compactText(assistantMessage?.content || turn.final_response || turn.error_message || "", 220),
    },
  };
}

function buildTurnItems(turn, turnMessages, turnEvents) {
  const orderedMessages = [...turnMessages].sort((left, right) => new Date(left.created_at || 0) - new Date(right.created_at || 0));
  const userMessages = orderedMessages
    .filter((item) => item.role === "user")
    .map((message) => ({
      event_id: `msg-${message.message_id}`,
      session_id: message.session_id,
      turn_id: message.turn_id,
      type: "local_user",
      created_at: message.created_at,
      data: { message: message.content, message_id: message.message_id, evidence_refs: message.evidence_refs || [], artifact_refs: message.artifact_refs || [] },
    }));
  const assistantMessage = lastMessage(orderedMessages, "assistant");
  const processItem = buildProcessItem(turn, turnEvents.filter((event) => event.type === "assistant_chunk"));
  const toolCards = extractToolCards(turnEvents);
  const items = [
    ...userMessages,
    ...(processItem ? [processItem] : []),
    ...buildToolItems(turn, toolCards),
  ];
  if (assistantMessage) {
    items.push({
      event_id: `msg-${assistantMessage.message_id}`,
      session_id: assistantMessage.session_id,
      turn_id: assistantMessage.turn_id,
      type: "assistant_message",
      created_at: assistantMessage.created_at,
      data: { message: assistantMessage.content, message_id: assistantMessage.message_id, evidence_refs: assistantMessage.evidence_refs || [], artifact_refs: assistantMessage.artifact_refs || [] },
    });
  }
  if (items.length || turn.status !== "completed") {
    items.push(buildTurnSummaryItem(turn, assistantMessage, toolCards, turnEvents));
  }
  return items;
}

export function buildPrimaryTimeline(messages, events, turns, showKeySystemCards = true) {
  const standaloneMessages = asArray(messages)
    .filter((message) => !message.turn_id)
    .map((message) => ({
      event_id: `msg-${message.message_id}`,
      session_id: message.session_id,
      turn_id: null,
      type: message.role === "user" ? "local_user" : "assistant_message",
      created_at: message.created_at,
      data: { message: message.content, message_id: message.message_id, evidence_refs: message.evidence_refs || [], artifact_refs: message.artifact_refs || [] },
    }));
  const messagesByTurn = groupByTurn(messages);
  const eventsByTurn = groupByTurn(events);
  const turnItems = [...asArray(turns)]
    .sort((left, right) => new Date(left.created_at || 0) - new Date(right.created_at || 0))
    .flatMap((turn) => buildTurnItems(turn, messagesByTurn.get(turn.turn_id) || [], eventsByTurn.get(turn.turn_id) || []));
  const keySystemCards = showKeySystemCards
    ? asArray(events)
      .filter((event) => KEY_CHAT_EVENT_TYPES.has(event.type))
      .map((event) => ({ ...event, data: asObject(event.data) }))
    : [];
  return [...standaloneMessages, ...turnItems, ...keySystemCards].sort(compareTimeline);
}
