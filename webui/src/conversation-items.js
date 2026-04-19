import { compactText } from "./chat-utils.js";

const ACTION_LABEL = "执行动作";
const APPROVAL_EVENT_TYPES = new Set(["approval_required"]);
const NOTICE_EVENT_TYPES = new Set(["approval_expired", "approval_superseded", "awaiting_user_input", "failed", "timed_out", "cancelled"]);
export const PRIMARY_CONVERSATION_ITEM_TYPES = new Set([
  "user_message",
  "assistant_process",
  "tool_action",
  "tool_observation",
  "participant_handoff",
  "participant_message",
  "assistant_message",
]);
export const KEY_SYSTEM_CONVERSATION_ITEM_TYPES = new Set([
  "approval_required",
  "approval_request",
  "system_notice",
]);
const TYPE_ORDER = {
  user_message: 0,
  assistant_process: 1,
  participant_handoff: 2,
  tool_action: 3,
  tool_observation: 4,
  approval_required: 5,
  approval_request: 5,
  participant_message: 6,
  assistant_message: 7,
  system_notice: 8,
};
const DEFAULT_OPTIONS = Object.freeze({
  activeTurnId: null,
  showKeySystemCards: true,
});

const asArray = (value) => (Array.isArray(value) ? value : []);
const asObject = (value) => (value && typeof value === "object" && !Array.isArray(value) ? value : {});

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

function safeHost(value) {
  if (!value) {
    return "";
  }
  try {
    return new URL(value).host;
  } catch {
    return "";
  }
}

function uniqueList(values) {
  return [...new Set(values.filter(Boolean).map(String))];
}

function normalizeSpeaker(value, fallback = null) {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return fallback;
}

function buildMessageItem(message) {
  const addressedParticipants = uniqueList([
    ...asArray(message.addressed_participants),
    ...asArray(message.mentions),
  ]);
  return {
    event_id: `msg-${message.message_id}`,
    session_id: message.session_id,
    turn_id: message.turn_id || null,
    type: message.role === "user" ? "user_message" : "assistant_message",
    created_at: message.created_at,
    data: {
      message: message.content,
      markdown: message.content,
      message_id: message.message_id,
      speaker_profile: normalizeSpeaker(message.speaker_profile, message.role === "assistant" ? "assistant" : "user"),
      addressed_participants: addressedParticipants,
      evidence_refs: message.evidence_refs || [],
      artifact_refs: message.artifact_refs || [],
    },
  };
}

function numericValue(value) {
  return Number.isFinite(value) ? value : null;
}

function compareEventSequence(left, right) {
  const leftSessionOrder = numericValue(left?._eventSourceOrder);
  const rightSessionOrder = numericValue(right?._eventSourceOrder);
  if (leftSessionOrder != null && rightSessionOrder != null && leftSessionOrder !== rightSessionOrder) {
    return leftSessionOrder - rightSessionOrder;
  }
  const leftSuborder = numericValue(left?._eventSuborder) ?? 0;
  const rightSuborder = numericValue(right?._eventSuborder) ?? 0;
  if (leftSessionOrder != null && rightSessionOrder != null && leftSuborder !== rightSuborder) {
    return leftSuborder - rightSuborder;
  }
  return 0;
}

function compareToolCausality(left, right) {
  const leftToolCallId = left?.data?.tool_call_id;
  const rightToolCallId = right?.data?.tool_call_id;
  if (!leftToolCallId || !rightToolCallId || leftToolCallId !== rightToolCallId) {
    return 0;
  }
  if (left.type === "tool_action" && right.type === "tool_observation") {
    return -1;
  }
  if (left.type === "tool_observation" && right.type === "tool_action") {
    return 1;
  }
  return 0;
}

function compareConversationItems(left, right) {
  const causalDelta = compareToolCausality(left, right);
  if (causalDelta !== 0) {
    return causalDelta;
  }
  const eventDelta = compareEventSequence(left, right);
  if (eventDelta !== 0) {
    return eventDelta;
  }
  const timeDelta = new Date(left?.created_at || 0) - new Date(right?.created_at || 0);
  if (timeDelta !== 0) {
    return timeDelta;
  }
  const typeDelta = (TYPE_ORDER[left.type] ?? 20) - (TYPE_ORDER[right.type] ?? 20);
  if (typeDelta !== 0) {
    return typeDelta;
  }
  return String(left.event_id || "").localeCompare(String(right.event_id || ""));
}

function compareRawEvents(left, right) {
  const leftSessionOrder = numericValue(left?.session_event_index);
  const rightSessionOrder = numericValue(right?.session_event_index);
  if (leftSessionOrder != null && rightSessionOrder != null && leftSessionOrder !== rightSessionOrder) {
    return leftSessionOrder - rightSessionOrder;
  }
  const timeDelta = new Date(left?.created_at || 0) - new Date(right?.created_at || 0);
  if (timeDelta !== 0) {
    return timeDelta;
  }
  const leftTurnOrder = numericValue(left?.turn_event_index);
  const rightTurnOrder = numericValue(right?.turn_event_index);
  if (leftTurnOrder != null && rightTurnOrder != null && leftTurnOrder !== rightTurnOrder) {
    return leftTurnOrder - rightTurnOrder;
  }
  const inputDelta = (left?._inputOrder ?? 0) - (right?._inputOrder ?? 0);
  if (inputDelta !== 0) {
    return inputDelta;
  }
  return String(left?.event_id || "").localeCompare(String(right?.event_id || ""));
}

function normalizeOptions(options) {
  if (typeof options === "boolean") {
    return {
      ...DEFAULT_OPTIONS,
      showKeySystemCards: options,
    };
  }
  return {
    ...DEFAULT_OPTIONS,
    ...(options || {}),
  };
}

function eventTurnId(event) {
  return event?.turn_id || event?.data?.turn_id || null;
}

function speakerKey(event) {
  return normalizeSpeaker(
    event?.data?.speaker_profile
      || event?.speaker_profile
      || event?.data?.participant_profile
      || event?.participant_profile,
    "assistant",
  );
}

function buildTurnMetadata(messages, events, options) {
  const turnMap = new Map();
  for (const message of asArray(messages)) {
    if (!message?.turn_id) {
      continue;
    }
    const current = turnMap.get(message.turn_id) || { hasAssistantMessage: false, hasVisibleProcess: false };
    if (message.role === "assistant") {
      current.hasAssistantMessage = true;
    }
    turnMap.set(message.turn_id, current);
  }
  for (const event of asArray(events)) {
    const turnId = eventTurnId(event);
    if (!turnId || event.type === "assistant_chunk") {
      continue;
    }
    const current = turnMap.get(turnId) || { hasAssistantMessage: false, hasVisibleProcess: false };
    if (event.type === "langgraph_tasks") {
      current.hasVisibleProcess = buildLanggraphToolItems({ ...event, data: asObject(event.data) }).length > 0 || current.hasVisibleProcess;
      turnMap.set(turnId, current);
      continue;
    }
    if (event.type === "tool_result" || event.type === "participant_handoff" || event.type === "participant_message" || event.type === "subagent") {
      current.hasVisibleProcess = true;
      turnMap.set(turnId, current);
      continue;
    }
    if ((APPROVAL_EVENT_TYPES.has(event.type) || NOTICE_EVENT_TYPES.has(event.type)) && options.showKeySystemCards) {
      current.hasVisibleProcess = true;
      turnMap.set(turnId, current);
    }
  }
  return turnMap;
}

function shouldKeepChunkGroup(chunkBuffer, turnMetadata, options) {
  if (!chunkBuffer.length) {
    return false;
  }
  const turnId = eventTurnId(chunkBuffer[0]);
  if (!turnId) {
    return true;
  }
  if (options.activeTurnId && turnId === options.activeTurnId) {
    return true;
  }
  const metadata = turnMetadata.get(turnId);
  if (!metadata?.hasAssistantMessage) {
    return true;
  }
  return Boolean(metadata.hasVisibleProcess);
}

function splitParagraphs(text) {
  return String(text || "")
    .split(/\n\s*\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function eventSourceOrder(event, fallbackOrder = null) {
  return numericValue(event?.session_event_index)
    ?? numericValue(event?.turn_event_index)
    ?? numericValue(event?._orderedEventIndex)
    ?? numericValue(event?._inputOrder)
    ?? fallbackOrder;
}

function flushThoughtChunks(items, chunkBuffer, turnMetadata, options) {
  if (!chunkBuffer.length) {
    return;
  }
  const text = chunkBuffer.map((item) => String(item.data?.text || "")).join("").trim();
  if (!text || !shouldKeepChunkGroup(chunkBuffer, turnMetadata, options)) {
    chunkBuffer.length = 0;
    return;
  }
  const first = chunkBuffer[0];
  const paragraphs = splitParagraphs(text);
  for (const [index, paragraph] of paragraphs.entries()) {
    items.push({
      event_id: `process-${first.event_id}-${index + 1}`,
      session_id: first.session_id,
      turn_id: first.turn_id || null,
      type: "assistant_process",
      created_at: first.created_at,
      _eventSourceOrder: eventSourceOrder(first),
      _eventSuborder: index,
      data: {
        title: "过程输出",
        summary: compactText(paragraph, 180),
        detail: paragraph,
        speaker_profile: normalizeSpeaker(first.data?.speaker_profile || first.data?.participant_profile, "assistant"),
      },
    });
  }
  chunkBuffer.length = 0;
}

function buildActionItem(event, toolCall, requestMessage, suborder = 0) {
  const callArgs = asObject(toolCall?.args);
  const argKeys = Object.keys(callArgs);
  return {
    event_id: `tool-action-${toolCall.id || event.event_id}`,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "tool_action",
    created_at: event.created_at,
    _eventSourceOrder: eventSourceOrder(event),
    _eventSuborder: suborder,
    data: {
      tool_call_id: toolCall.id || event.event_id,
      tool_name: toolCall.name || "tool",
      title: `${ACTION_LABEL} · ${toolCall.name || "tool"}`,
      summary: compactText(requestMessage || `调用 ${toolCall.name || "tool"}`, 180),
      arguments: callArgs,
      detail: argKeys.length ? JSON.stringify(callArgs, null, 2) : "",
      argument_count: argKeys.length,
    },
  };
}

function buildObservationItem(event, message, parsed, suborder = 0) {
  const toolName = message?.name || parsed?.source?.tool_name || "tool";
  const rawOutput = parseJson(parsed?.raw_output);
  const sourceUrl = parsed?.source?.url || rawOutput?.url || null;
  const detail = typeof parsed?.raw_output === "string"
    ? parsed.raw_output
    : typeof message?.content === "string"
      ? message.content
      : "";
  return {
    event_id: `tool-observation-${message?.tool_call_id || event.event_id}`,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "tool_observation",
    created_at: event.created_at,
    _eventSourceOrder: eventSourceOrder(event),
    _eventSuborder: suborder,
    data: {
      tool_call_id: message?.tool_call_id || event.event_id,
      tool_name: toolName,
      title: parsed?.title || `观察结果 · ${toolName}`,
      summary: compactText(parsed?.summary || message?.content || "工具返回了观察结果。", 180),
      status: message?.status || "success",
      source_url: sourceUrl,
      detail,
      facts: asArray(parsed?.facts).slice(0, 4),
      source_host: safeHost(sourceUrl),
    },
  };
}

function buildLanggraphToolItems(event) {
  const items = [];
  const payload = asObject(event.data?.payload);
  const result = asObject(payload.result);
  const messages = asArray(result.messages);
  if (payload.name === "model") {
    for (const message of messages) {
      const requestMessage = typeof message?.content === "string" ? message.content : "";
      for (const [index, toolCall] of asArray(message?.tool_calls).entries()) {
        items.push(buildActionItem(event, toolCall, requestMessage, index));
      }
    }
  }
  if (payload.name === "tools") {
    for (const [index, message] of messages.entries()) {
      if (message?.type !== "tool") {
        continue;
      }
      const parsed = parseJson(message.content) || {};
      items.push(buildObservationItem(event, message, parsed, index));
    }
  }
  return items;
}

function buildDirectToolObservation(event) {
  const data = asObject(event.data);
  return {
    event_id: `tool-observation-${event.event_id}`,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "tool_observation",
    created_at: event.created_at,
    _eventSourceOrder: eventSourceOrder(event),
    _eventSuborder: 0,
    data: {
      tool_call_id: data.tool_call_id || event.event_id,
      tool_name: data.tool_name || "tool",
      title: data.title || `观察结果 · ${data.tool_name || "tool"}`,
      summary: compactText(data.summary || "工具返回了观察结果。", 180),
      status: data.status || "success",
      source_url: data.source_url || null,
      detail: data.detail || data.raw_output || "",
      facts: asArray(data.facts).slice(0, 4),
      source_host: safeHost(data.source_url),
    },
  };
}

function buildParticipantItem(event) {
  const data = asObject(event.data);
  if (event.type === "participant_handoff") {
    return {
      event_id: event.event_id,
      session_id: event.session_id,
      turn_id: event.turn_id || null,
      type: "participant_handoff",
      created_at: event.created_at,
      _eventSourceOrder: eventSourceOrder(event),
      _eventSuborder: 0,
      data: {
        handoff_from: data.handoff_from || "assistant",
        handoff_to: data.handoff_to || data.participant_profile || "agent",
        summary: compactText(data.summary || `${data.handoff_from || "assistant"} 正在交给 ${data.handoff_to || data.participant_profile || "agent"}`, 180),
      },
    };
  }
  const participantProfile = data.participant_profile || data.delegatee_profile_name || data.speaker_profile || "agent";
  return {
    event_id: event.event_id,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "participant_message",
    created_at: event.created_at,
    _eventSourceOrder: eventSourceOrder(event),
    _eventSuborder: 0,
    data: {
      participant_profile: participantProfile,
      message: data.message || data.summary || data.result?.summary || data.task?.goal || "",
      markdown: data.message || data.summary || data.result?.summary || data.task?.goal || "",
      summary: compactText(data.summary || data.result?.summary || data.task?.goal || "参与者返回了阶段结果。", 180),
      speaker_profile: participantProfile,
    },
  };
}

function buildApprovalItem(event) {
  return {
    event_id: event.event_id,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "approval_required",
    created_at: event.created_at,
    _eventSourceOrder: eventSourceOrder(event),
    _eventSuborder: 0,
    data: asObject(event.data),
  };
}

function buildNoticeItem(event) {
  const data = asObject(event.data);
  return {
    event_id: event.event_id,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "system_notice",
    created_at: event.created_at,
    _eventSourceOrder: eventSourceOrder(event),
    _eventSuborder: 0,
    data: {
      title: event.type,
      severity: ["failed", "timed_out", "approval_expired"].includes(event.type) ? "error" : "info",
      summary: compactText(data.summary || data.error || data.reason || data.prompt || data.question || event.type, 180),
    },
  };
}

function buildVisibleEventItems(event, options) {
  const normalized = { ...event, data: asObject(event.data) };
  if (normalized.type === "langgraph_tasks") {
    return buildLanggraphToolItems(normalized);
  }
  if (normalized.type === "tool_result") {
    return [buildDirectToolObservation(normalized)];
  }
  if (normalized.type === "participant_handoff" || normalized.type === "participant_message" || normalized.type === "subagent") {
    return [buildParticipantItem(normalized)];
  }
  if (APPROVAL_EVENT_TYPES.has(normalized.type)) {
    return options.showKeySystemCards ? [buildApprovalItem(normalized)] : [];
  }
  if (NOTICE_EVENT_TYPES.has(normalized.type)) {
    return options.showKeySystemCards ? [buildNoticeItem(normalized)] : [];
  }
  return [];
}

function buildEventItems(events, turnMetadata, options) {
  const items = [];
  const chunkBuffer = [];
  let chunkKey = null;
  const orderedEvents = asArray(events)
    .map((event, index) => ({ ...event, _inputOrder: index }))
    .sort(compareRawEvents)
    .map((event, index) => ({ ...event, _orderedEventIndex: index }));
  for (const event of orderedEvents) {
    if (event.type === "assistant_chunk") {
      const normalized = { ...event, data: asObject(event.data) };
      const nextKey = `${eventTurnId(normalized) || ""}:${speakerKey(normalized)}`;
      if (chunkKey && chunkKey !== nextKey) {
        flushThoughtChunks(items, chunkBuffer, turnMetadata, options);
      }
      chunkKey = nextKey;
      chunkBuffer.push(normalized);
      continue;
    }
    const visibleItems = buildVisibleEventItems(event, options);
    if (!visibleItems.length) {
      continue;
    }
    flushThoughtChunks(items, chunkBuffer, turnMetadata, options);
    chunkKey = null;
    items.push(...visibleItems);
  }
  flushThoughtChunks(items, chunkBuffer, turnMetadata, options);
  return items;
}

export function buildConversationItems(messages, events, options = DEFAULT_OPTIONS) {
  const normalizedOptions = normalizeOptions(options);
  const turnMetadata = buildTurnMetadata(messages, events, normalizedOptions);
  const messageItems = asArray(messages).map(buildMessageItem);
  const eventItems = buildEventItems(events, turnMetadata, normalizedOptions);
  return [...messageItems, ...eventItems].sort(compareConversationItems);
}
