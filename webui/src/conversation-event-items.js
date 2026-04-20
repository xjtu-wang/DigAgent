import { compactText } from "./chat-utils.js";
import {
  APPROVAL_NOTICE_EVENT_TYPES,
  APPROVAL_REQUEST_EVENT_TYPES,
  NOTICE_EVENT_TYPES,
  approvalStateForType,
  approvalTitleForType,
  asArray,
  asObject,
  eventSourceOrder,
  eventTurnId,
  normalizeSpeaker,
  speakerKey,
  splitParagraphs,
} from "./conversation-item-utils.js";
import { buildDirectToolObservation, buildLanggraphToolItems } from "./conversation-tool-items.js";

const NOTICE_TITLES = Object.freeze({
  awaiting_user_input: "等待补充信息",
  failed: "执行失败",
  timed_out: "执行超时",
  cancelled: "执行已取消",
});

export function buildTurnMetadata(messages, events, options) {
  const turnMap = new Map();
  for (const message of asArray(messages)) {
    if (!message?.turn_id) {
      continue;
    }
    const current = turnMap.get(message.turn_id) || baseTurnMetadata();
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
    const current = turnMap.get(turnId) || baseTurnMetadata();
    if (event.type === "langgraph_tasks") {
      current.hasVisibleProcess = buildLanggraphToolItems(withObjectData(event)).length > 0 || current.hasVisibleProcess;
      turnMap.set(turnId, current);
      continue;
    }
    if (["tool_result", "participant_handoff", "participant_message", "subagent"].includes(event.type)) {
      current.hasVisibleProcess = true;
      turnMap.set(turnId, current);
      continue;
    }
    if (shouldShowKeySystemCard(event.type, options)) {
      current.hasVisibleProcess = true;
      turnMap.set(turnId, current);
    }
  }
  return turnMap;
}

export function buildEventItems(events, turnMetadata, options) {
  const items = [];
  const chunkBuffer = [];
  let chunkKey = null;
  const orderedEvents = asArray(events)
    .map((event, index) => ({ ...event, _inputOrder: index }))
    .sort(compareEventSequence)
    .map((event, index) => ({ ...event, _orderedEventIndex: index }));
  for (const event of orderedEvents) {
    if (event.type === "assistant_chunk") {
      const normalized = withObjectData(event);
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

function baseTurnMetadata() {
  return { hasAssistantMessage: false, hasVisibleProcess: false };
}

function compareEventSequence(left, right) {
  const sourceDelta = (left?.session_event_index ?? left?._inputOrder ?? 0) - (right?.session_event_index ?? right?._inputOrder ?? 0);
  if (sourceDelta !== 0 && Number.isFinite(sourceDelta)) {
    return sourceDelta;
  }
  const timeDelta = new Date(left?.created_at || 0) - new Date(right?.created_at || 0);
  if (timeDelta !== 0) {
    return timeDelta;
  }
  const turnDelta = (left?.turn_event_index ?? 0) - (right?.turn_event_index ?? 0);
  if (turnDelta !== 0) {
    return turnDelta;
  }
  return String(left?.event_id || "").localeCompare(String(right?.event_id || ""));
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
        summary: compactText(data.summary || `任务正从 ${data.handoff_from || "assistant"} 转交给 ${data.handoff_to || data.participant_profile || "agent"}`, 180),
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

function buildApprovalRequestItem(event) {
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

function buildApprovalNoticeItem(event) {
  const data = asObject(event.data);
  return {
    event_id: event.event_id,
    session_id: event.session_id,
    turn_id: event.turn_id || null,
    type: "approval_notice",
    created_at: event.created_at,
    _eventSourceOrder: eventSourceOrder(event),
    _eventSuborder: 0,
    data: {
      approval_id: data.approval_id || data.old_approval_id || null,
      new_approval_id: data.new_approval_id || null,
      status: data.status || null,
      state: approvalStateForType(event.type),
      title: approvalTitleForType(event.type),
      summary: compactText(data.summary || data.reason || data.message || approvalTitleForType(event.type), 180),
      raw_type: event.type,
    },
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
      title: NOTICE_TITLES[event.type] || event.type,
      severity: ["failed", "timed_out"].includes(event.type) ? "error" : "info",
      summary: compactText(data.summary || data.error || data.reason || data.prompt || data.question || NOTICE_TITLES[event.type] || event.type, 180),
    },
  };
}

function buildVisibleEventItems(event, options) {
  const normalized = withObjectData(event);
  if (normalized.type === "langgraph_tasks") {
    return buildLanggraphToolItems(normalized);
  }
  if (normalized.type === "tool_result") {
    return [buildDirectToolObservation(normalized)];
  }
  if (["participant_handoff", "participant_message", "subagent"].includes(normalized.type)) {
    return [buildParticipantItem(normalized)];
  }
  if (APPROVAL_REQUEST_EVENT_TYPES.has(normalized.type)) {
    return options.showKeySystemCards ? [buildApprovalRequestItem(normalized)] : [];
  }
  if (APPROVAL_NOTICE_EVENT_TYPES.has(normalized.type)) {
    return options.showKeySystemCards ? [buildApprovalNoticeItem(normalized)] : [];
  }
  if (NOTICE_EVENT_TYPES.has(normalized.type)) {
    return options.showKeySystemCards ? [buildNoticeItem(normalized)] : [];
  }
  return [];
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

function shouldShowKeySystemCard(type, options) {
  return options.showKeySystemCards
    && (APPROVAL_REQUEST_EVENT_TYPES.has(type)
      || APPROVAL_NOTICE_EVENT_TYPES.has(type)
      || NOTICE_EVENT_TYPES.has(type));
}

function withObjectData(event) {
  return { ...event, data: asObject(event.data) };
}
