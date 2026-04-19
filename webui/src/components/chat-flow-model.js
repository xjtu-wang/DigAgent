import { compactText } from "../chat-utils.js";

const APPROVAL_ACTIVITY_TYPES = new Set([
  "approval_required",
  "approval_expired",
  "approval_superseded",
]);

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function firstText(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function stringifyValue(value) {
  if (value == null || value === "") {
    return "";
  }
  if (typeof value === "string") {
    return value.trim();
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function toolActionSummary(tool) {
  const callArgs = asObject(tool.call_args);
  if (typeof callArgs.url === "string" && callArgs.url.trim()) {
    return compactText(`请求 ${callArgs.url.trim()}`, 180);
  }
  if (typeof callArgs.command === "string" && callArgs.command.trim()) {
    return compactText(`执行 ${callArgs.command.trim()}`, 180);
  }
  if (typeof callArgs.path === "string" && callArgs.path.trim()) {
    return compactText(`读取 ${callArgs.path.trim()}`, 180);
  }
  if (typeof callArgs.query === "string" && callArgs.query.trim()) {
    return compactText(`查询 ${callArgs.query.trim()}`, 180);
  }
  if (tool.request_message) {
    return compactText(tool.request_message, 180);
  }
  const keys = Object.keys(callArgs);
  if (keys.length) {
    return `参数: ${keys.slice(0, 4).join(", ")}`;
  }
  return compactText(tool.title || tool.tool_name || "发起了一次工具动作。", 180);
}

function toolActionDetail(tool) {
  const callArgs = asObject(tool.call_args);
  return Object.keys(callArgs).length ? stringifyValue(callArgs) : "";
}

function toolObservationDetail(tool) {
  return firstText(
    tool.body_excerpt,
    stringifyValue(tool.raw_output_object),
    stringifyValue(tool.raw_output),
  );
}

function pushWorkflowBlocks(blocks, workflowItems) {
  for (const item of asArray(workflowItems)) {
    if (item?.type === "assistant_chunk") {
      blocks.push({
        block_id: `thought-${item.event_id}`,
        type: "assistant_thought",
        title: item.title || "执行思路",
        summary: item.summary || "暂无思路摘要。",
        detail: firstText(item.detail, item.summary),
        chips: asArray(item.chips),
        created_at: item.created_at,
      });
      continue;
    }
    blocks.push({
      block_id: `participant-${item.event_id}`,
      type: "participant_message",
      title: item.title || "执行更新",
      summary: item.summary || "暂无过程摘要。",
      detail: firstText(item.detail),
      chips: asArray(item.chips),
      created_at: item.created_at,
    });
  }
}

function pushToolBlocks(blocks, tools) {
  for (const tool of asArray(tools)) {
    blocks.push({
      block_id: `tool-action-${tool.tool_call_id || tool.title}`,
      type: "tool_action",
      title: tool.title || tool.tool_name || "工具动作",
      summary: toolActionSummary(tool),
      detail: toolActionDetail(tool),
      chips: [tool.tool_name || "tool", ...asArray(tool.chips).filter((chip) => chip && chip !== tool.tool_status)],
      created_at: tool.created_at,
    });
    blocks.push({
      block_id: `tool-observation-${tool.tool_call_id || tool.title}`,
      type: "tool_observation",
      title: tool.title || tool.tool_name || "工具观察",
      summary: tool.summary || "暂无工具结果。",
      detail: toolObservationDetail(tool),
      chips: asArray(tool.chips),
      created_at: tool.created_at,
    });
  }
}

function pushActivityBlocks(blocks, activityItems) {
  for (const item of asArray(activityItems)) {
    if (APPROVAL_ACTIVITY_TYPES.has(item?.type)) {
      continue;
    }
    blocks.push({
      block_id: `activity-${item.event_id}`,
      type: item?.type === "subagent" ? "participant_handoff" : "participant_message",
      title: item.title || "执行活动",
      summary: item.summary || "暂无活动摘要。",
      detail: firstText(item.detail),
      chips: asArray(item.chips),
      created_at: item.created_at,
    });
  }
}

export function buildTurnFlowBlocks(item) {
  const data = item?.data || {};
  const blocks = [];
  pushWorkflowBlocks(blocks, data.workflow?.items);
  pushToolBlocks(blocks, data.tools?.items);
  pushActivityBlocks(blocks, data.activity?.items);
  return blocks.sort((left, right) => new Date(left.created_at || 0) - new Date(right.created_at || 0));
}
