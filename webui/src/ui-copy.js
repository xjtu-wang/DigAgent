const STATUS_LABELS = Object.freeze({
  idle: "空闲",
  created: "已创建",
  planning: "规划中",
  running: "进行中",
  active_turn: "进行中",
  active_run: "进行中",
  reporting: "整理结果",
  aggregating: "整理中",
  awaiting_approval: "等待确认",
  awaiting_user_input: "等待补充信息",
  waiting_approval: "等待确认",
  waiting_user_input: "等待补充信息",
  blocked: "已阻塞",
  ready: "就绪",
  pending: "等待开始",
  archived: "已归档",
  completed: "已完成",
  failed: "执行失败",
  timed_out: "执行超时",
  cancelled: "已取消",
  deprecated: "已弃用",
  resolved: "已处理",
  expired: "已过期",
  superseded: "已替代",
  success: "成功",
});

const INSPECTOR_TAB_LABELS = Object.freeze({
  workflow: "执行流程",
  execution: "执行概览",
  activity: "系统事件",
  session: "会话设置",
});

const TIMELINE_DENSITY_LABELS = Object.freeze({
  comfortable: "宽松",
  compact: "紧凑",
});

const PERMISSION_RULE_LABELS = Object.freeze({
  inherit: "沿用",
  allow: "允许",
  confirm: "询问",
  deny: "拒绝",
});

const SETTINGS_SUMMARY_LABELS = Object.freeze({
  model_ready: "模型可用",
  model_unavailable: "模型不可用",
  real_model: "真实模型",
  fake_model: "模拟模型",
  nvd_ready: "NVD 已配置",
  nvd_missing: "NVD 未配置",
});

export function composerPlaceholder() {
  return "输入你的问题或任务，输入 @ 可提及 Agent";
}

export function composerRuntimeChips(runtimeDraft, permissionOverrides) {
  const chips = [];
  if (runtimeDraft?.profile) {
    chips.push(`执行配置 ${runtimeDraft.profile}`);
  }
  if (runtimeDraft?.repoPath) {
    chips.push(`仓库 ${runtimeDraft.repoPath}`);
  }
  if (runtimeDraft?.domain) {
    chips.push(`域名 ${runtimeDraft.domain}`);
  }
  if (runtimeDraft?.autoApprove) {
    chips.push("本页自动确认");
  }
  if (permissionOverrides?.auto_approve) {
    chips.push("会话自动确认");
  }
  return chips;
}

export function enterHintLabel(enterToSend) {
  return enterToSend
    ? "Enter 发送，Shift + Enter 换行"
    : "Enter 换行，Shift + Enter 换行";
}

export function eventCountLabel(count = 0) {
  return `${count} 条事件`;
}

export function inspectorTabLabel(tabId) {
  return INSPECTOR_TAB_LABELS[tabId] || String(tabId || "");
}

export function notInProfileLabel() {
  return "当前执行配置未默认包含";
}

export function permissionRuleLabel(rule) {
  return PERMISSION_RULE_LABELS[rule] || String(rule || "");
}

export function profileSummaryLabel(profileName, overrideCount) {
  return `执行配置：${profileName} · 已自定义 ${overrideCount} 条规则`;
}

export function responseCharsLabel(count = 0) {
  return `${count} 字`;
}

export function settingsSummaryBadges(summary = {}) {
  return [
    summary.can_use_model ? SETTINGS_SUMMARY_LABELS.model_ready : SETTINGS_SUMMARY_LABELS.model_unavailable,
    summary.fake_model ? SETTINGS_SUMMARY_LABELS.fake_model : SETTINGS_SUMMARY_LABELS.real_model,
    summary.has_nvd_api_key ? SETTINGS_SUMMARY_LABELS.nvd_ready : SETTINGS_SUMMARY_LABELS.nvd_missing,
    `审批超时 ${summary.approval_timeout_sec} 秒`,
  ];
}

export function statusLabel(status) {
  if (!status) {
    return STATUS_LABELS.idle;
  }
  return STATUS_LABELS[status] || String(status);
}

export function timelineDensityLabel(value) {
  return TIMELINE_DENSITY_LABELS[value] || String(value || "");
}

export function workflowCountLabel(count = 0) {
  return `${count} 步`;
}
