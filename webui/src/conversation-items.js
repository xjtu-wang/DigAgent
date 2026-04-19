import { compactText } from "./chat-utils.js";

const ACTION_LABEL = "执行动作";
const APPROVAL_EVENT_TYPES = new Set(["approval_required"]);
const NOTICE_EVENT_TYPES = new Set(["approval_expired", "approval_superseded", "awaiting_user_input", "failed", "timed_out", "cancelled"]);
const TYPE_ORDER = {
  user_message: 0,
  participant_handoff: 1,
  assistant_thought: 2,
  tool_action: 3,
  tool_observation: 4,
  approval_request: 5,
  participant_message: 6,
  assistant_message: 7,
  system_notice: 8,
};

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

function compareItems(left, right) {
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

function flushThoughtChunks(items, chunkBuffer) {
  if (!chunkBuffer.length) {
    return;
  }
  const text = chunkBuffer.map((item) => String(item.data?.text || "")).join("").trim();
  if (!text) {
    chunkBuffer.length = 0;
    return;
  }
  const first = chunkBuffer[0];
  items.push({
    event_id: `thought-${first.event_id}`,
    session_id: first.session_id,
    turn_id: first.turn_id || null,
    type: "assistant_thought",
    created_at: first.created_at,
    data: {
      summary: compactText(text, 180),
      detail: text,
      speaker_profile: normalizeSpeaker(first.data?.speaker_profile || first.data?.participant_profile, "assistant"),
      chunk_count: chunkBuffer.length,
    },
  });
  chunkBuffer.length = 0;
}

function buildActionItem(event, toolCall, requestMessage) {
  const callArgs = asObject(toolCall?.args);
  const argKeys = Object.keys(callArgs);
  return {
    event_id: `tool-action-${toolCall.id || event.event_id}`,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "tool_action",
    created_at: event.created_at,
    data: {
      tool_call_id: toolCall.id || event.event_id,
      tool_name: toolCall.name || "tool",
      title: `${ACTION_LABEL} · ${toolCall.name || "tool"}`,
      summary: compactText(requestMessage || `调用 ${toolCall.name || "tool"}`, 180),
      arguments: callArgs,
      argument_count: argKeys.length,
    },
  };
}

function buildObservationItem(event, message, parsed) {
  const toolName = message?.name || parsed?.source?.tool_name || "tool";
  const rawOutput = parseJson(parsed?.raw_output);
  const sourceUrl = parsed?.source?.url || rawOutput?.url || null;
  return {
    event_id: `tool-observation-${message?.tool_call_id || event.event_id}`,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "tool_observation",
    created_at: event.created_at,
    data: {
      tool_call_id: message?.tool_call_id || event.event_id,
      tool_name: toolName,
      title: parsed?.title || `观察结果 · ${toolName}`,
      summary: compactText(parsed?.summary || message?.content || "工具返回了观察结果。", 180),
      status: message?.status || "success",
      source_url: sourceUrl,
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
      for (const toolCall of asArray(message?.tool_calls)) {
        items.push(buildActionItem(event, toolCall, requestMessage));
      }
    }
  }
  if (payload.name === "tools") {
    for (const message of messages) {
      if (message?.type !== "tool") {
        continue;
      }
      const parsed = parseJson(message.content) || {};
      items.push(buildObservationItem(event, message, parsed));
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
    data: {
      tool_call_id: data.tool_call_id || event.event_id,
      tool_name: data.tool_name || "tool",
      title: data.title || `观察结果 · ${data.tool_name || "tool"}`,
      summary: compactText(data.summary || "工具返回了观察结果。", 180),
      status: data.status || "success",
      source_url: data.source_url || null,
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
    data: {
      participant_profile: participantProfile,
      message: data.message || data.summary || data.result?.summary || data.task?.goal || "",
      markdown: data.message || data.summary || data.result?.summary || data.task?.goal || "",
      summary: compactText(data.summary || data.result?.summary || data.task?.goal || "参与者返回了阶段结果。", 180),
    },
  };
}

function buildApprovalItem(event) {
  return {
    event_id: event.event_id,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "approval_request",
    created_at: event.created_at,
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
    data: {
      title: event.type,
      severity: ["failed", "timed_out", "approval_expired"].includes(event.type) ? "error" : "info",
      summary: compactText(data.summary || data.error || data.reason || data.prompt || data.question || event.type, 180),
    },
  };
}

function buildEventItems(events, showKeySystemCards) {
  const items = [];
  const chunkBuffer = [];
  for (const event of [...asArray(events)].sort(compareItems)) {
    if (event.type === "assistant_chunk") {
      chunkBuffer.push({ ...event, data: asObject(event.data) });
      continue;
    }
    flushThoughtChunks(items, chunkBuffer);
    if (event.type === "langgraph_tasks") {
      items.push(...buildLanggraphToolItems({ ...event, data: asObject(event.data) }));
      continue;
    }
    if (event.type === "tool_result") {
      items.push(buildDirectToolObservation({ ...event, data: asObject(event.data) }));
      continue;
    }
    if (event.type === "participant_handoff" || event.type === "participant_message" || event.type === "subagent") {
      items.push(buildParticipantItem({ ...event, data: asObject(event.data) }));
      continue;
    }
    if (APPROVAL_EVENT_TYPES.has(event.type)) {
      if (showKeySystemCards) {
        items.push(buildApprovalItem({ ...event, data: asObject(event.data) }));
      }
      continue;
    }
    if (NOTICE_EVENT_TYPES.has(event.type) && showKeySystemCards) {
      items.push(buildNoticeItem({ ...event, data: asObject(event.data) }));
    }
  }
  flushThoughtChunks(items, chunkBuffer);
  return items;
}

export function buildConversationItems(messages, events, showKeySystemCards = true) {
  const messageItems = asArray(messages).map(buildMessageItem);
  const eventItems = buildEventItems(events, showKeySystemCards);
  return [...messageItems, ...eventItems].sort(compareItems);
}
