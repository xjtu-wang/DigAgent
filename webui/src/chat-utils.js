export const graphNodeStyles = {
  pending: "border-slate-200 bg-white text-slate-500",
  ready: "border-slate-300 bg-slate-50 text-slate-700",
  running: "border-emerald-300 bg-emerald-50 text-emerald-800 shadow-[0_16px_45px_rgba(22,101,52,0.12)]",
  waiting_approval: "border-orange-300 bg-orange-50 text-orange-800 shadow-[0_16px_45px_rgba(251,146,60,0.12)]",
  waiting_user_input: "border-amber-300 bg-amber-50 text-amber-900 shadow-[0_16px_45px_rgba(245,158,11,0.12)]",
  blocked: "border-orange-300 bg-orange-50 text-orange-800 shadow-[0_16px_45px_rgba(251,146,60,0.12)]",
  completed: "border-slate-300 bg-slate-50 text-slate-600",
  failed: "border-rose-300 bg-rose-50 text-rose-800",
  timed_out: "border-amber-400 bg-amber-100 text-amber-900",
  deprecated: "border-slate-300 bg-slate-100 text-slate-500",
};

export const statusStyles = {
  idle: "bg-slate-100 text-slate-700",
  active_turn: "bg-emerald-100 text-emerald-800",
  active_run: "bg-emerald-100 text-emerald-800",
  awaiting_approval: "bg-orange-100 text-orange-800",
  awaiting_user_input: "bg-amber-100 text-amber-900",
  archived: "bg-slate-200 text-slate-700",
  completed: "bg-slate-100 text-slate-700",
  failed: "bg-rose-100 text-rose-700",
  timed_out: "bg-amber-100 text-amber-900",
  cancelled: "bg-slate-200 text-slate-600",
  running: "bg-emerald-100 text-emerald-800",
};

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

export function buildWorkflowItems(graph, events) {
  if (!graph?.nodes?.length) {
    return [];
  }
  const groupedEvents = nodeEventsById(events || []);
  return graph.nodes
    .map((node, index) => {
      const nodeEvents = groupedEvents.get(node.node_id) || [];
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
        ...node,
        orderIndex: index,
        eventCount: nodeEvents.length,
        firstEventAt: firstEvent?.created_at || node?.metadata?.created_at || null,
        lastEventAt: lastEvent?.created_at || node?.metadata?.completed_at || node?.metadata?.created_at || null,
        lastEventType: lastEvent?.type || node?.metadata?.source || null,
        lastEventSummary: lastEvent?.data?.summary || node?.metadata?.derived_from || node?.metadata?.source || "",
        startedAt,
        completedAt,
        toolName: node?.metadata?.tool_name || null,
        ownerProfileName: node?.owner_profile_name || null,
      };
    })
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
  const groups = [
    { key: "today", title: "今天", items: [] },
    { key: "week", title: "近 7 天", items: [] },
    { key: "earlier", title: "更早", items: [] },
  ];
  const groupMap = Object.fromEntries(groups.map((group) => [group.key, group]));
  for (const session of sessions) {
    groupMap[groupKey(session.updated_at)].items.push(session);
  }
  return groups.filter((group) => group.items.length > 0);
}
