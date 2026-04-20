import { compactText } from "./chat-utils.js";
import { buildConversationItems, KEY_SYSTEM_CONVERSATION_ITEM_TYPES, PRIMARY_CONVERSATION_ITEM_TYPES } from "./conversation-items.js";
import { statusLabel } from "./ui-copy.js";

export const KEY_CHAT_EVENT_TYPES = KEY_SYSTEM_CONVERSATION_ITEM_TYPES;

export const SYSTEM_ACTIVITY_TYPES = new Set([
  "turn_recorded",
  "user_task_recorded",
  "assistant_response_recorded",
  "turn_terminal_recorded",
  "plan",
  "task_node_started",
  "task_node_completed",
  "task_node_waiting_approval",
  "task_node_waiting_user_input",
  "graph_op_applied",
  "awaiting_approval",
  "approval_required",
  "approval_resolved",
  "approval_superseded",
  "tool_result",
  "evidence_added",
  "subagent",
  "aggregate",
  "report_ready",
  "export",
  "completed",
  "failed",
  "approval_expired",
  "timed_out",
  "awaiting_user_input",
  "cancelled",
  "turn_superseded",
]);

export const systemEventLabels = {
  turn_recorded: "执行已记录",
  user_task_recorded: "用户目标",
  assistant_response_recorded: "答复已记录",
  turn_terminal_recorded: "执行结束",
  plan: "任务规划",
  task_node_started: "步骤开始",
  task_node_completed: "步骤完成",
  task_node_waiting_approval: "步骤等待确认",
  task_node_waiting_user_input: "步骤等待补充",
  graph_op_applied: "执行流程更新",
  awaiting_approval: "等待确认",
  approval_required: "等待确认",
  approval_resolved: "确认已处理",
  approval_superseded: "确认已被替代",
  tool_result: "工具结果",
  evidence_added: "新增证据",
  subagent: "子 Agent",
  aggregate: "汇总",
  report_ready: "报告生成",
  export: "导出完成",
  approval_expired: "确认已过期",
  awaiting_user_input: "等待补充信息",
  completed: "执行完成",
  failed: "执行失败",
  timed_out: "执行超时",
  cancelled: "执行已取消",
  turn_superseded: "执行已被替代",
};

export function mergeHistory(messages, events, turns) {
  void turns;
  return buildConversationItems(messages, events, true);
}

export function filterPrimaryTimeline(timeline, showKeySystemCards = true) {
  return timeline.filter((item) => {
    if (PRIMARY_CONVERSATION_ITEM_TYPES.has(item.type) || item.type === "local_user") {
      return true;
    }
    return showKeySystemCards && KEY_CHAT_EVENT_TYPES.has(item.type);
  });
}

export function filterActivityEvents(events) {
  return events
    .filter((item) => SYSTEM_ACTIVITY_TYPES.has(item.type))
    .sort((left, right) => new Date(right.created_at || 0) - new Date(left.created_at || 0));
}

export function eventSummary(item) {
  const data = item.data || {};
  if (item.type === "turn_recorded") {
    return compactText(data.goal || data.turn_id || "已记录执行", 120);
  }
  if (item.type === "user_task_recorded") {
    return compactText(data.goal || "已记录用户目标", 120);
  }
  if (item.type === "assistant_response_recorded") {
    return compactText(data.preview || "已记录助手答复", 120);
  }
  if (item.type === "turn_terminal_recorded") {
    const status = statusLabel(data.status || "completed");
    return `执行结束 · ${status}`;
  }
  if (item.type === "plan") {
    return `已生成 ${data.nodes?.length || 0} 个执行步骤`;
  }
  if (item.type === "task_node_started" || item.type === "task_node_completed") {
    return data.title || data.node_id || systemEventLabels[item.type];
  }
  if (item.type === "task_node_waiting_approval") {
    return data.reason || "步骤等待确认";
  }
  if (item.type === "task_node_waiting_user_input" || item.type === "awaiting_user_input") {
    return data.question || data.prompt || "等待补充信息";
  }
  if (item.type === "awaiting_approval") {
    return `等待确认${Array.isArray(data.approval_ids) && data.approval_ids.length ? `（${data.approval_ids.length} 项）` : ""}`;
  }
  if (item.type === "graph_op_applied") {
    return data.op_type || "执行流程已更新";
  }
  if (item.type === "tool_result") {
    return data.summary || data.title || "工具执行完成";
  }
  if (item.type === "evidence_added") {
    return data.title || data.evidence_id || "新增证据";
  }
  if (item.type === "subagent") {
    return data.result?.summary || data.task?.goal || "子 Agent 已返回结果";
  }
  if (item.type === "aggregate") {
    return data.summary || "已完成阶段汇总";
  }
  if (item.type === "report_ready") {
    return data.report_id ? `结果报告 ${data.report_id} 已生成` : "结果报告已生成";
  }
  if (item.type === "export") {
    return "导出已完成";
  }
  if (item.type === "completed") {
    return data.summary || "本轮执行已完成";
  }
  if (item.type === "failed") {
    return data.error || "本轮执行失败";
  }
  if (item.type === "approval_expired") {
    return data.reason || "确认已过期";
  }
  if (item.type === "timed_out") {
    return data.reason || "本轮执行超时";
  }
  if (item.type === "approval_resolved") {
    return data.status === "approved" ? "已批准，执行继续" : "已拒绝，本次执行不会继续";
  }
  if (item.type === "approval_superseded") {
    return data.reason || "当前确认已被新的动作替代";
  }
  if (item.type === "cancelled") {
    return "本轮执行已取消";
  }
  if (item.type === "turn_superseded") {
    return data.reason || "当前执行已被新的消息替代";
  }
  return systemEventLabels[item.type] || item.type;
}
