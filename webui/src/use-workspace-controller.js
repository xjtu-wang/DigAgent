import { useEffect, useMemo, useRef, useState } from "react";
import { groupSessionsByDate, scopePayload } from "./chat-utils.js";
import { buildInspectorActivityEvents, buildInspectorGraph } from "./inspector-store.js";
import { emptyOverrides, normalizePermissionOverrides } from "./permissions-store.js";
import { buildPrimaryTimeline } from "./semantic-timeline.js";
import { createRuntimeDraft } from "./settings-store.js";
import { filterActivityEvents } from "./timeline-utils.js";
import { normalizeTurn, normalizeTurnEvent, normalizeTurns, TERMINAL_TURN_STATUSES } from "./turn-utils.js";

const PRIMARY_TIMELINE_EVENT_TYPES = [
  "assistant_chunk",
  "langgraph_tasks",
  "tool_result",
  "participant_handoff",
  "participant_message",
  "subagent",
  "approval_required",
  "approval_expired",
  "approval_superseded",
  "approval_resolved",
  "failed",
  "timed_out",
  "cancelled",
  "awaiting_user_input",
];
const SESSION_LIVE_EVENT_TYPES = [
  ...PRIMARY_TIMELINE_EVENT_TYPES,
  "assistant_message",
  "session_title_updated",
  "session_permissions_updated",
  "session_updated",
  "turn_updated",
];
const TURN_DETAIL_EVENT_TYPES = [
  ...PRIMARY_TIMELINE_EVENT_TYPES,
  "awaiting_approval",
  "completed",
  "turn_superseded",
  "task_node_started",
  "task_node_completed",
  "task_node_waiting_approval",
  "task_node_waiting_user_input",
  "graph_op_applied",
  "aggregate",
  "evidence_added",
  "report_ready",
  "export",
];

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
  const message = {
    message_id: payload.data.message_id,
    session_id: payload.session_id,
    turn_id: turnId,
    role: "assistant",
    sender: payload.data?.speaker_profile || "assistant",
    speaker_profile: payload.data?.speaker_profile || null,
    addressed_participants: payload.data?.addressed_participants || [],
    content: payload.data.message,
    evidence_refs: payload.data.evidence_refs || [],
    artifact_refs: payload.data.artifact_refs || [],
    created_at: payload.created_at,
  };
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
  return upsertSessionSummary(sessions, {
    session_id: payload.session_id,
    title: payload.data?.title,
    title_status: payload.data?.title_status,
    title_source: payload.data?.title_source,
    updated_at: payload.created_at,
  });
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

function createAbortError(message = "hydrate superseded") {
  try {
    return new DOMException(message, "AbortError");
  } catch {
    const error = new Error(message);
    error.name = "AbortError";
    return error;
  }
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function eventCursor(event) {
  if (event?.event_id) {
    return event.event_id;
  }
  if (!event) {
    return null;
  }
  return [event.created_at || "", event.turn_id || "", event.type || ""].join(":");
}

function mergeUniqueEvents(current, incoming) {
  const items = Array.isArray(current) ? current : [];
  const nextItems = Array.isArray(incoming) ? incoming : [incoming];
  const seen = new Set(items.map((item) => eventCursor(item)));
  const merged = [...items];
  for (const item of nextItems) {
    const cursor = eventCursor(item);
    if (!cursor || seen.has(cursor)) {
      continue;
    }
    seen.add(cursor);
    merged.push(item);
  }
  return merged;
}

function encodeEventTypes(types) {
  return encodeURIComponent(types.join(","));
}

function sessionLiveUrl(sessionId) {
  return `/api/sessions/${sessionId}/events?event_types=${encodeEventTypes(SESSION_LIVE_EVENT_TYPES)}`;
}

function turnDetailHistoryUrl(turnId) {
  return `/api/turns/${turnId}/events?history_only=true&event_types=${encodeEventTypes(TURN_DETAIL_EVENT_TYPES)}`;
}

function sortSessionsByUpdatedAt(items) {
  return [...items].sort((left, right) => new Date(right.updated_at || 0) - new Date(left.updated_at || 0));
}

function upsertSessionSummary(sessions, summary) {
  if (!summary?.session_id) {
    return sessions;
  }
  const index = sessions.findIndex((item) => item.session_id === summary.session_id);
  if (index === -1) {
    return sortSessionsByUpdatedAt([...sessions, summary]);
  }
  const next = [...sessions];
  next[index] = { ...next[index], ...summary };
  return sortSessionsByUpdatedAt(next);
}

function mergeTurnSnapshot(turns, snapshot) {
  const turn = normalizeTurn(snapshot);
  if (!turn.turn_id) {
    return turns;
  }
  const index = turns.findIndex((item) => item.turn_id === turn.turn_id);
  if (index === -1) {
    return normalizeTurns([...turns, turn]);
  }
  const next = [...turns];
  next[index] = normalizeTurn({ ...next[index], ...turn });
  return normalizeTurns(next);
}

function sessionPatchFromPayload(payload) {
  const patch = payload?.data?.session || payload?.session || null;
  return patch && typeof patch === "object" ? patch : null;
}

function turnPatchFromPayload(payload) {
  const patch = payload?.data?.turn || payload?.turn || null;
  return patch && typeof patch === "object" ? patch : null;
}

function createDeferred(sessionId) {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { sessionId, promise, resolve, reject };
}

export function createTailEventGate(initialCursor = null) {
  let tailCursor = initialCursor;
  let replaying = Boolean(initialCursor);
  return {
    reset(nextCursor = null) {
      tailCursor = nextCursor;
      replaying = Boolean(nextCursor);
    },
    shouldProcess(event) {
      if (!replaying) {
        return true;
      }
      if (eventCursor(event) === tailCursor) {
        replaying = false;
      }
      return false;
    },
  };
}

export function resolveHydrateTarget(sessionList, options = {}) {
  const { currentSessionId = null, forceHydrate = false, intendedSessionId = null, preferredId = null } = options;
  if (!sessionList.length || (!forceHydrate && currentSessionId)) {
    return null;
  }
  if (preferredId) {
    return sessionList.some((item) => item.session_id === preferredId) ? preferredId : null;
  }
  if (intendedSessionId) {
    return sessionList.some((item) => item.session_id === intendedSessionId) ? intendedSessionId : null;
  }
  if (currentSessionId) {
    return sessionList.some((item) => item.session_id === currentSessionId) ? currentSessionId : null;
  }
  return forceHydrate ? sessionList[0]?.session_id || null : null;
}

function rejectDeferred(deferred, message = "hydrate superseded") {
  if (deferred) {
    deferred.reject(createAbortError(message));
  }
}

export function createHydrationController(runHydrate) {
  let activeRequest = null;
  let epoch = 0;
  let queuedRequest = null;

  function start(sessionId) {
    const controller = new AbortController();
    const request = {
      controller,
      epoch: epoch + 1,
      isCurrent: () => activeRequest === request && epoch === request.epoch && !controller.signal.aborted,
      sessionId,
      signal: controller.signal,
    };
    epoch = request.epoch;
    activeRequest = request;
    return runHydrate(sessionId, request).finally(() => {
      if (activeRequest === request) {
        activeRequest = null;
      }
      if (!queuedRequest || queuedRequest.sessionId !== sessionId || controller.signal.aborted) {
        return;
      }
      const next = queuedRequest;
      queuedRequest = null;
      void start(next.sessionId).then(next.resolve, next.reject);
    });
  }

  return {
    cancel(sessionId = null) {
      if (activeRequest && (!sessionId || activeRequest.sessionId === sessionId)) {
        activeRequest.controller.abort();
      }
      if (queuedRequest && (!sessionId || queuedRequest.sessionId === sessionId)) {
        const next = queuedRequest;
        queuedRequest = null;
        rejectDeferred(next);
      }
    },
    request(sessionId) {
      if (!sessionId) {
        return Promise.resolve(null);
      }
      if (activeRequest?.sessionId === sessionId) {
        if (!queuedRequest) {
          queuedRequest = createDeferred(sessionId);
        }
        return queuedRequest.promise;
      }
      if (queuedRequest) {
        const next = queuedRequest;
        queuedRequest = null;
        rejectDeferred(next);
      }
      activeRequest?.controller.abort();
      return start(sessionId);
    },
  };
}

export function useWorkspaceController(appSettings) {
  const [sessions, setSessions] = useState([]);
  const [sessionSearch, setSessionSearch] = useState("");
  const [session, setSession] = useState(null);
  const [turns, setTurns] = useState([]);
  const [focusedTurnId, setFocusedTurnId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [sessionEvents, setSessionEvents] = useState([]);
  const [turnDetailsById, setTurnDetailsById] = useState({});
  const [planGraphOverride, setPlanGraphOverride] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [task, setTask] = useState("");
  const [runtimeDraft, setRuntimeDraft] = useState(() => createRuntimeDraft(appSettings));
  const [expandedItems, setExpandedItems] = useState(new Set());
  const [evidenceItems, setEvidenceItems] = useState({});
  const [openEvidenceIds, setOpenEvidenceIds] = useState(new Set());
  const [reportsById, setReportsById] = useState({});
  const [openReportIds, setOpenReportIds] = useState(new Set());
  const [resolvingApprovalIds, setResolvingApprovalIds] = useState(() => new Set());
  const [permissionOverrides, setPermissionOverrides] = useState(() => emptyOverrides());
  const [requestPending, setRequestPending] = useState(false);
  const [inspectorDemanded, setInspectorDemanded] = useState(false);
  const eventSourceRef = useRef(null);
  const currentSessionIdRef = useRef(null);
  const eventCursorRef = useRef(null);
  const hydrateControllerRef = useRef(null);
  const hydrateExecutorRef = useRef(null);
  const reportsByIdRef = useRef(reportsById);
  const sessionIntentRef = useRef(null);
  const turnDetailsByIdRef = useRef(turnDetailsById);
  const currentTurnIdRef = useRef(null);

  const activeTurn = useMemo(() => selectActiveTurn(turns, session?.active_turn_id), [session?.active_turn_id, turns]);
  const currentTurn = useMemo(() => selectCurrentTurn(turns, focusedTurnId, session?.active_turn_id), [focusedTurnId, session?.active_turn_id, turns]);
  const currentTurnEvents = useMemo(() => currentTurn?.turn_id ? turnDetailsById[currentTurn.turn_id]?.events || [] : [], [currentTurn?.turn_id, turnDetailsById]);
  const running = requestPending || Boolean(activeTurn && !TERMINAL_TURN_STATUSES.has(activeTurn.status));
  const primaryTimeline = useMemo(() => buildPrimaryTimeline(messages, sessionEvents, turns, {
    showKeySystemCards: appSettings.chatPreferences.showKeySystemCards,
    activeTurnId: activeTurn?.turn_id || null,
  }), [activeTurn?.turn_id, appSettings.chatPreferences.showKeySystemCards, messages, sessionEvents, turns]);
  const activityEvents = useMemo(() => filterActivityEvents(buildInspectorActivityEvents(currentTurnEvents, turns, messages, currentTurn?.turn_id)), [currentTurn?.turn_id, currentTurnEvents, turns, messages]);
  const filteredSessions = useMemo(() => {
    const keyword = sessionSearch.trim().toLowerCase();
    return keyword ? sessions.filter((item) => `${item.title || ""} ${item.last_message_preview || ""}`.toLowerCase().includes(keyword)) : sessions;
  }, [sessionSearch, sessions]);
  const sessionGroups = useMemo(() => groupSessionsByDate(filteredSessions), [filteredSessions]);
  const evidenceState = useMemo(() => ({ items: evidenceItems, openIds: openEvidenceIds }), [evidenceItems, openEvidenceIds]);
  const resolvedApprovalIds = useMemo(() => new Set(sessionEvents.filter((event) => ["approval_resolved", "approval_expired"].includes(event.type)).map((event) => event.data?.approval_id).filter(Boolean)), [sessionEvents]);
  const supersededApprovals = useMemo(() => Object.fromEntries(sessionEvents.filter((event) => event.type === "approval_superseded" && event.data?.old_approval_id).map((event) => [event.data.old_approval_id, { newApprovalId: event.data?.new_approval_id, reason: event.data?.reason }])), [sessionEvents]);
  const supersededApprovalIds = useMemo(() => new Set(Object.keys(supersededApprovals)), [supersededApprovals]);
  const planGraph = useMemo(() => {
    if (planGraphOverride?.turn_id === currentTurn?.turn_id) {
      return planGraphOverride;
    }
    if (currentTurn?.turn_id && turnDetailsById[currentTurn.turn_id]?.graph) {
      return turnDetailsById[currentTurn.turn_id].graph;
    }
    return buildInspectorGraph(currentTurn, messages);
  }, [currentTurn, messages, planGraphOverride, turnDetailsById]);
  const selectedGraphNode = useMemo(() => planGraph?.nodes?.find((node) => node.node_id === selectedNodeId) || planGraph?.nodes?.find((node) => node.is_active) || planGraph?.nodes?.[0] || null, [planGraph, selectedNodeId]);
  const pendingApprovals = activeTurn?.pending_approvals || [];
  const canDeleteCurrentSession = Boolean(session?.session_id) && !session?.active_turn_id;
  const canArchiveCurrentSession = Boolean(session?.session_id) && !session?.active_turn_id;

  useEffect(() => {
    setRuntimeDraft(createRuntimeDraft(appSettings));
  }, [appSettings]);

  useEffect(() => {
    currentSessionIdRef.current = session?.session_id || null;
  }, [session?.session_id]);

  useEffect(() => {
    turnDetailsByIdRef.current = turnDetailsById;
  }, [turnDetailsById]);

  useEffect(() => {
    currentTurnIdRef.current = currentTurn?.turn_id || null;
  }, [currentTurn?.turn_id]);

  useEffect(() => {
    reportsByIdRef.current = reportsById;
  }, [reportsById]);

  useEffect(() => {
    if (planGraph?.nodes?.length && !planGraph.nodes.some((node) => node.node_id === selectedNodeId)) {
      const activeNode = planGraph.nodes.find((node) => node.is_active) || planGraph.nodes[0];
      setSelectedNodeId(activeNode?.node_id || null);
    }
  }, [planGraph, selectedNodeId]);

  async function loadReport(reportId, signal = undefined) {
    if (!reportId || reportsByIdRef.current[reportId]) {
      return reportsByIdRef.current[reportId] || null;
    }
    const payload = await readJson(await fetch(`/api/reports/${reportId}`, { signal }));
    if (signal?.aborted) {
      return null;
    }
    setReportsById((current) => current[reportId] ? current : { ...current, [reportId]: payload });
    return payload;
  }

  function resetSessionView() {
    hydrateControllerRef.current?.cancel();
    eventSourceRef.current?.close();
    eventSourceRef.current = null;
    currentSessionIdRef.current = null;
    eventCursorRef.current = null;
    sessionIntentRef.current = null;
    setSession(null);
    setTurns([]);
    setFocusedTurnId(null);
    setMessages([]);
    setSessionEvents([]);
    setTurnDetailsById({});
    setPlanGraphOverride(null);
    setSelectedNodeId(null);
    setExpandedItems(new Set());
    setOpenEvidenceIds(new Set());
    setOpenReportIds(new Set());
    setPermissionOverrides(emptyOverrides());
  }

  hydrateExecutorRef.current = async (sessionId, request) => {
    const workspacePayload = await readJson(await fetch(`/api/sessions/${sessionId}/workspace`, { signal: request.signal }));
    if (!request.isCurrent() || sessionIntentRef.current !== sessionId) {
      return null;
    }
    const sessionPayload = workspacePayload.session || null;
    const messagePayload = Array.isArray(workspacePayload.messages) ? workspacePayload.messages : [];
    if (!sessionPayload?.session_id) {
      throw new Error("会话加载失败");
    }
    const normalizedTurns = normalizeTurns(sessionPayload.turns || []);
    eventCursorRef.current = null;
    currentSessionIdRef.current = sessionPayload.session_id;
    setSession(sessionPayload);
    setTurns(normalizedTurns);
    setFocusedTurnId((current) => current && normalizedTurns.some((item) => item.turn_id === current) ? current : sessionPayload.active_turn_id || normalizedTurns[0]?.turn_id || null);
    setPermissionOverrides(normalizePermissionOverrides(sessionPayload.permission_overrides));
    setMessages(sortMessages(messagePayload));
    setSessionEvents([]);
    setTurnDetailsById({});
    setExpandedItems(new Set());
    setOpenEvidenceIds(new Set());
    setOpenReportIds(new Set());
    const currentReportId = sessionPayload.latest_report_id || sessionPayload.last_report_id || normalizedTurns.find((item) => item.turn_id === sessionPayload.active_turn_id)?.report_id;
    if (currentReportId) {
      await loadReport(currentReportId, request.signal);
    }
    if (!request.isCurrent() || sessionIntentRef.current !== sessionId) {
      return null;
    }
    return { events: [], session: sessionPayload };
  };

  if (!hydrateControllerRef.current) {
    hydrateControllerRef.current = createHydrationController((sessionId, request) => hydrateExecutorRef.current(sessionId, request));
  }

  async function hydrateSession(sessionId) {
    if (!sessionId) {
      return null;
    }
    sessionIntentRef.current = sessionId;
    try {
      return await hydrateControllerRef.current.request(sessionId);
    } catch (error) {
      if (isAbortError(error)) {
        return null;
      }
      throw error;
    }
  }

  async function loadSessions(preferredId = null, forceHydrate = false) {
    const payload = await readJson(await fetch("/api/sessions"));
    setSessions(payload);
    const hydrateTarget = resolveHydrateTarget(payload, {
      currentSessionId: currentSessionIdRef.current,
      forceHydrate,
      intendedSessionId: sessionIntentRef.current,
      preferredId,
    });
    if (hydrateTarget) {
      await hydrateSession(hydrateTarget);
    } else if (!forceHydrate && currentSessionIdRef.current) {
      const current = payload.find((item) => item.session_id === currentSessionIdRef.current);
      if (current) {
        setSession((existing) => ({ ...(existing || {}), ...current }));
      }
    }
    return payload;
  }

  useEffect(() => {
    void loadSessions(null, true);
  }, []);

  useEffect(() => () => hydrateControllerRef.current?.cancel(), []);

  useEffect(() => {
    if (!session?.session_id) {
      return undefined;
    }
    eventSourceRef.current?.close();
    const source = new EventSource(sessionLiveUrl(session.session_id));
    const tailGate = createTailEventGate();
    source.onopen = () => {
      tailGate.reset(null);
    };
    source.onmessage = async (event) => {
      const payload = normalizeTurnEvent(JSON.parse(event.data));
      if (!tailGate.shouldProcess(payload)) {
        return;
      }
      eventCursorRef.current = eventCursor(payload);
      if (payload.type === "assistant_message") {
        setMessages((current) => commitAssistantMessage(current, payload));
      } else if (payload.type === "session_title_updated") {
        setSession((current) => applySessionTitleUpdate(current, payload));
        setSessions((current) => applySessionSummaryTitleUpdate(current, payload));
      } else if (payload.type === "session_updated") {
        const patch = sessionPatchFromPayload(payload);
        if (patch) {
          setSession((current) => current?.session_id === patch.session_id ? { ...current, ...patch } : current);
          setSessions((current) => upsertSessionSummary(current, patch));
        }
      } else if (payload.type === "turn_updated") {
        const patch = turnPatchFromPayload(payload);
        if (patch) {
          setTurns((current) => mergeTurnSnapshot(current, patch));
          if (patch.report_id) {
            void loadReport(patch.report_id);
          }
        }
      }
      if (PRIMARY_TIMELINE_EVENT_TYPES.includes(payload.type)) {
        setSessionEvents((current) => mergeUniqueEvents(current, payload));
      }
      if (payload.turn_id && (turnDetailsByIdRef.current[payload.turn_id] || currentTurnIdRef.current === payload.turn_id)) {
        setTurnDetailsById((current) => {
          const detail = current[payload.turn_id] || { events: [], graph: null };
          return {
            ...current,
            [payload.turn_id]: {
              ...detail,
              events: mergeUniqueEvents(detail.events, payload),
            },
          };
        });
      }
      if (payload.type === "task_graph_updated") {
        const graphPayload = { ...payload.data, turn_id: payload.turn_id || payload.data?.turn_id || null };
        setPlanGraphOverride(graphPayload);
        if (graphPayload.turn_id) {
          setTurnDetailsById((current) => {
            const detail = current[graphPayload.turn_id] || { events: [], graph: null };
            return {
              ...current,
              [graphPayload.turn_id]: {
                ...detail,
                graph: graphPayload,
              },
            };
          });
        }
      }
      if (payload.type === "session_permissions_updated") {
        setPermissionOverrides(normalizePermissionOverrides(payload.data));
      }
      if (payload.data?.report_id) await loadReport(payload.data.report_id);
    };
    eventSourceRef.current = source;
    return () => {
      source.close();
      if (eventSourceRef.current === source) {
        eventSourceRef.current = null;
      }
    };
  }, [session?.session_id]);

  async function loadTurnDetails(sessionId, turnId, signal = undefined) {
    if (!sessionId || !turnId) {
      return null;
    }
    const cached = turnDetailsByIdRef.current[turnId];
    if (cached?.events?.length && cached?.graph) {
      return cached;
    }
    const [eventsResponse, graphResponse] = await Promise.all([
      fetch(turnDetailHistoryUrl(turnId), { signal }),
      fetch(`/api/turns/${turnId}/graph`, { signal }),
    ]);
    ensureOk(eventsResponse, "执行历史加载失败");
    ensureOk(graphResponse, "执行流程加载失败");
    const [rawEvents, graphPayload] = await Promise.all([eventsResponse.text(), graphResponse.json()]);
    if (signal?.aborted || currentSessionIdRef.current !== sessionId || sessionIntentRef.current !== sessionId) {
      return null;
    }
    const detail = {
      events: parseEventHistory(rawEvents),
      graph: graphPayload,
    };
    setTurnDetailsById((current) => {
      const existing = current[turnId] || { events: [], graph: null };
      return {
        ...current,
        [turnId]: {
          events: mergeUniqueEvents(existing.events, detail.events),
          graph: detail.graph || existing.graph,
        },
      };
    });
    return detail;
  }

  useEffect(() => {
    if (!inspectorDemanded || !session?.session_id || !currentTurn?.turn_id) {
      return undefined;
    }
    const controller = new AbortController();
    void loadTurnDetails(session.session_id, currentTurn.turn_id, controller.signal).catch((error) => {
      if (!isAbortError(error)) {
        console.error(error);
      }
    });
    return () => controller.abort();
  }, [currentTurn?.turn_id, inspectorDemanded, session?.session_id]);

  async function ensureSession(message) {
    if (session?.session_id) {
      return session.session_id;
    }
    const payload = await readJson(await fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: "新会话", profile: runtimeDraft.profile, scope: scopePayload(runtimeDraft.repoPath, runtimeDraft.domain) }) }));
    await loadSessions(payload.session_id, true);
    return payload.session_id;
  }

  async function sendMessage(options = {}) {
    const message = typeof options.content === "string" ? options.content.trim() : task.trim();
    const mentions = Array.isArray(options.mentions) ? options.mentions.filter(Boolean) : [];
    if (!message) return;
    try {
      setRequestPending(true);
      const sessionId = await ensureSession(message);
      setMessages((current) => sortMessages([...current, {
        message_id: `local-${Date.now()}`,
        session_id: sessionId,
        turn_id: null,
        role: "user",
        sender: "user",
        speaker_profile: "user",
        mentions,
        addressed_participants: mentions,
        content: message,
        evidence_refs: [],
        artifact_refs: [],
        created_at: new Date().toISOString(),
      }]));
      setTask("");
      const payload = await readJson(await fetch(`/api/sessions/${sessionId}/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: message,
          profile: runtimeDraft.profile,
          scope: scopePayload(runtimeDraft.repoPath, runtimeDraft.domain),
          auto_approve: runtimeDraft.autoApprove,
          mentions,
        }),
      }));
      if (payload.session) {
        setSession((current) => current?.session_id === payload.session.session_id ? { ...current, ...payload.session } : payload.session);
        setSessions((current) => upsertSessionSummary(current, payload.session));
      }
      if (payload.turn) {
        setTurns((current) => mergeTurnSnapshot(current, payload.turn));
        setFocusedTurnId(payload.turn.turn_id);
        if (payload.turn.report_id) {
          void loadReport(payload.turn.report_id);
        }
      }
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }
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
    } catch (error) {
      if (isAbortError(error)) {
        return;
      }
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
    const payload = await readJson(await fetch(`/api/turns/${activeTurn.turn_id}/cancel`, { method: "POST" }));
    setTurns((current) => mergeTurnSnapshot(current, payload));
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

  function toggleItem(eventId, turnId = null) {
    const opening = !expandedItems.has(eventId);
    setExpandedItems((current) => { const next = new Set(current); next.has(eventId) ? next.delete(eventId) : next.add(eventId); return next; });
    if (opening && session?.session_id && turnId) {
      void loadTurnDetails(session.session_id, turnId).catch((error) => {
        if (!isAbortError(error)) {
          console.error(error);
        }
      });
    }
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
    setInspectorDemanded,
    selectTurn: setFocusedTurnId,
    selectedGraphNode,
    selectedNodeId,
    session,
    sessionGroups,
    sessionSearch,
    sendMessage,
    setPermissionOverrides,
    setRuntimeDraft,
    setSelectedNodeId,
    setSessionSearch,
    setTask,
    startFreshSession,
    supersededApprovalIds,
    supersededApprovals,
    task,
    toggleArchive,
    toggleEvidence,
    toggleItem,
    toggleReport,
    turns,
    hydrateSession,
  };
}
