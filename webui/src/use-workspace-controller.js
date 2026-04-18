import { useEffect, useMemo, useRef, useState } from "react";
import { groupSessionsByDate, scopePayload } from "./chat-utils.js";
import { buildInspectorActivityEvents, buildInspectorGraph } from "./inspector-store.js";
import { emptyOverrides, normalizePermissionOverrides } from "./permissions-store.js";
import { buildPrimaryTimeline } from "./semantic-timeline.js";
import { createRuntimeDraft } from "./settings-store.js";
import { filterActivityEvents } from "./timeline-utils.js";
import { normalizeTurnEvent, normalizeTurns, TERMINAL_TURN_STATUSES } from "./turn-utils.js";

const SESSION_REFRESH_EVENT_TYPES = new Set([
  "assistant_message",
  "approval_required",
  "approval_resolved",
  "approval_expired",
  "approval_superseded",
  "awaiting_approval",
  "awaiting_user_input",
  "completed",
  "failed",
  "timed_out",
  "cancelled",
  "report_ready",
  "turn_started",
  "turn_status",
  "turn_updated",
  "turn_recorded",
]);

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || "request failed");
  }
  return payload;
}

function ensureOk(response, message) {
  if (!response.ok) {
    throw new Error(message);
  }
  return response;
}

function parseEventHistory(rawText) {
  return rawText
    .split("\n\n")
    .map((chunk) => chunk.trim())
    .filter(Boolean)
    .map((chunk) => normalizeTurnEvent(JSON.parse(chunk.replace(/^data:\s*/, ""))));
}

function sortMessages(messages) {
  return [...messages].sort((left, right) => new Date(left.created_at || 0) - new Date(right.created_at || 0));
}

function commitAssistantMessage(messages, payload) {
  const turnId = payload.turn_id || payload.data?.turn_id || null;
  const message = { message_id: payload.data.message_id, session_id: payload.session_id, turn_id: turnId, role: "assistant", sender: "sisyphus", content: payload.data.message, evidence_refs: payload.data.evidence_refs || [], artifact_refs: payload.data.artifact_refs || [], created_at: payload.created_at };
  if (messages.some((item) => item.message_id === message.message_id)) {
    return messages;
  }
  return sortMessages([...messages, message]);
}

function applySessionTitleUpdate(current, payload) {
  if (!current?.session_id || current.session_id !== payload.session_id) {
    return current;
  }
  return {
    ...current,
    title: payload.data?.title || current.title,
    title_status: payload.data?.title_status || current.title_status,
    title_source: payload.data?.title_source || current.title_source,
    updated_at: payload.created_at || current.updated_at,
  };
}

function applySessionSummaryTitleUpdate(sessions, payload) {
  return sessions.map((item) => item.session_id === payload.session_id ? {
    ...item,
    title: payload.data?.title || item.title,
    title_status: payload.data?.title_status || item.title_status,
    title_source: payload.data?.title_source || item.title_source,
    updated_at: payload.created_at || item.updated_at,
  } : item);
}

function shouldRefreshSession(payload) {
  return SESSION_REFRESH_EVENT_TYPES.has(payload.type);
}

function selectCurrentTurn(turns, focusTurnId, activeTurnId) {
  return turns.find((item) => item.turn_id === focusTurnId) || turns.find((item) => item.turn_id === activeTurnId) || turns[0] || null;
}

export function selectActiveTurn(turns, activeTurnId) {
  if (!activeTurnId) {
    return null;
  }
  return turns.find((item) => item.turn_id === activeTurnId) || null;
}

export function useWorkspaceController(appSettings) {
  const [sessions, setSessions] = useState([]);
  const [sessionSearch, setSessionSearch] = useState("");
  const [session, setSession] = useState(null);
  const [turns, setTurns] = useState([]);
  const [focusedTurnId, setFocusedTurnId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [events, setEvents] = useState([]);
  const [planGraphOverride, setPlanGraphOverride] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [task, setTask] = useState("");
  const [runtimeDraft, setRuntimeDraft] = useState(() => createRuntimeDraft(appSettings));
  const [expandedItems, setExpandedItems] = useState(new Set());
  const [evidenceItems, setEvidenceItems] = useState({});
  const [openEvidenceIds, setOpenEvidenceIds] = useState(new Set());
  const [reportsById, setReportsById] = useState({});
  const [openReportIds, setOpenReportIds] = useState(new Set());
  const [cveStatus, setCveStatus] = useState({ status: "idle" });
  const [cveQuery, setCveQuery] = useState("");
  const [cveResults, setCveResults] = useState([]);
  const [resolvingApprovalIds, setResolvingApprovalIds] = useState(() => new Set());
  const [permissionOverrides, setPermissionOverrides] = useState(() => emptyOverrides());
  const [requestPending, setRequestPending] = useState(false);
  const eventSourceRef = useRef(null);

  const activeTurn = useMemo(() => selectActiveTurn(turns, session?.active_turn_id), [session?.active_turn_id, turns]);
  const currentTurn = useMemo(() => selectCurrentTurn(turns, focusedTurnId, session?.active_turn_id), [focusedTurnId, session?.active_turn_id, turns]);
  const running = requestPending || Boolean(activeTurn && !TERMINAL_TURN_STATUSES.has(activeTurn.status));
  const primaryTimeline = useMemo(() => buildPrimaryTimeline(messages, events, turns, appSettings.chatPreferences.showKeySystemCards), [appSettings.chatPreferences.showKeySystemCards, events, messages, turns]);
  const activityEvents = useMemo(() => filterActivityEvents(buildInspectorActivityEvents(events, turns, messages, currentTurn?.turn_id)), [currentTurn?.turn_id, events, turns, messages]);
  const filteredSessions = useMemo(() => {
    const keyword = sessionSearch.trim().toLowerCase();
    return keyword ? sessions.filter((item) => `${item.title || ""} ${item.last_message_preview || ""}`.toLowerCase().includes(keyword)) : sessions;
  }, [sessionSearch, sessions]);
  const sessionGroups = useMemo(() => groupSessionsByDate(filteredSessions), [filteredSessions]);
  const evidenceState = useMemo(() => ({ items: evidenceItems, openIds: openEvidenceIds }), [evidenceItems, openEvidenceIds]);
  const resolvedApprovalIds = useMemo(() => new Set(events.filter((event) => ["approval_resolved", "approval_expired"].includes(event.type)).map((event) => event.data?.approval_id).filter(Boolean)), [events]);
  const supersededApprovals = useMemo(() => Object.fromEntries(events.filter((event) => event.type === "approval_superseded" && event.data?.old_approval_id).map((event) => [event.data.old_approval_id, { newApprovalId: event.data?.new_approval_id, reason: event.data?.reason }])), [events]);
  const supersededApprovalIds = useMemo(() => new Set(Object.keys(supersededApprovals)), [supersededApprovals]);
  const planGraph = useMemo(() => {
    if (planGraphOverride?.turn_id === currentTurn?.turn_id) {
      return planGraphOverride;
    }
    return buildInspectorGraph(currentTurn, messages);
  }, [currentTurn, messages, planGraphOverride]);
  const selectedGraphNode = useMemo(() => planGraph?.nodes?.find((node) => node.node_id === selectedNodeId) || planGraph?.nodes?.find((node) => node.is_active) || planGraph?.nodes?.[0] || null, [planGraph, selectedNodeId]);
  const pendingApprovals = activeTurn?.pending_approvals || [];
  const canDeleteCurrentSession = Boolean(session?.session_id) && !session?.active_turn_id;
  const canArchiveCurrentSession = Boolean(session?.session_id) && !session?.active_turn_id;

  useEffect(() => {
    setRuntimeDraft(createRuntimeDraft(appSettings));
  }, [appSettings]);

  useEffect(() => {
    if (planGraph?.nodes?.length && !planGraph.nodes.some((node) => node.node_id === selectedNodeId)) {
      const activeNode = planGraph.nodes.find((node) => node.is_active) || planGraph.nodes[0];
      setSelectedNodeId(activeNode?.node_id || null);
    }
  }, [planGraph, selectedNodeId]);

  async function loadReport(reportId) {
    if (!reportId || reportsById[reportId]) {
      return reportsById[reportId];
    }
    const payload = await readJson(await fetch(`/api/reports/${reportId}`));
    setReportsById((current) => ({ ...current, [reportId]: payload }));
    return payload;
  }

  function resetSessionView() {
    eventSourceRef.current?.close();
    setSession(null);
    setTurns([]);
    setFocusedTurnId(null);
    setMessages([]);
    setEvents([]);
    setPlanGraphOverride(null);
    setSelectedNodeId(null);
    setExpandedItems(new Set());
    setOpenEvidenceIds(new Set());
    setOpenReportIds(new Set());
    setPermissionOverrides(emptyOverrides());
  }

  async function hydrateSession(sessionId) {
    const [sessionResponse, messagesResponse, eventsResponse] = await Promise.all([
      fetch(`/api/sessions/${sessionId}`),
      fetch(`/api/sessions/${sessionId}/messages`),
      fetch(`/api/sessions/${sessionId}/events?history_only=true`),
    ]);
    ensureOk(sessionResponse, "会话加载失败");
    ensureOk(messagesResponse, "消息加载失败");
    ensureOk(eventsResponse, "事件历史加载失败");
    const [sessionPayload, messagePayload, rawEvents] = await Promise.all([sessionResponse.json(), messagesResponse.json(), eventsResponse.text()]);
    const normalizedTurns = normalizeTurns(sessionPayload.turns || []);
    setSession(sessionPayload);
    setTurns(normalizedTurns);
    setFocusedTurnId((current) => current && normalizedTurns.some((item) => item.turn_id === current) ? current : sessionPayload.active_turn_id || normalizedTurns[0]?.turn_id || null);
    setPermissionOverrides(normalizePermissionOverrides(sessionPayload.permission_overrides));
    setMessages(sortMessages(messagePayload));
    setEvents(parseEventHistory(rawEvents));
    setExpandedItems(new Set());
    setOpenEvidenceIds(new Set());
    setOpenReportIds(new Set());
    const currentReportId = sessionPayload.latest_report_id || sessionPayload.last_report_id || normalizedTurns.find((item) => item.turn_id === sessionPayload.active_turn_id)?.report_id;
    if (currentReportId) {
      await loadReport(currentReportId);
    }
  }

  async function loadSessions(preferredId = null, forceHydrate = false) {
    const payload = await readJson(await fetch("/api/sessions"));
    setSessions(payload);
    if ((forceHydrate || !session?.session_id) && payload.length > 0) {
      const preferred = preferredId && payload.some((item) => item.session_id === preferredId) ? preferredId : payload[0].session_id;
      await hydrateSession(preferred);
    } else if (!forceHydrate && session?.session_id) {
      const current = payload.find((item) => item.session_id === session.session_id);
      if (current) {
        setSession((existing) => ({ ...(existing || {}), ...current }));
      }
    }
    return payload;
  }

  useEffect(() => {
    void loadSessions(null, true);
  }, []);

  useEffect(() => {
    if (!session?.session_id) {
      return undefined;
    }
    eventSourceRef.current?.close();
    const source = new EventSource(`/api/sessions/${session.session_id}/events`);
    source.onmessage = async (event) => {
      const payload = normalizeTurnEvent(JSON.parse(event.data));
      if (payload.type === "assistant_message") {
        setMessages((current) => commitAssistantMessage(current, payload));
      } else if (payload.type === "session_title_updated") {
        setSession((current) => applySessionTitleUpdate(current, payload));
        setSessions((current) => applySessionSummaryTitleUpdate(current, payload));
      } else {
        setEvents((current) => current.some((item) => item.event_id === payload.event_id) ? current : [...current, payload]);
      }
      if (payload.type === "task_graph_updated") {
        setPlanGraphOverride({ ...payload.data, turn_id: payload.turn_id || payload.data?.turn_id || null });
      }
      if (payload.type === "cve_sync_updated") setCveStatus(payload.data);
      if (payload.type === "session_permissions_updated") setPermissionOverrides(normalizePermissionOverrides(payload.data));
      if (payload.data?.report_id) await loadReport(payload.data.report_id);
      if (shouldRefreshSession(payload)) await hydrateSession(session.session_id);
    };
    eventSourceRef.current = source;
    return () => source.close();
  }, [session?.session_id]);

  async function ensureSession(message) {
    if (session?.session_id) {
      return session.session_id;
    }
    const payload = await readJson(await fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "新会话", profile: runtimeDraft.profile, scope: scopePayload(runtimeDraft.repoPath, runtimeDraft.domain) }) }));
    await loadSessions(payload.session_id, true);
    return payload.session_id;
  }

  async function sendMessage() {
    if (!task.trim()) return;
    try {
      setRequestPending(true);
      const message = task.trim();
      const sessionId = await ensureSession(message);
      setMessages((current) => sortMessages([...current, { message_id: `local-${Date.now()}`, session_id: sessionId, turn_id: null, role: "user", sender: "user", content: message, evidence_refs: [], artifact_refs: [], created_at: new Date().toISOString() }]));
      setTask("");
      const payload = await readJson(await fetch(`/api/sessions/${sessionId}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content: message, profile: runtimeDraft.profile, scope: scopePayload(runtimeDraft.repoPath, runtimeDraft.domain), auto_approve: runtimeDraft.autoApprove }) }));
      if (payload.session) setSession(payload.session);
      await hydrateSession(sessionId);
      if (!payload.turn) setRequestPending(false);
    } catch (error) {
      setRequestPending(false);
      window.alert(error instanceof Error ? error.message : "消息发送失败");
    } finally {
      setRequestPending(false);
    }
  }

  async function resolveApproval(approval, approved) {
    const approvalId = approval.approval_id;
    if (resolvingApprovalIds.has(approvalId) || resolvedApprovalIds.has(approvalId) || supersededApprovalIds.has(approvalId)) return;
    setResolvingApprovalIds((current) => new Set(current).add(approvalId));
    try {
      await readJson(await fetch(`/api/approvals/${approvalId}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved, resolver: "webui" }) }));
      if (session?.session_id) await hydrateSession(session.session_id);
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "审批提交失败");
    } finally {
      setResolvingApprovalIds((current) => {
        const next = new Set(current);
        next.delete(approvalId);
        return next;
      });
    }
  }

  async function deleteSessionById(sessionId) {
    const target = sessions.find((item) => item.session_id === sessionId) || session;
    if (!target) return;
    if (target.active_turn_id || (session?.session_id === sessionId && session?.active_turn_id)) {
      window.alert("请先结束当前执行，再删除这个聊天。");
      return;
    }
    if (!window.confirm(`确认删除聊天“${target.title || "未命名会话"}”吗？\n\n这会删除消息、turn、审批、证据、报告和附件，且不可恢复。`)) return;
    await readJson(await fetch(`/api/sessions/${sessionId}`, { method: "DELETE" }));
    if (session?.session_id === sessionId) {
      resetSessionView();
      await loadSessions(null, true);
    } else {
      await loadSessions(session?.session_id);
    }
  }

  async function toggleArchive() {
    if (!session?.session_id) return;
    const endpoint = session.status === "archived" ? "unarchive" : "archive";
    const payload = await readJson(await fetch(`/api/sessions/${session.session_id}/${endpoint}`, { method: "POST" }));
    setSession(payload);
    await loadSessions(payload.session_id);
  }

  async function savePermissionOverrides(patch) {
    if (!session?.session_id) return null;
    try {
      const payload = await readJson(await fetch(`/api/sessions/${session.session_id}/permissions`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(patch) }));
      setPermissionOverrides(normalizePermissionOverrides(payload));
      return payload;
    } catch (error) {
      window.alert(error instanceof Error ? error.message : "权限保存失败");
      return null;
    }
  }

  async function cancelCurrentTurn() {
    if (!activeTurn || !session?.session_id) return;
    await readJson(await fetch(`/api/turns/${activeTurn.turn_id}/cancel`, { method: "POST" }));
    await hydrateSession(session.session_id);
  }

  async function toggleEvidence(evidenceId) {
    if (!evidenceItems[evidenceId]) {
      const response = await fetch(`/api/evidence/${evidenceId}`);
      if (response.ok) {
        const payload = await response.json();
        setEvidenceItems((current) => ({ ...current, [evidenceId]: payload }));
      }
    }
    setOpenEvidenceIds((current) => { const next = new Set(current); next.has(evidenceId) ? next.delete(evidenceId) : next.add(evidenceId); return next; });
  }

  async function toggleReport(reportId) {
    await loadReport(reportId);
    setOpenReportIds((current) => { const next = new Set(current); next.has(reportId) ? next.delete(reportId) : next.add(reportId); return next; });
  }

  function toggleItem(eventId) {
    setExpandedItems((current) => { const next = new Set(current); next.has(eventId) ? next.delete(eventId) : next.add(eventId); return next; });
  }

  async function syncCve() {
    setCveStatus((current) => ({ ...current, status: "running", running: true }));
    const response = await fetch("/api/cve/sync", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ max_records: 200 }) });
    const payload = await response.json().catch(() => ({}));
    setCveStatus(response.ok ? payload : { ...cveStatus, status: "failed", running: false, last_error: payload.detail || "sync failed" });
  }

  async function searchCve() {
    const response = await fetch(`/api/cve/search?query=${encodeURIComponent(cveQuery)}`);
    ensureOk(response, "CVE 搜索失败");
    const payload = await response.json();
    setCveResults(payload.items || []);
    setCveStatus(payload.state || cveStatus);
  }

  function startFreshSession() {
    resetSessionView();
    setTask("");
  }

  return {
    activityEvents,
    activeTurn,
    canArchiveCurrentSession,
    canDeleteCurrentSession,
    cancelCurrentTurn,
    currentTurn,
    cveQuery,
    cveResults,
    cveStatus,
    deleteSessionById,
    downloadReport: (reportId, format) => window.open(`/api/reports/${reportId}/download?format=${format}`, "_blank"),
    evidenceState,
    expandedItems,
    messages,
    openReportIds,
    pendingApprovals,
    permissionOverrides,
    planGraph,
    primaryTimeline,
    reportsById,
    resolveApproval,
    resolvedApprovalIds,
    resolvingApprovalIds,
    running,
    runtimeDraft,
    savePermissionOverrides,
    searchCve,
    selectTurn: setFocusedTurnId,
    selectedGraphNode,
    selectedNodeId,
    session,
    sessionGroups,
    sessionSearch,
    sendMessage,
    setCveQuery,
    setPermissionOverrides,
    setRuntimeDraft,
    setSelectedNodeId,
    setSessionSearch,
    setTask,
    startFreshSession,
    supersededApprovalIds,
    supersededApprovals,
    syncCve,
    task,
    toggleArchive,
    toggleEvidence,
    toggleItem,
    toggleReport,
    turns,
    hydrateSession,
  };
}
