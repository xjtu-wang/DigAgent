import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  Bot,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Download,
  Eye,
  FileSearch,
  GitBranchPlus,
  LoaderCircle,
  MessageSquareText,
  Plus,
  RefreshCw,
  Search,
  Shield,
  SquareTerminal,
  XCircle,
} from "lucide-react";
import { Badge, Button, Input, Textarea } from "./components/ui";

const CHAT_EVENT_TYPES = new Set([
  "plan",
  "task_node_started",
  "task_node_completed",
  "task_node_waiting_approval",
  "graph_op_applied",
  "approval_required",
  "approval_resolved",
  "tool_result",
  "evidence_added",
  "subagent",
  "aggregate",
  "report_ready",
  "export",
  "completed",
  "failed",
]);

const systemEventLabels = {
  plan: "任务规划",
  task_node_started: "节点开始",
  task_node_completed: "节点完成",
  task_node_waiting_approval: "节点等待审批",
  task_node_waiting_user_input: "节点等待输入",
  graph_op_applied: "任务图更新",
  approval_required: "等待审批",
  approval_resolved: "审批完成",
  tool_result: "工具结果",
  evidence_added: "新增证据",
  subagent: "子 Agent",
  aggregate: "汇总",
  report_ready: "报告生成",
  export: "导出完成",
  awaiting_user_input: "等待补充信息",
  completed: "任务完成",
  failed: "任务失败",
};

const graphNodeStyles = {
  pending: "border-slate-200 bg-white text-slate-500",
  ready: "border-violet-200 bg-violet-50 text-violet-700 shadow-[0_12px_30px_rgba(124,58,237,0.08)]",
  running: "border-sky-300 bg-sky-50 text-sky-700 shadow-[0_12px_30px_rgba(14,165,233,0.12)]",
  waiting_approval: "border-orange-300 bg-orange-50 text-orange-800 shadow-[0_12px_30px_rgba(249,115,22,0.12)]",
  waiting_user_input: "border-amber-300 bg-amber-50 text-amber-800 shadow-[0_12px_30px_rgba(245,158,11,0.12)]",
  blocked: "border-orange-300 bg-orange-50 text-orange-800 shadow-[0_12px_30px_rgba(249,115,22,0.12)]",
  completed: "border-emerald-300 bg-emerald-50 text-emerald-800",
  failed: "border-rose-300 bg-rose-50 text-rose-800",
  deprecated: "border-slate-300 bg-slate-100 text-slate-500",
};

const statusStyles = {
  idle: "bg-slate-100 text-slate-700",
  active_run: "bg-sky-100 text-sky-700",
  awaiting_approval: "bg-orange-100 text-orange-800",
  awaiting_user_input: "bg-amber-100 text-amber-800",
  archived: "bg-slate-200 text-slate-700",
  completed: "bg-emerald-100 text-emerald-700",
  failed: "bg-rose-100 text-rose-700",
  cancelled: "bg-slate-200 text-slate-600",
};

function scopePayload(repoPath, domain) {
  return {
    repo_paths: repoPath ? [repoPath] : [],
    allowed_domains: domain ? [domain] : [],
    artifacts: [],
  };
}

function stableStringify(value) {
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  }
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${stableStringify(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

async function digestPayload(value) {
  const bytes = new TextEncoder().encode(stableStringify(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
  return `sha256:${hex}`;
}

async function buildApprovalToken(approval, approved, resolver) {
  return digestPayload({
    approval_id: approval.approval_id,
    action_id: approval.challenge.action_id,
    action_digest: approval.challenge.action_digest,
    challenge: approval.challenge.challenge,
    approved,
    resolver,
  });
}

function formatTime(value) {
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

function compactText(value, limit = 96) {
  if (!value) {
    return "";
  }
  const compact = value.replace(/\s+/g, " ").trim();
  if (compact.length <= limit) {
    return compact;
  }
  return `${compact.slice(0, limit - 1).trimEnd()}…`;
}

function graphNodeQuestion(node) {
  return node?.metadata?.question || node?.block_reason || node?.summary || node?.description || "";
}

function mergeHistory(messages, events) {
  const messageEntries = messages.map((message) => ({
    event_id: `msg-${message.message_id}`,
    session_id: message.session_id,
    run_id: message.run_id,
    type: message.role === "user" ? "local_user" : "assistant_message",
    created_at: message.created_at,
    data: {
      message: message.content,
      message_id: message.message_id,
      evidence_refs: message.evidence_refs || [],
      artifact_refs: message.artifact_refs || [],
    },
  }));
  const systemEntries = events.filter((event) => CHAT_EVENT_TYPES.has(event.type));
  return [...messageEntries, ...systemEntries].sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
}

function eventSummary(item) {
  const data = item.data || {};
  if (item.type === "plan") {
    return `已生成 ${data.nodes?.length || 0} 个任务节点`;
  }
  if (item.type === "task_node_started") {
    return data.title || data.node_id || "节点开始";
  }
  if (item.type === "task_node_completed") {
    return data.title || data.node_id || "节点完成";
  }
  if (item.type === "task_node_waiting_approval") {
    return data.reason || "节点等待审批";
  }
  if (item.type === "task_node_waiting_user_input") {
    return data.question || data.prompt || "节点等待用户输入";
  }
  if (item.type === "graph_op_applied") {
    return data.op_type || "任务图已更新";
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
    return "已完成证据汇总";
  }
  if (item.type === "report_ready") {
    return `报告 ${data.report_id || ""} 已生成`;
  }
  if (item.type === "export") {
    return "PDF 导出已完成";
  }
  if (item.type === "awaiting_user_input") {
    return data.question || data.prompt || "等待用户补充信息";
  }
  if (item.type === "completed") {
    return "任务已完成";
  }
  if (item.type === "failed") {
    return data.error || "任务执行失败";
  }
  if (item.type === "approval_resolved") {
    return data.status === "approved" ? "审批已通过，任务继续执行" : "审批已拒绝";
  }
  return systemEventLabels[item.type] || item.type;
}

function StatusPill({ status }) {
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${statusStyles[status] || "bg-slate-100 text-slate-700"}`}>{status ? status.replaceAll("_", " ") : "idle"}</span>;
}

function ApprovalCard({ approval, onResolve, compact = false }) {
  return (
    <div className={`rounded-2xl border border-orange-200 bg-orange-50 p-4 ${compact ? "text-sm" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-2">
          <div className="flex items-center gap-2 text-orange-900">
            <CircleAlert size={16} />
            <div className="font-medium">{approval.name}</div>
          </div>
          <div className="text-sm text-orange-800">{approval.reason}</div>
        </div>
        <Badge className="bg-orange-100 text-orange-900">{approval.approval_id}</Badge>
      </div>
      <div className="mt-3 rounded-xl bg-white/70 p-3 text-xs text-orange-900">
        <div>Action: {approval.action_id}</div>
        <div className="mt-1 break-all">Digest: {approval.challenge?.action_digest || "n/a"}</div>
      </div>
      <div className="mt-4 flex gap-2">
        <Button onClick={() => onResolve(approval, true)}>批准</Button>
        <Button variant="danger" onClick={() => onResolve(approval, false)}>
          拒绝
        </Button>
      </div>
    </div>
  );
}

function EvidenceInline({ evidence, onOpenArtifact }) {
  return (
    <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-4 text-sm text-slate-700 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-ink">{evidence.title}</div>
          <div className="mt-1 text-xs text-slate-500">{evidence.evidence_id}</div>
        </div>
        <Badge>{evidence.type}</Badge>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{evidence.summary}</p>
      {evidence.structured_facts?.length ? (
        <div className="mt-3 rounded-xl bg-slate-50 p-3">
          <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500">Facts</div>
          <div className="grid gap-2">
            {evidence.structured_facts.map((fact, index) => (
              <div key={`${evidence.evidence_id}-${index}`} className="flex items-start justify-between gap-3 text-xs text-slate-700">
                <span className="font-medium text-slate-500">{fact.key}</span>
                <span className="text-right">{String(fact.value)}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {evidence.artifacts?.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {evidence.artifacts.map((artifact) => (
            <Button key={artifact.artifact_id} variant="secondary" className="h-9" onClick={() => onOpenArtifact(artifact.artifact_id)}>
              <Eye size={14} className="mr-2" />
              {artifact.kind}
            </Button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ReportInline({ report, onDownload }) {
  return (
    <div className="mt-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-medium text-ink">{report.title}</div>
          <div className="mt-1 text-xs text-slate-500">{report.report_id}</div>
        </div>
        <Badge>{report.kind}</Badge>
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{report.summary}</p>
      {report.findings?.length ? (
        <div className="mt-3 grid gap-3">
          {report.findings.map((finding) => (
            <div key={finding.finding_id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
              <div className="flex items-center justify-between gap-3">
                <div className="font-medium text-ink">{finding.title}</div>
                <Badge className="bg-white text-slate-700">{finding.severity}</Badge>
              </div>
              <p className="mt-2 text-sm text-slate-700">{finding.claim}</p>
            </div>
          ))}
        </div>
      ) : null}
      {report.markdown ? (
        <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
          <summary className="cursor-pointer text-sm font-medium text-slate-700">查看 Markdown</summary>
          <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-700">{report.markdown}</pre>
        </details>
      ) : null}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="secondary" onClick={() => onDownload(report.report_id, "markdown")}>
          <Download size={14} className="mr-2" />
          Markdown
        </Button>
        <Button variant="secondary" onClick={() => onDownload(report.report_id, "pdf")}>
          <Download size={14} className="mr-2" />
          PDF
        </Button>
      </div>
    </div>
  );
}

function ChatMessage({
  item,
  expandedItems,
  toggleItem,
  evidenceState,
  onToggleEvidence,
  onResolveApproval,
  reportsById,
  reportOpenIds,
  onToggleReport,
  onDownloadReport,
}) {
  const isUser = item.type === "local_user";
  const isAssistant = item.type === "assistant_message";
  const evidenceRefs = item.data?.evidence_refs || (item.data?.evidence_id ? [item.data.evidence_id] : []);
  const reportId = item.data?.report_id;

  if (isUser || isAssistant) {
    return (
      <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
        <div className={`max-w-3xl rounded-[1.6rem] px-5 py-4 shadow-sm ${isUser ? "bg-ink text-white" : "border border-slate-200 bg-white text-slate-800"}`}>
          <div className="mb-2 flex items-center gap-2 text-xs opacity-70">
            {isAssistant ? <Bot size={14} /> : <MessageSquareText size={14} />}
            <span>{isAssistant ? "Sisyphus" : "你"}</span>
            <span>{formatTime(item.created_at)}</span>
          </div>
          <div className="whitespace-pre-wrap text-sm leading-6">{item.data.message}</div>
          {evidenceRefs.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {evidenceRefs.map((evidenceId) => (
                <button
                  key={`${item.event_id}-${evidenceId}`}
                  className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${isUser ? "bg-white/10 text-white" : "bg-slate-100 text-slate-700"}`}
                  onClick={() => onToggleEvidence(evidenceId)}
                >
                  <Eye size={12} />
                  {evidenceId}
                </button>
              ))}
            </div>
          ) : null}
          {evidenceRefs.map((evidenceId) => {
            const evidence = evidenceState.items[evidenceId];
            if (!evidenceState.openIds.has(evidenceId) || !evidence) {
              return null;
            }
            return <EvidenceInline key={`evidence-inline-${evidenceId}`} evidence={evidence} onOpenArtifact={(artifactId) => window.open(`/api/artifacts/${artifactId}/content`, "_blank")} />;
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="w-full max-w-3xl rounded-[1.6rem] border border-slate-200 bg-white shadow-sm">
        <div className="flex items-center justify-between gap-3 px-5 py-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-ink">
              <SquareTerminal size={15} />
              <span>{systemEventLabels[item.type] || item.type}</span>
            </div>
            <div className="mt-1 text-sm text-slate-600">{eventSummary(item)}</div>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">{formatTime(item.created_at)}</span>
            {item.type !== "approval_required" ? (
              <button className="rounded-full p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700" onClick={() => toggleItem(item.event_id)}>
                {expandedItems.has(item.event_id) ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
            ) : null}
          </div>
        </div>
        <div className="border-t border-slate-100 px-5 py-4">
          {item.type === "approval_required" ? <ApprovalCard approval={item.data} onResolve={onResolveApproval} compact /> : null}
          {item.type !== "approval_required" && expandedItems.has(item.event_id) ? (
            <pre className="overflow-x-auto whitespace-pre-wrap rounded-2xl bg-slate-50 p-4 text-xs text-slate-700">{JSON.stringify(item.data, null, 2)}</pre>
          ) : null}
          {evidenceRefs.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {evidenceRefs.map((evidenceId) => (
                <button
                  key={`${item.event_id}-${evidenceId}`}
                  className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700"
                  onClick={() => onToggleEvidence(evidenceId)}
                >
                  <Eye size={12} />
                  {evidenceId}
                </button>
              ))}
            </div>
          ) : null}
          {evidenceRefs.map((evidenceId) => {
            const evidence = evidenceState.items[evidenceId];
            if (!evidenceState.openIds.has(evidenceId) || !evidence) {
              return null;
            }
            return <EvidenceInline key={`system-evidence-${evidenceId}`} evidence={evidence} onOpenArtifact={(artifactId) => window.open(`/api/artifacts/${artifactId}/content`, "_blank")} />;
          })}
          {reportId ? (
            <div className="mt-3">
              <Button variant="secondary" onClick={() => onToggleReport(reportId)}>
                <FileSearch size={14} className="mr-2" />
                {reportOpenIds.has(reportId) ? "收起报告" : "查看报告"}
              </Button>
              {reportOpenIds.has(reportId) && reportsById[reportId] ? <ReportInline report={reportsById[reportId]} onDownload={onDownloadReport} /> : null}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function GraphCanvas({ graph, selectedNodeId, onSelect }) {
  if (!graph?.nodes?.length) {
    return (
      <div className="flex h-[420px] items-center justify-center rounded-[2rem] border border-dashed border-slate-300 bg-white text-sm text-slate-500">
        当前没有活跃任务图。
      </div>
    );
  }

  const columns = Math.min(3, Math.max(graph.nodes.length, 1));
  const cardWidth = 240;
  const cardHeight = 130;
  const gapX = 42;
  const gapY = 44;
  const positions = graph.nodes.map((node, index) => {
    const row = Math.floor(index / columns);
    const rawColumn = index % columns;
    const column = row % 2 === 0 ? rawColumn : columns - rawColumn - 1;
    return {
      ...node,
      x: 24 + column * (cardWidth + gapX),
      y: 24 + row * (cardHeight + gapY),
    };
  });
  const rows = Math.ceil(graph.nodes.length / columns);
  const width = 48 + columns * cardWidth + (columns - 1) * gapX;
  const height = 48 + rows * cardHeight + (rows - 1) * gapY;
  const byId = Object.fromEntries(positions.map((node) => [node.node_id, node]));

  return (
    <div className="h-full overflow-auto rounded-[2rem] border border-slate-200 bg-white px-4 py-4 shadow-sm">
      <div className="relative min-w-max" style={{ width, height }}>
        <svg width={width} height={height} className="absolute left-0 top-0 overflow-visible">
          {graph.edges.map((edge) => {
            const source = byId[edge.source];
            const target = byId[edge.target];
            if (!source || !target) {
              return null;
            }
            const startX = source.x + cardWidth / 2;
            const startY = source.y + cardHeight;
            const endX = target.x + cardWidth / 2;
            const endY = target.y;
            const controlY = startY + (endY - startY) / 2;
            return <path key={`${edge.source}-${edge.target}`} d={`M ${startX} ${startY} C ${startX} ${controlY} ${endX} ${controlY} ${endX} ${endY}`} fill="none" stroke="#cbd5e1" strokeWidth="2" />;
          })}
        </svg>
        {positions.map((node) => (
          <button
            key={node.node_id}
            type="button"
            onClick={() => onSelect(node.node_id)}
            className={`absolute rounded-3xl border p-4 text-left transition hover:-translate-y-0.5 ${graphNodeStyles[node.status] || graphNodeStyles.pending} ${selectedNodeId === node.node_id ? "ring-2 ring-ink/15" : ""}`}
            style={{ width: cardWidth, height: cardHeight, left: node.x, top: node.y }}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-medium">{node.title}</div>
                <div className="mt-1 text-xs opacity-75">{node.kind}</div>
              </div>
              {node.is_active ? <Badge className="bg-white/70 text-slate-700">active</Badge> : null}
            </div>
            <p
              className="mt-3 text-xs opacity-80"
              style={{
                display: "-webkit-box",
                WebkitLineClamp: 3,
                WebkitBoxOrient: "vertical",
                overflow: "hidden",
              }}
            >
              {node.status === "waiting_user_input" ? graphNodeQuestion(node) : node.summary || node.description}
            </p>
          </button>
        ))}
      </div>
    </div>
  );
}

function SessionListItem({ session, active, onSelect }) {
  return (
    <button
      type="button"
      onClick={() => onSelect(session.session_id)}
      className={`w-full rounded-2xl px-4 py-3 text-left transition ${active ? "bg-white text-ink shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:bg-white/60"}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{session.title || "Untitled Session"}</div>
          <div className="mt-1 line-clamp-2 text-xs text-slate-500">{session.last_message_preview || "还没有消息。"}</div>
        </div>
        {session.pending_approval_count ? <Badge className="bg-orange-100 text-orange-800">{session.pending_approval_count}</Badge> : <StatusPill status={session.status} />}
      </div>
      <div className="mt-3 flex items-center justify-between text-xs text-slate-400">
        <span>{formatTime(session.updated_at)}</span>
        {session.latest_report_id ? <span>report</span> : null}
      </div>
    </button>
  );
}

function TaskDetailsModal({
  open,
  onClose,
  session,
  runs,
  activeRun,
  cveStatus,
  cveQuery,
  setCveQuery,
  cveResults,
  onSyncCve,
  onSearchCve,
  onSelectRun,
}) {
  if (!open) {
    return null;
  }
  const budget = activeRun?.budget_usage || { tool_calls_used: 0, runtime_seconds_used: 0, active_subagents: 0, active_tools: 0 };
  const budgetMax = activeRun?.budget || { max_tool_calls: 0, max_runtime_seconds: 0, max_parallel_subagents: 0, max_parallel_tools: 0 };
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-950/30 backdrop-blur-sm">
      <div className="h-full w-full max-w-[520px] overflow-y-auto bg-[#fcfbf7] p-6 shadow-2xl">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-lg font-semibold text-ink">任务详情</div>
            <div className="mt-1 text-sm text-slate-500">{session?.title || "未选择会话"}</div>
          </div>
          <Button variant="secondary" onClick={onClose}>
            关闭
          </Button>
        </div>

        <div className="mt-6 grid gap-4">
          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="font-medium text-ink">当前运行</div>
              <StatusPill status={activeRun?.status || session?.status || "idle"} />
            </div>
            <div className="text-sm text-slate-700">{activeRun?.user_task || "当前没有活跃任务。"}</div>
            <div className="mt-4 grid gap-2 text-xs text-slate-500">
              <div>工具调用 {budget.tool_calls_used}/{budgetMax.max_tool_calls}</div>
              <div>运行时长 {Number(budget.runtime_seconds_used || 0).toFixed(1)}/{budgetMax.max_runtime_seconds}s</div>
              <div>活跃 tool {budget.active_tools}/{budgetMax.max_parallel_tools}</div>
              <div>活跃 subagent {budget.active_subagents}/{budgetMax.max_parallel_subagents}</div>
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="mb-3 font-medium text-ink">历史 Run</div>
            <div className="grid gap-2">
              {runs.length === 0 ? <div className="text-sm text-slate-500">当前 session 还没有 run。</div> : null}
              {runs.map((run) => (
                <button
                  key={run.run_id}
                  type="button"
                  onClick={() => onSelectRun(run.run_id)}
                  className={`rounded-2xl border px-3 py-3 text-left ${activeRun?.run_id === run.run_id ? "border-ink bg-slate-50" : "border-slate-200 bg-white"}`}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="truncate text-sm font-medium text-ink">{run.user_task}</div>
                    <StatusPill status={run.status} />
                  </div>
                  <div className="mt-2 text-xs text-slate-400">{run.run_id}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-200 bg-white p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="font-medium text-ink">漏洞知识库</div>
              <StatusPill status={cveStatus.status || "idle"} />
            </div>
            <div className="flex gap-2">
              <Button variant="secondary" onClick={onSyncCve}>
                <RefreshCw size={14} className="mr-2" />
                同步 NVD
              </Button>
              <div className="text-xs text-slate-500">records: {cveStatus.normalized_records || 0}</div>
            </div>
            <div className="mt-4 flex gap-2">
              <Input value={cveQuery} onChange={(event) => setCveQuery(event.target.value)} placeholder="搜索 CVE / CWE / product" />
              <Button variant="secondary" onClick={onSearchCve}>
                搜索
              </Button>
            </div>
            {cveResults.length ? (
              <div className="mt-4 grid gap-2">
                {cveResults.slice(0, 4).map((item) => (
                  <div key={item.cve_id} className="rounded-xl bg-slate-50 p-3 text-sm text-slate-700">
                    <div className="font-medium text-ink">{item.cve_id}</div>
                    <div className="mt-1 text-xs text-slate-500">{compactText((item.descriptions || []).join(" "), 120)}</div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

        </div>
      </div>
    </div>
  );
}

export function App() {
  const [catalog, setCatalog] = useState({ profiles: [], tools: [], skills: [], cve: { status: "idle" } });
  const [sessions, setSessions] = useState([]);
  const [sessionSearch, setSessionSearch] = useState("");
  const [viewMode, setViewMode] = useState("chat");
  const [task, setTask] = useState("");
  const [profile, setProfile] = useState("sisyphus-default");
  const [repoPath, setRepoPath] = useState("");
  const [domain, setDomain] = useState("");
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [events, setEvents] = useState([]);
  const [runs, setRuns] = useState([]);
  const [planGraph, setPlanGraph] = useState(null);
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [running, setRunning] = useState(false);
  const [expandedItems, setExpandedItems] = useState(new Set());
  const [evidenceItems, setEvidenceItems] = useState({});
  const [openEvidenceIds, setOpenEvidenceIds] = useState(new Set());
  const [reportsById, setReportsById] = useState({});
  const [openReportIds, setOpenReportIds] = useState(new Set());
  const [showDetails, setShowDetails] = useState(false);
  const [cveStatus, setCveStatus] = useState({ status: "idle" });
  const [cveQuery, setCveQuery] = useState("");
  const [cveResults, setCveResults] = useState([]);
  const eventSourceRef = useRef(null);

  const timeline = useMemo(() => mergeHistory(messages, events), [messages, events]);
  const filteredSessions = useMemo(() => {
    const keyword = sessionSearch.trim().toLowerCase();
    if (!keyword) {
      return sessions;
    }
    return sessions.filter((item) => `${item.title || ""} ${item.last_message_preview || ""}`.toLowerCase().includes(keyword));
  }, [sessions, sessionSearch]);
  const activeRun = useMemo(() => runs.find((item) => item.run_id === session?.active_run_id) || runs[0] || null, [runs, session?.active_run_id]);
  const selectedGraphNode = useMemo(
    () => planGraph?.nodes?.find((node) => node.node_id === selectedNodeId) || planGraph?.nodes?.find((node) => node.is_active) || planGraph?.nodes?.[0] || null,
    [planGraph, selectedNodeId],
  );
  const approvalsByNodeId = useMemo(() => {
    const approvals = new Map();
    for (const item of events) {
      if (item.type === "approval_required" && item.data?.node_id) {
        approvals.set(item.data.node_id, item.data);
      }
      if (item.type === "approval_resolved" && item.data?.node_id) {
        approvals.delete(item.data.node_id);
      }
    }
    return approvals;
  }, [events]);
  const selectedGraphApproval = useMemo(
    () => (selectedGraphNode?.node_id ? approvalsByNodeId.get(selectedGraphNode.node_id) || null : null),
    [approvalsByNodeId, selectedGraphNode?.node_id],
  );

  useEffect(() => {
    let cancelled = false;

    async function bootstrap() {
      const [catalogResponse, sessionResponse] = await Promise.all([fetch("/api/catalog"), fetch("/api/sessions")]);
      const [catalogPayload, sessionPayload] = await Promise.all([catalogResponse.json(), sessionResponse.json()]);
      if (cancelled) {
        return;
      }
      setCatalog(catalogPayload);
      setCveStatus(catalogPayload.cve || { status: "idle" });
      setSessions(sessionPayload);
      if (sessionPayload.length > 0) {
        await hydrateSession(sessionPayload[0].session_id);
      }
    }

    bootstrap();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!session?.session_id) {
      return undefined;
    }
    eventSourceRef.current?.close();
    const source = new EventSource(`/api/sessions/${session.session_id}/events`);
    source.onmessage = async (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === "assistant_message") {
        setMessages((current) => {
          if (current.some((item) => item.message_id === payload.data.message_id)) {
            return current;
          }
          return [
            ...current,
            {
              message_id: payload.data.message_id,
              session_id: payload.session_id,
              run_id: payload.run_id,
              role: "assistant",
              sender: "sisyphus",
              content: payload.data.message,
              evidence_refs: payload.data.evidence_refs || [],
              artifact_refs: payload.data.artifact_refs || [],
              created_at: payload.created_at,
            },
          ];
        });
      } else {
        setEvents((current) => {
          if (current.some((item) => item.event_id === payload.event_id)) {
            return current;
          }
          return [...current, payload];
        });
      }

      if (payload.type === "task_graph_updated") {
        setPlanGraph(payload.data);
      }
      if (payload.type === "approval_required") {
        setRunning(false);
      }
      if (payload.type === "approval_resolved") {
        setRunning(true);
      }
      if (payload.type === "awaiting_user_input") {
        setRunning(false);
      }
      if (payload.type === "task_node_waiting_approval" || payload.type === "task_node_waiting_user_input") {
        setRunning(false);
      }
      if (payload.type === "completed" || payload.type === "failed") {
        setRunning(false);
      }
      if (payload.type === "cve_sync_updated") {
        setCveStatus(payload.data);
      }
      if (payload.type === "report_ready" || (payload.type === "completed" && payload.data?.report_id)) {
        await loadReport(payload.data.report_id);
      }
      if (payload.run_id && ["run_status", "approval_required", "approval_resolved", "completed", "failed", "report_ready", "awaiting_user_input", "budget_updated"].includes(payload.type)) {
        await hydrateRun(payload.run_id);
      }
      if (["assistant_message", "approval_required", "approval_resolved", "completed", "failed", "awaiting_user_input", "report_ready"].includes(payload.type)) {
        await loadSessions(session.session_id);
      }
    };
    eventSourceRef.current = source;
    return () => source.close();
  }, [session?.session_id]);

  useEffect(() => {
    if (planGraph?.nodes?.length && !planGraph.nodes.some((node) => node.node_id === selectedNodeId)) {
      const activeNode = planGraph.nodes.find((node) => node.is_active) || planGraph.nodes[0];
      setSelectedNodeId(activeNode?.node_id || null);
    }
  }, [planGraph, selectedNodeId]);

  async function loadSessions(preferredId = null) {
    const response = await fetch("/api/sessions");
    const payload = await response.json();
    setSessions(payload);
    if (!session?.session_id && payload.length > 0) {
      const targetId = preferredId || payload[0].session_id;
      if (targetId) {
        await hydrateSession(targetId);
      }
    }
    return payload;
  }

  async function hydrateRun(runId) {
    const [runResponse, graphResponse] = await Promise.all([fetch(`/api/runs/${runId}`), fetch(`/api/runs/${runId}/graph`)]);
    const [runPayload, graphPayload] = await Promise.all([runResponse.json(), graphResponse.json()]);
    setRuns((current) => {
      const others = current.filter((item) => item.run_id !== runPayload.run_id);
      return [runPayload, ...others].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    });
    setPlanGraph(graphPayload);
    setRunning(!["completed", "failed", "cancelled", "awaiting_approval", "awaiting_user_input"].includes(runPayload.status));
    if (runPayload.report_id) {
      await loadReport(runPayload.report_id);
    }
  }

  async function hydrateSession(sessionId) {
    const [sessionResponse, messagesResponse, eventsResponse, runsResponse] = await Promise.all([
      fetch(`/api/sessions/${sessionId}`),
      fetch(`/api/sessions/${sessionId}/messages`),
      fetch(`/api/sessions/${sessionId}/events?history_only=true`),
      fetch(`/api/sessions/${sessionId}/runs`),
    ]);
    const [baseSession, messagePayload, runsPayload, rawEvents] = await Promise.all([
      sessionResponse.json(),
      messagesResponse.json(),
      runsResponse.json(),
      eventsResponse.text(),
    ]);
    const parsedEvents = rawEvents
      .split("\n\n")
      .map((chunk) => chunk.trim())
      .filter(Boolean)
      .map((chunk) => JSON.parse(chunk.replace(/^data:\s*/, "")));

    setSession(baseSession);
    setMessages(messagePayload);
    setEvents(parsedEvents);
    setRuns(runsPayload);
    setExpandedItems(new Set());
    setOpenEvidenceIds(new Set());
    setOpenReportIds(new Set());
    if (baseSession.latest_report_id || baseSession.last_report_id) {
      await loadReport(baseSession.latest_report_id || baseSession.last_report_id);
    }
    if (baseSession.active_run_id) {
      await hydrateRun(baseSession.active_run_id);
      return;
    }
    if (runsPayload[0]) {
      await hydrateRun(runsPayload[0].run_id);
      return;
    }
    setPlanGraph(null);
    setRunning(false);
  }

  async function ensureSession(currentTask) {
    if (session?.session_id) {
      return session.session_id;
    }
    const response = await fetch("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: currentTask.slice(0, 60) || "DigAgent Session",
        profile,
        task_type: "general",
        scope: scopePayload(repoPath, domain),
      }),
    });
    const payload = await response.json();
    await loadSessions(payload.session_id);
    await hydrateSession(payload.session_id);
    return payload.session_id;
  }

  async function loadReport(reportId) {
    if (!reportId) {
      return;
    }
    if (reportsById[reportId]) {
      return reportsById[reportId];
    }
    const response = await fetch(`/api/reports/${reportId}`);
    const payload = await response.json();
    setReportsById((current) => ({ ...current, [reportId]: payload }));
    return payload;
  }

  async function toggleEvidence(evidenceId) {
    if (!evidenceItems[evidenceId]) {
      const response = await fetch(`/api/evidence/${evidenceId}`);
      const payload = await response.json();
      setEvidenceItems((current) => ({ ...current, [evidenceId]: payload }));
    }
    setOpenEvidenceIds((current) => {
      const next = new Set(current);
      if (next.has(evidenceId)) {
        next.delete(evidenceId);
      } else {
        next.add(evidenceId);
      }
      return next;
    });
  }

  async function toggleReport(reportId) {
    await loadReport(reportId);
    setOpenReportIds((current) => {
      const next = new Set(current);
      if (next.has(reportId)) {
        next.delete(reportId);
      } else {
        next.add(reportId);
      }
      return next;
    });
  }

  function toggleItem(eventId) {
    setExpandedItems((current) => {
      const next = new Set(current);
      if (next.has(eventId)) {
        next.delete(eventId);
      } else {
        next.add(eventId);
      }
      return next;
    });
  }

  async function sendMessage() {
    if (!task.trim()) {
      return;
    }
    const message = task.trim();
    const sessionId = await ensureSession(message);
    setMessages((current) => [
      ...current,
      {
        message_id: `local-${Date.now()}`,
        session_id: sessionId,
        run_id: session?.active_run_id || null,
        role: "user",
        sender: "user",
        content: message,
        evidence_refs: [],
        artifact_refs: [],
        created_at: new Date().toISOString(),
      },
    ]);
    setRunning(true);
    setTask("");
    const response = await fetch(`/api/sessions/${sessionId}/messages`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: message, profile, scope: scopePayload(repoPath, domain) }),
    });
    const payload = await response.json();
    if (payload.session) {
      setSession(payload.session);
    }
    await loadSessions(sessionId);
    await hydrateSession(sessionId);
    if (!payload.run) {
      setRunning(false);
    }
  }

  async function resolveApproval(approval, approved) {
    const resolver = "webui";
    const approvalToken = await buildApprovalToken(approval, approved, resolver);
    const response = await fetch(`/api/approvals/${approval.approval_id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, resolver, approval_token: approvalToken }),
    });
    if (!response.ok) {
      const payload = await response.json();
      alert(payload.detail || "审批提交失败");
      return;
    }
    await loadSessions(session?.session_id);
  }

  async function selectSession(sessionId) {
    setViewMode("chat");
    await hydrateSession(sessionId);
  }

  function startFreshSession() {
    eventSourceRef.current?.close();
    setSession(null);
    setMessages([]);
    setEvents([]);
    setRuns([]);
    setPlanGraph(null);
    setRunning(false);
    setTask("");
    setShowDetails(false);
  }

  async function toggleArchive() {
    if (!session?.session_id) {
      return;
    }
    const endpoint = session.status === "archived" ? "unarchive" : "archive";
    const response = await fetch(`/api/sessions/${session.session_id}/${endpoint}`, { method: "POST" });
    if (!response.ok) {
      const payload = await response.json();
      alert(payload.detail || "会话操作失败");
      return;
    }
    const payload = await response.json();
    setSession(payload);
    await loadSessions(payload.session_id);
  }

  async function cancelCurrentRun() {
    if (!activeRun) {
      return;
    }
    await fetch(`/api/runs/${activeRun.run_id}/cancel`, { method: "POST" });
    await hydrateRun(activeRun.run_id);
    await loadSessions(session?.session_id);
  }

  async function syncCve() {
    setCveStatus((current) => ({ ...current, status: "running", running: true }));
    const response = await fetch("/api/cve/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_records: 200 }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setCveStatus((current) => ({ ...current, status: "failed", running: false, last_error: payload.detail || "sync failed" }));
      return;
    }
    setCveStatus(payload);
  }

  async function searchCve() {
    const response = await fetch(`/api/cve/search?query=${encodeURIComponent(cveQuery)}`);
    const payload = await response.json();
    setCveResults(payload.items || []);
    setCveStatus(payload.state || cveStatus);
  }

  async function downloadReport(reportId, format) {
    window.open(`/api/reports/${reportId}/download?format=${format}`, "_blank");
  }

  const evidenceState = useMemo(() => ({ items: evidenceItems, openIds: openEvidenceIds }), [evidenceItems, openEvidenceIds]);

  return (
    <div className="h-screen overflow-hidden bg-transparent text-ink">
      <TaskDetailsModal
        open={showDetails}
        onClose={() => setShowDetails(false)}
        session={session}
        runs={runs}
        activeRun={activeRun}
        cveStatus={cveStatus}
        cveQuery={cveQuery}
        setCveQuery={setCveQuery}
        cveResults={cveResults}
        onSyncCve={syncCve}
        onSearchCve={searchCve}
        onSelectRun={hydrateRun}
      />

      <div className="mx-auto flex h-full max-w-[1680px] gap-6 overflow-hidden px-4 py-4 md:px-6">
        <aside className="hidden h-full min-h-0 w-[312px] shrink-0 flex-col rounded-[2rem] border border-slate-200/80 bg-white/70 p-4 shadow-panel backdrop-blur lg:flex">
          <div className="flex items-center justify-between gap-3 px-2 pb-4">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Shield size={16} />
                DigAgent
              </div>
              <div className="mt-1 text-xs text-slate-500">General chat shell with agent runtime</div>
            </div>
            <Button onClick={startFreshSession}>
              <Plus size={14} className="mr-2" />
              新会话
            </Button>
          </div>

          <div className="relative mb-4">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <Input className="pl-10" placeholder="搜索会话" value={sessionSearch} onChange={(event) => setSessionSearch(event.target.value)} />
          </div>

          <div className="flex-1 overflow-y-auto">
            <div className="grid gap-2">
              {filteredSessions.map((item) => (
                <SessionListItem key={item.session_id} session={item} active={item.session_id === session?.session_id} onSelect={selectSession} />
              ))}
              {filteredSessions.length === 0 ? <div className="px-3 py-8 text-sm text-slate-500">还没有会话。先发起一个任务。</div> : null}
            </div>
          </div>

          <div className="mt-4 rounded-2xl bg-slate-50 px-4 py-3 text-xs text-slate-500">
            <div>Profiles: {catalog.profiles.length}</div>
            <div>Tools: {catalog.tools.length}</div>
            <div>Skills: {catalog.skills.length}</div>
          </div>
        </aside>

        <main className="flex h-full min-w-0 flex-1 flex-col overflow-hidden rounded-[2rem] border border-slate-200/80 bg-white/75 shadow-panel backdrop-blur">
          <header className="border-b border-slate-200/80 px-5 py-4 md:px-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <div className="rounded-full bg-ink p-2 text-white">
                    <Bot size={18} />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-lg font-semibold text-ink">{session?.title || "新会话"}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <StatusPill status={session?.status || "idle"} />
                      {activeRun ? <span className="truncate">{compactText(activeRun.user_task, 88)}</span> : <span>聊天是主视图，流程图作为次级标签保留。</span>}
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button variant={viewMode === "chat" ? "primary" : "secondary"} onClick={() => setViewMode("chat")}>
                  <MessageSquareText size={14} className="mr-2" />
                  聊天
                </Button>
                <Button variant={viewMode === "graph" ? "primary" : "secondary"} onClick={() => setViewMode("graph")}>
                  <GitBranchPlus size={14} className="mr-2" />
                  任务图
                </Button>
                <Button variant="secondary" onClick={() => setShowDetails(true)}>
                  <SquareTerminal size={14} className="mr-2" />
                  任务详情
                </Button>
                <Button variant="secondary" onClick={toggleArchive} disabled={!session?.session_id}>
                  <Archive size={14} className="mr-2" />
                  {session?.status === "archived" ? "恢复" : "归档"}
                </Button>
              </div>
            </div>
          </header>

          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            {viewMode === "chat" ? (
              <>
                <div className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-6">
                  {timeline.length === 0 ? (
                    <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center rounded-[2rem] border border-dashed border-slate-300 bg-slate-50/70 px-8 py-16 text-center">
                      <div className="rounded-full bg-white p-3 text-sea shadow-sm">
                        <MessageSquareText size={24} />
                      </div>
                      <div className="mt-5 text-xl font-semibold text-ink">DigAgent</div>
                      <p className="mt-2 max-w-xl text-sm leading-6 text-slate-500">
                        像通用聊天 Bot 一样开始对话。审批、证据、报告和任务图会作为辅助能力出现，不再占据整个主界面。
                      </p>
                    </div>
                  ) : (
                    <div className="mx-auto grid max-w-4xl gap-4">
                      {timeline.map((item) => (
                        <ChatMessage
                          key={item.event_id}
                          item={item}
                          expandedItems={expandedItems}
                          toggleItem={toggleItem}
                          evidenceState={evidenceState}
                          onToggleEvidence={toggleEvidence}
                          onResolveApproval={resolveApproval}
                          reportsById={reportsById}
                          reportOpenIds={openReportIds}
                          onToggleReport={toggleReport}
                          onDownloadReport={downloadReport}
                        />
                      ))}
                      {running ? (
                        <div className="flex justify-start">
                          <div className="inline-flex items-center gap-3 rounded-full border border-slate-200 bg-white px-4 py-3 text-sm text-slate-600 shadow-sm">
                            <LoaderCircle size={16} className="animate-spin" />
                            DigAgent 正在继续执行
                          </div>
                        </div>
                      ) : null}
                    </div>
                  )}
                </div>

                <div className="border-t border-slate-200/80 px-4 py-4 md:px-6">
                  <div className="mx-auto max-w-4xl rounded-[1.8rem] border border-slate-200 bg-[#fbfbf8] p-4 shadow-sm">
                    <div className="mb-3 grid gap-2 md:grid-cols-[1fr_1fr_180px]">
                      <Input placeholder="仓库路径（可选）" value={repoPath} onChange={(event) => setRepoPath(event.target.value)} />
                      <Input placeholder="目标域名（可选）" value={domain} onChange={(event) => setDomain(event.target.value)} />
                      <select
                        className="w-full rounded-2xl border border-slate-300 bg-white px-4 py-2 text-sm outline-none focus:border-sea"
                        value={profile}
                        onChange={(event) => setProfile(event.target.value)}
                      >
                        {catalog.profiles.map((item) => (
                          <option key={item.name} value={item.name}>
                            {item.name}
                          </option>
                        ))}
                      </select>
                    </div>
                    <Textarea
                      className="min-h-28 resize-none border-0 bg-transparent px-0 py-0 focus:border-transparent"
                      placeholder="向 DigAgent 发送消息，例如：分析当前项目源码并生成报告"
                      value={task}
                      onChange={(event) => setTask(event.target.value)}
                    />
                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                        {activeRun ? (
                          <>
                            <StatusPill status={activeRun.status} />
                            <span>当前 run: {activeRun.run_id}</span>
                          </>
                        ) : (
                          <span>直接对话会自动按 session 驱动 direct answer / run。</span>
                        )}
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button variant="secondary" onClick={() => setShowDetails(true)}>
                          <FileSearch size={14} className="mr-2" />
                          当前任务
                        </Button>
                        {activeRun ? (
                          <Button variant="secondary" onClick={cancelCurrentRun}>
                            <XCircle size={14} className="mr-2" />
                            取消
                          </Button>
                        ) : null}
                        {session?.latest_report_id ? (
                          <>
                            <Button variant="secondary" onClick={() => downloadReport(session.latest_report_id, "markdown")}>
                              <Download size={14} className="mr-2" />
                              Markdown
                            </Button>
                            <Button variant="secondary" onClick={() => downloadReport(session.latest_report_id, "pdf")}>
                              <Download size={14} className="mr-2" />
                              PDF
                            </Button>
                          </>
                        ) : null}
                        <Button onClick={sendMessage} disabled={!task.trim()}>
                          {running ? <LoaderCircle size={14} className="mr-2 animate-spin" /> : <CheckCircle2 size={14} className="mr-2" />}
                          发送
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="min-h-0 flex-1 overflow-hidden px-4 py-6 md:px-6">
                <div className="mx-auto flex h-full min-h-0 max-w-6xl flex-col gap-6 overflow-hidden">
                  <div className="flex min-h-0 flex-[1.1] flex-col rounded-[2rem] border border-slate-200 bg-slate-50/70 p-5">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-lg font-semibold text-ink">任务规划图</div>
                        <div className="mt-1 text-sm text-slate-500">参考任务 DAG 展示当前 run 的步骤、阻塞和完成情况。</div>
                      </div>
                      {activeRun ? <StatusPill status={activeRun.status} /> : null}
                    </div>
                    <div className="mt-5 min-h-0 flex-1">
                      <GraphCanvas graph={planGraph} selectedNodeId={selectedGraphNode?.node_id || selectedNodeId} onSelect={setSelectedNodeId} />
                    </div>
                  </div>

                  <div className="min-h-0 overflow-y-auto rounded-[2rem] border border-slate-200 bg-white p-5 shadow-sm">
                    <div className="flex items-center justify-between gap-3">
                      <div>
                        <div className="text-lg font-semibold text-ink">{selectedGraphNode?.title || "节点详情"}</div>
                        <div className="mt-1 text-sm text-slate-500">{selectedGraphNode ? selectedGraphNode.kind : "选择图中的节点查看详情。"}</div>
                      </div>
                      {selectedGraphNode ? <Badge className={graphNodeStyles[selectedGraphNode.status] ? "bg-slate-100 text-slate-700" : ""}>{selectedGraphNode.status}</Badge> : null}
                    </div>

                    {selectedGraphNode ? (
                      <div className="mt-5 grid gap-4">
                        <div className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-700">
                          {selectedGraphNode.status === "waiting_user_input" ? graphNodeQuestion(selectedGraphNode) : selectedGraphNode.summary || selectedGraphNode.description}
                        </div>
                        {(selectedGraphNode.block_reason || selectedGraphNode.status === "waiting_user_input") ? (
                          <div className="rounded-2xl border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900">
                            <div className="font-medium">Blocked reason</div>
                            <div className="mt-2">
                              {selectedGraphNode.status === "waiting_user_input" ? graphNodeQuestion(selectedGraphNode) : selectedGraphNode.block_reason}
                            </div>
                          </div>
                        ) : null}
                        {selectedGraphNode.action_request ? (
                          <div className="rounded-2xl border border-slate-200 bg-white p-4">
                            <div className="mb-2 text-sm font-medium text-ink">动作摘要</div>
                            <div className="grid gap-2 text-sm text-slate-700">
                              <div>Action: {selectedGraphNode.action_request.name}</div>
                              {selectedGraphNode.action_request.risk_tags?.length ? <div>Risk: {selectedGraphNode.action_request.risk_tags.join(", ")}</div> : null}
                              <pre className="overflow-x-auto whitespace-pre-wrap rounded-2xl bg-slate-50 p-3 text-xs text-slate-700">
                                {JSON.stringify(selectedGraphNode.action_request.arguments || {}, null, 2)}
                              </pre>
                            </div>
                          </div>
                        ) : null}
                        {selectedGraphNode.status === "waiting_approval" && selectedGraphApproval ? (
                          <div className="rounded-2xl border border-orange-200 bg-orange-50 p-4">
                            <div className="mb-3 text-sm font-medium text-orange-900">节点审批</div>
                            <ApprovalCard approval={selectedGraphApproval} onResolve={resolveApproval} />
                          </div>
                        ) : null}
                        {selectedGraphNode.evidence_refs?.length ? (
                          <div>
                            <div className="mb-2 text-sm font-medium text-ink">关联证据</div>
                            <div className="flex flex-wrap gap-2">
                              {selectedGraphNode.evidence_refs.map((evidenceId) => (
                                <Button key={`graph-ev-${evidenceId}`} variant="secondary" onClick={() => toggleEvidence(evidenceId)}>
                                  <Eye size={14} className="mr-2" />
                                  {evidenceId}
                                </Button>
                              ))}
                            </div>
                            {selectedGraphNode.evidence_refs.map((evidenceId) => {
                              const evidence = evidenceItems[evidenceId];
                              if (!openEvidenceIds.has(evidenceId) || !evidence) {
                                return null;
                              }
                              return <EvidenceInline key={`graph-evidence-${evidenceId}`} evidence={evidence} onOpenArtifact={(artifactId) => window.open(`/api/artifacts/${artifactId}/content`, "_blank")} />;
                            })}
                          </div>
                        ) : null}
                      </div>
                    ) : (
                      <div className="mt-5 text-sm text-slate-500">当前没有任务节点。</div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
