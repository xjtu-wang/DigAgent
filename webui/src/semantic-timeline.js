import { compactText } from "./chat-utils.js";
import { buildConversationItems } from "./conversation-items.js";
import { buildTurnTimelineEntries } from "./turn-utils.js";

const ROOT_ASSISTANT_SPEAKERS = new Set([
  "assistant",
  "sisyphus-default",
  "digagent",
  "DA",
]);

export function buildPrimaryTimeline(messages, events, turns, options = true) {
  const normalizedOptions = normalizeOptions(options);
  const conversationItems = buildConversationItems(messages, events, normalizedOptions);
  const reportItems = buildReportItems(turns, messages, events);
  const orderedItems = [...conversationItems, ...reportItems].sort(compareTimelineEntries);
  return buildSemanticTimeline(orderedItems);
}

export function buildSemanticTimeline(timeline) {
  const groups = [];
  let currentGroup = null;

  for (const item of timeline) {
    const descriptor = describeItem(item);
    if (canAppendToGroup(currentGroup, descriptor)) {
      currentGroup.items.push(item);
      continue;
    }
    currentGroup = createGroup(item, descriptor);
    groups.push(currentGroup);
  }

  return groups.map(finalizeGroup);
}

function normalizeOptions(input) {
  if (typeof input === "boolean") {
    return { showKeySystemCards: input, activeTurnId: null };
  }
  return {
    showKeySystemCards: input?.showKeySystemCards ?? true,
    activeTurnId: input?.activeTurnId ?? null,
  };
}

function buildReportItems(turns, messages, events) {
  return buildTurnTimelineEntries(turns, messages, events)
    .filter(shouldIncludeReportItem)
    .map((item) => ({
      ...item,
      created_at: item.data?.raw?.turn?.updated_at || item.created_at,
      _semanticOrder: 100,
    }));
}

function shouldIncludeReportItem(item) {
  const data = item?.data || {};
  return Boolean(data.report_id || data.evidence_count || data.artifact_count);
}

function compareTimelineEntries(left, right) {
  const timeDelta = new Date(left?.created_at || 0) - new Date(right?.created_at || 0);
  if (timeDelta !== 0) {
    return timeDelta;
  }
  const sourceDelta = compareOrderedField(left?._eventSourceOrder, right?._eventSourceOrder);
  if (sourceDelta !== 0) {
    return sourceDelta;
  }
  const suborderDelta = compareOrderedField(left?._eventSuborder, right?._eventSuborder);
  if (suborderDelta !== 0) {
    return suborderDelta;
  }
  const semanticDelta = (left?._semanticOrder ?? 0) - (right?._semanticOrder ?? 0);
  if (semanticDelta !== 0) {
    return semanticDelta;
  }
  return String(left?.event_id || "").localeCompare(String(right?.event_id || ""));
}

function compareOrderedField(left, right) {
  const hasLeft = Number.isFinite(left);
  const hasRight = Number.isFinite(right);
  if (hasLeft && hasRight && left !== right) {
    return left - right;
  }
  if (hasLeft !== hasRight) {
    return hasLeft ? -1 : 1;
  }
  return 0;
}

function createGroup(item, descriptor) {
  return {
    id: item.event_id,
    type: descriptor.type,
    layout: descriptor.layout,
    title: descriptor.title,
    speakerLabel: descriptor.speakerLabel || null,
    speakerRole: descriptor.speakerRole || null,
    mergeKey: descriptor.mergeKey || null,
    items: [item],
  };
}

function canAppendToGroup(currentGroup, descriptor) {
  return Boolean(
    currentGroup
      && descriptor.mergeKey
      && currentGroup.type === descriptor.type
      && currentGroup.mergeKey === descriptor.mergeKey,
  );
}

function finalizeGroup(group) {
  const latestItem = group.items[group.items.length - 1];
  return {
    id: group.id,
    type: group.type,
    layout: group.layout,
    title: group.title,
    speakerLabel: group.speakerLabel,
    speakerRole: group.speakerRole,
    created_at: group.items[0]?.created_at || null,
    latest_at: latestItem?.created_at || null,
    summary: summarizeGroup(group.type, group.items),
    count: group.items.length,
    items: group.items,
  };
}

function describeItem(item) {
  if (item.type === "local_user" || item.type === "user_message") {
    return {
      type: "message",
      layout: "message",
      speakerLabel: "你",
      speakerRole: "user",
      title: "你",
    };
  }
  if (item.type === "assistant_message") {
    return describeAssistantMessage(item);
  }
  if (item.type === "participant_handoff" || item.type === "participant_message" || item.type === "subagent") {
    return {
      type: "agent",
      layout: "cluster",
      mergeKey: `agent:${item.turn_id || ""}`,
      title: "Agent 协作",
    };
  }
  if (item.type === "tool_action" || item.type === "tool_observation" || item.type === "tool_result") {
    const type = toolGroupType(item);
    return {
      type,
      layout: "cluster",
      mergeKey: `${type}:${item.turn_id || ""}`,
      title: titleForType(type),
    };
  }
  if (item.type === "approval_required" || item.type === "approval_notice" || item.type === "approval_request") {
    return {
      type: "approval",
      layout: "approval",
      title: item.data?.title || "审批",
    };
  }
  if (item.type === "assistant_process" || item.type === "assistant_thought" || item.type === "langgraph_tasks") {
    return {
      type: "workflow",
      layout: "cluster",
      mergeKey: `workflow:${item.turn_id || ""}:${item.data?.speaker_profile || ""}`,
      title: "执行过程",
    };
  }
  if (item.type === "turn_card" || item.type === "report_ready") {
    return {
      type: "report",
      layout: "report",
      title: "执行总结",
    };
  }
  return {
    type: "system",
    layout: "cluster",
    mergeKey: `system:${item.turn_id || ""}`,
    title: "系统提示",
  };
}

function describeAssistantMessage(item) {
  const speaker = String(item.data?.speaker_profile || "assistant");
  if (ROOT_ASSISTANT_SPEAKERS.has(speaker)) {
    return {
      type: "message",
      layout: "message",
      speakerLabel: speaker === "assistant" ? "DigAgent" : speaker,
      speakerRole: "assistant",
      title: "DigAgent",
    };
  }
  return {
    type: "agent",
    layout: "agent-message",
    speakerLabel: speaker,
    speakerRole: "agent",
    title: `@${speaker}`,
  };
}

function toolGroupType(item) {
  const data = item.data || {};
  if (data.skill_name || data.skill_id || data.arguments?.skill_name || data.arguments?.skill_id) {
    return "skill";
  }
  if (
    data.mcp_server_id
    || data.server_id
    || data.source?.server_id
    || data.source?.kind === "mcp"
    || data.arguments?.server_id
    || data.arguments?.mcp_server_id
  ) {
    return "mcp";
  }
  return "tool";
}

function titleForType(type) {
  if (type === "skill") {
    return "Skill 调用";
  }
  if (type === "mcp") {
    return "MCP 调用";
  }
  if (type === "workflow") {
    return "执行过程";
  }
  if (type === "agent") {
    return "Agent 协作";
  }
  if (type === "report") {
    return "执行总结";
  }
  if (type === "system") {
    return "系统提示";
  }
  return "工具调用";
}

function summarizeGroup(type, items) {
  const latestItem = items[items.length - 1];
  if (type === "message") {
    return compactText(messageText(items[0]), 220);
  }
  if (type === "report") {
    return compactText(latestItem?.data?.result_summary || latestItem?.data?.action_summary || "执行已生成总结。", 220);
  }
  if (type === "approval") {
    return compactText(latestItem?.data?.summary || latestItem?.data?.reason || "确认状态已更新。", 220);
  }
  return compactText(
    latestItem?.data?.summary
      || latestItem?.data?.message
      || latestItem?.data?.detail
      || latestItem?.data?.title
      || titleForType(type),
    220,
  );
}

function messageText(item) {
  return item?.data?.markdown || item?.data?.message || "";
}
