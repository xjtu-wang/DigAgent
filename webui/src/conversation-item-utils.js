const ACTION_LABEL = "执行动作";

const APPROVAL_REQUEST_EVENT_TYPES = new Set(["approval_required"]);
const APPROVAL_NOTICE_EVENT_TYPES = new Set([
  "approval_resolved",
  "approval_expired",
  "approval_superseded",
]);
const NOTICE_EVENT_TYPES = new Set([
  "awaiting_user_input",
  "failed",
  "timed_out",
  "cancelled",
]);

export const PRIMARY_CONVERSATION_ITEM_TYPES = new Set([
  "user_message",
  "assistant_process",
  "tool_action",
  "tool_observation",
  "participant_handoff",
  "participant_message",
  "assistant_message",
  "turn_card",
]);

export const KEY_SYSTEM_CONVERSATION_ITEM_TYPES = new Set([
  "approval_required",
  "approval_notice",
  "system_notice",
]);

const TYPE_ORDER = {
  user_message: 0,
  assistant_process: 1,
  participant_handoff: 2,
  tool_action: 3,
  tool_observation: 4,
  approval_required: 5,
  approval_notice: 5,
  participant_message: 6,
  assistant_message: 7,
  turn_card: 8,
  system_notice: 9,
};

const DEFAULT_OPTIONS = Object.freeze({
  activeTurnId: null,
  showKeySystemCards: true,
});

export function asArray(value) {
  return Array.isArray(value) ? value : [];
}

export function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function parseJson(value) {
  if (typeof value !== "string") {
    return null;
  }
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

export function safeHost(value) {
  if (!value) {
    return "";
  }
  try {
    return new URL(value).host;
  } catch {
    return "";
  }
}

export function uniqueList(values) {
  return [...new Set(values.filter(Boolean).map(String))];
}

export function normalizeSpeaker(value, fallback = null) {
  if (typeof value === "string" && value.trim()) {
    return value.trim();
  }
  return fallback;
}

export function numericValue(value) {
  return Number.isFinite(value) ? value : null;
}

export function compareConversationItems(left, right) {
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

export function compareRawEvents(left, right) {
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

export function normalizeConversationOptions(options) {
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

export function eventTurnId(event) {
  return event?.turn_id || event?.data?.turn_id || null;
}

export function speakerKey(event) {
  return normalizeSpeaker(
    event?.data?.speaker_profile
      || event?.speaker_profile
      || event?.data?.participant_profile
      || event?.participant_profile,
    "assistant",
  );
}

export function eventSourceOrder(event, fallbackOrder = null) {
  return numericValue(event?.session_event_index)
    ?? numericValue(event?.turn_event_index)
    ?? numericValue(event?._orderedEventIndex)
    ?? numericValue(event?._inputOrder)
    ?? fallbackOrder;
}

export function splitParagraphs(text) {
  return String(text || "")
    .split(/\n\s*\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function toolSemanticsFromParts(parts = {}) {
  const source = asObject(parts.source);
  const argumentsValue = asObject(parts.arguments);
  const fallback = asObject(parts.fallback);
  const skillName = parts.skill_name
    || argumentsValue.skill_name
    || fallback.skill_name
    || source.skill_name
    || null;
  const skillId = parts.skill_id
    || argumentsValue.skill_id
    || fallback.skill_id
    || source.skill_id
    || null;
  const serverId = parts.server_id
    || argumentsValue.server_id
    || argumentsValue.mcp_server_id
    || fallback.server_id
    || fallback.mcp_server_id
    || source.server_id
    || source.mcp_server_id
    || null;
  const isMcp = source.kind === "mcp" || Boolean(serverId);
  return {
    skill_name: skillName,
    skill_id: skillId,
    server_id: serverId,
    mcp_server_id: isMcp ? serverId || "mcp" : null,
    source: Object.keys(source).length ? source : null,
  };
}

export function approvalStateForType(type) {
  if (type === "approval_resolved") {
    return "resolved";
  }
  if (type === "approval_expired") {
    return "expired";
  }
  if (type === "approval_superseded") {
    return "superseded";
  }
  return "required";
}

export function approvalTitleForType(type) {
  if (type === "approval_resolved") {
    return "确认已处理";
  }
  if (type === "approval_expired") {
    return "确认已过期";
  }
  if (type === "approval_superseded") {
    return "确认已被替代";
  }
  return "需要确认";
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

export {
  ACTION_LABEL,
  APPROVAL_NOTICE_EVENT_TYPES,
  APPROVAL_REQUEST_EVENT_TYPES,
  DEFAULT_OPTIONS,
  NOTICE_EVENT_TYPES,
};
