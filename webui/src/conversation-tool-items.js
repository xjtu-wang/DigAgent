import { compactText } from "./chat-utils.js";
import {
  ACTION_LABEL,
  asArray,
  asObject,
  eventSourceOrder,
  parseJson,
  safeHost,
  toolSemanticsFromParts,
} from "./conversation-item-utils.js";

export function buildLanggraphToolItems(event) {
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

export function buildDirectToolObservation(event) {
  const data = asObject(event.data);
  const semantics = toolSemanticsFromParts({
    arguments: data.arguments,
    fallback: data,
    source: data.source,
  });
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
      source_url: data.source_url || data.source?.url || null,
      detail: data.detail || data.raw_output || "",
      facts: asArray(data.facts).slice(0, 4),
      source_host: safeHost(data.source_url || data.source?.url),
      ...semantics,
    },
  };
}

function buildActionItem(event, toolCall, requestMessage, suborder = 0) {
  const callArgs = asObject(toolCall?.args);
  const argKeys = Object.keys(callArgs);
  const semantics = toolSemanticsFromParts({ arguments: callArgs });
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
      ...semantics,
    },
  };
}

function buildObservationItem(event, message, parsed, suborder = 0) {
  const toolName = message?.name || parsed?.source?.tool_name || "tool";
  const rawOutput = parseJson(parsed?.raw_output);
  const source = asObject(parsed?.source);
  const sourceUrl = source.url || rawOutput?.url || null;
  const detail = typeof parsed?.raw_output === "string"
    ? parsed.raw_output
    : typeof message?.content === "string"
      ? message.content
      : "";
  const semantics = toolSemanticsFromParts({
    fallback: parsed,
    source,
  });
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
      ...semantics,
    },
  };
}
