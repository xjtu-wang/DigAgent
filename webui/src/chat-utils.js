const MIDDLEWARE_SUMMARIES = { "MemoryMiddleware.before_agent": "准备长期记忆与项目约束，让主 agent 在执行前拿到持久上下文。", "SkillsMiddleware.before_agent": "收集可用 skill 与说明，决定本轮可调用的技能上下文。", "PatchToolCallsMiddleware.before_agent": "整理模型产出的工具调用结构，避免把内部消息直接当作真实工具步骤。", "TodoListMiddleware.after_model": "同步任务清单状态，记录规划或执行后的任务变化。" };
const KIND_LABELS = { input: "输入", tool: "工具", reasoning: "模型推理", system: "中间件", subagent: "子 Agent", report: "汇总", aggregate: "聚合" };
export const graphNodeStyles = { pending: "border-slate-200 bg-white text-slate-500", ready: "border-slate-300 bg-slate-50 text-slate-700", running: "border-emerald-300 bg-emerald-50 text-emerald-800 shadow-[0_16px_45px_rgba(22,101,52,0.12)]", waiting_approval: "border-orange-300 bg-orange-50 text-orange-800 shadow-[0_16px_45px_rgba(251,146,60,0.12)]", waiting_user_input: "border-amber-300 bg-amber-50 text-amber-900 shadow-[0_16px_45px_rgba(245,158,11,0.12)]", blocked: "border-orange-300 bg-orange-50 text-orange-800 shadow-[0_16px_45px_rgba(251,146,60,0.12)]", completed: "border-slate-300 bg-slate-50 text-slate-600", failed: "border-rose-300 bg-rose-50 text-rose-800", timed_out: "border-amber-400 bg-amber-100 text-amber-900", deprecated: "border-slate-300 bg-slate-100 text-slate-500" };
export const statusStyles = { idle: "bg-slate-100 text-slate-700", active_turn: "bg-emerald-100 text-emerald-800", active_run: "bg-emerald-100 text-emerald-800", awaiting_approval: "bg-orange-100 text-orange-800", awaiting_user_input: "bg-amber-100 text-amber-900", archived: "bg-slate-200 text-slate-700", completed: "bg-slate-100 text-slate-700", failed: "bg-rose-100 text-rose-700", timed_out: "bg-amber-100 text-amber-900", cancelled: "bg-slate-200 text-slate-600", running: "bg-emerald-100 text-emerald-800" };

export function scopePayload(repoPath, domain) {
  return {
    repo_paths: repoPath ? [repoPath] : [],
    allowed_domains: domain ? [domain] : [],
    artifacts: [],
  };
}

export function formatTime(value) {
  if (!value) {
    return "";
  }
  try {
    return new Date(value).toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

export function compactText(value, limit = 96) {
  if (!value) {
    return "";
  }
  const compact = String(value).replace(/\s+/g, " ").trim();
  if (compact.length <= limit) {
    return compact;
  }
  return `${compact.slice(0, limit - 1).trimEnd()}...`;
}

export function graphNodeQuestion(node) {
  return node?.metadata?.question || node?.block_reason || node?.summary || node?.description || "";
}
function asArray(value) {
  return Array.isArray(value) ? value : [];
}
function parseMaybeJson(value) {
  if (!value || typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed || !["{", "["].includes(trimmed[0])) {
    return null;
  }
  try {
    return JSON.parse(trimmed);
  } catch {
    return null;
  }
}
function humanizeName(value) {
  return String(value || "")
    .replaceAll(/[_-]+/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .trim()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
function messageText(message) {
  if (!message) {
    return "";
  }
  const content = message.content;
  if (typeof content === "string") {
    return content;
  }
  return compactText(JSON.stringify(content), 220);
}
function transcriptMessages(node, payload) {
  const direct = payload?.messages?.value || payload?.messages;
  if (Array.isArray(direct)) {
    return direct;
  }
  const inputMessages = node?.metadata?.payload?.input?.messages;
  return Array.isArray(inputMessages) ? inputMessages : [];
}
function latestMessage(messages, types) {
  for (const message of [...messages].reverse()) {
    if (!types.includes(message?.type)) {
      continue;
    }
    return message;
  }
  return null;
}
function toolObservationFromMessage(message) {
  if (!message) {
    return null;
  }
  const parsed = parseMaybeJson(messageText(message));
  const toolName = parsed?.source?.tool_name || message?.name || null;
  if (!toolName && !parsed?.summary && !parsed?.title) {
    return null;
  }
  const facts = asArray(parsed?.facts).slice(0, 4).map((fact) => `${humanizeName(fact.key)}: ${compactText(fact.value, 48)}`);
  return {
    raw: parsed || { content: messageText(message), name: message?.name || null },
    title: parsed?.title || humanizeName(toolName || "tool"),
    summary: compactText(parsed?.summary || messageText(message), 180),
    toolName: toolName || parsed?.title || "tool",
    target: parsed?.source?.url || parsed?.url || null,
    facts,
  };
}
function classifySemanticKind(node, toolObservation) {
  const title = String(node?.title || "");
  if (/middleware|\.before_|\.after_/i.test(title)) {
    return "system";
  }
  if (toolObservation || /^tools?$/i.test(title)) {
    return "tool";
  }
  if (/^model$/i.test(title)) {
    return "reasoning";
  }
  if (node?.kind === "subagent") {
    return "subagent";
  }
  if (node?.kind === "input") {
    return "input";
  }
  if (["report", "export"].includes(node?.kind)) {
    return "report";
  }
  return node?.kind || "aggregate";
}
function displayTitle(node, semanticKind, toolObservation) {
  const rawTitle = String(node?.title || "").trim();
  if (semanticKind === "system") {
    return humanizeName(rawTitle.replaceAll(".", " "));
  }
  if (semanticKind === "reasoning") {
    return rawTitle === "model" ? "模型推理" : rawTitle;
  }
  if (semanticKind === "tool" && toolObservation?.title) {
    return toolObservation.title;
  }
  return rawTitle || "未命名步骤";
}
function nodeSummary(node, semanticKind, messages, toolObservation) {
  if (semanticKind === "system") {
    return MIDDLEWARE_SUMMARIES[node?.title] || "内部运行时步骤，用来注入上下文、整理调用或同步执行状态。";
  }
  if (semanticKind === "tool") {
    return toolObservation?.summary || "工具完成了一次外部观察或操作。";
  }
  if (semanticKind === "reasoning") {
    return compactText(messageText(latestMessage(messages, ["ai"])) || node?.summary || node?.description || "模型生成了下一步计划或答复。", 180);
  }
  if (semanticKind === "input") {
    return compactText(node?.description || node?.summary || "收到新的用户目标。", 180);
  }
  return compactText(node?.summary || node?.description || "该步骤没有额外摘要。", 180);
}
function nodeDetailSections(node, semanticKind, summary, toolObservation) {
  if (semanticKind === "tool") {
    return [
      { label: "观察摘要", value: summary },
      { label: "目标", value: toolObservation?.target || null },
      { label: "关键事实", value: toolObservation?.facts?.length ? toolObservation.facts.join(" · ") : null },
    ].filter((item) => item.value);
  }
  if (semanticKind === "system") {
    return [
      { label: "内部职责", value: summary },
      { label: "原始节点", value: node?.title || null },
    ].filter((item) => item.value);
  }
  return [{ label: "摘要", value: summary }];
}
function nodeDebugPayload(node, payload, toolObservation) {
  return toolObservation?.raw || node?.action_request || node?.metadata?.payload || payload || node?.metadata || null;
}
function nodeMetadataBadges(node, semanticKind, toolObservation) {
  return [KIND_LABELS[semanticKind], toolObservation?.toolName ? humanizeName(toolObservation.toolName) : null, node?.owner_profile_name || null].filter(Boolean);
}
function nodeEventsById(events) {
  const grouped = new Map();
  for (const event of [...events].sort((a, b) => new Date(a.created_at || 0) - new Date(b.created_at || 0))) {
    const nodeId = event?.data?.node_id;
    if (!nodeId) {
      continue;
    }
    const items = grouped.get(nodeId) || [];
    items.push(event);
    grouped.set(nodeId, items);
  }
  return grouped;
}
function timelineFields(node, nodeEvents, index) {
  const firstEvent = nodeEvents[0] || null;
  const lastEvent = nodeEvents.at(-1) || null;
  let startedAt = node?.metadata?.started_at || node?.metadata?.created_at || null;
  let completedAt = node?.metadata?.completed_at || null;
  for (const event of nodeEvents) {
    if (event.type === "task_node_started" && !startedAt) {
      startedAt = event.created_at;
    }
    if (event.type === "task_node_completed") {
      completedAt = event.created_at;
    }
  }
  return {
    orderIndex: index,
    eventCount: nodeEvents.length,
    firstEventAt: firstEvent?.created_at || node?.metadata?.created_at || null,
    lastEventAt: lastEvent?.created_at || node?.metadata?.completed_at || node?.metadata?.created_at || null,
    lastEventType: lastEvent?.type || node?.metadata?.source || null,
    startedAt,
    completedAt,
  };
}

export function projectWorkflowNode(node, nodeEvents = [], index = 0) {
  const payload = parseMaybeJson(node?.summary) || parseMaybeJson(node?.description);
  const messages = transcriptMessages(node, payload);
  const toolObservation = toolObservationFromMessage(latestMessage(messages, ["tool"])) || toolObservationFromMessage(payload);
  const semanticKind = classifySemanticKind(node, toolObservation);
  const summary = nodeSummary(node, semanticKind, messages, toolObservation);
  return {
    ...node,
    ...timelineFields(node, nodeEvents, index),
    title: displayTitle(node, semanticKind, toolObservation),
    rawTitle: node?.title || null,
    summary,
    kindLabel: KIND_LABELS[semanticKind] || humanizeName(node?.kind || "step"),
    semanticKind,
    toolName: toolObservation?.toolName || node?.metadata?.tool_name || null,
    ownerProfileName: node?.owner_profile_name || null,
    lastEventSummary: summary,
    detailSections: nodeDetailSections(node, semanticKind, summary, toolObservation),
    metadataBadges: nodeMetadataBadges(node, semanticKind, toolObservation),
    debugLabel: semanticKind === "tool" ? "工具原始输出" : "节点原始数据",
    debugPayload: nodeDebugPayload(node, payload, toolObservation),
  };
}
export function buildWorkflowItems(graph, events) {
  if (!graph?.nodes?.length) {
    return [];
  }
  const groupedEvents = nodeEventsById(events || []);
  return graph.nodes
    .map((node, index) => projectWorkflowNode(node, groupedEvents.get(node.node_id) || [], index))
    .sort((left, right) => {
      if (left.firstEventAt && right.firstEventAt) {
        return new Date(left.firstEventAt) - new Date(right.firstEventAt);
      }
      if (left.firstEventAt) {
        return -1;
      }
      if (right.firstEventAt) {
        return 1;
      }
      return left.orderIndex - right.orderIndex;
    });
}
function groupKey(updatedAt) {
  if (!updatedAt) {
    return "earlier";
  }
  const now = new Date();
  const value = new Date(updatedAt);
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const weekStart = new Date(todayStart);
  weekStart.setDate(todayStart.getDate() - 6);
  if (value >= todayStart) {
    return "today";
  }
  if (value >= weekStart) {
    return "week";
  }
  return "earlier";
}
export function groupSessionsByDate(sessions) {
  const groups = [{ key: "today", title: "今天", items: [] }, { key: "week", title: "近 7 天", items: [] }, { key: "earlier", title: "更早", items: [] }];
  const groupMap = Object.fromEntries(groups.map((group) => [group.key, group]));
  for (const session of sessions) {
    groupMap[groupKey(session.updated_at)].items.push(session);
  }
  return groups.filter((group) => group.items.length > 0);
}
