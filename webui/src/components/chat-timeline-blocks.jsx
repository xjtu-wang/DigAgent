import React, { useState } from "react";
import {
  AlertTriangle,
  ArrowRightLeft,
  Bot,
  BrainCircuit,
  Box,
  ChevronDown,
  ChevronRight,
  FileText,
  LoaderCircle,
  ShieldAlert,
  Sparkles,
  Workflow,
  Wrench,
} from "lucide-react";
import { formatTime } from "../chat-utils";
import { MarkdownBlock } from "./markdown-block";
import { ReportInline, renderInlineEvidence } from "./timeline-inline";
import { StatusPill } from "./status-pill";
import { Badge, Button } from "./ui";

const GROUP_META = {
  agent: { icon: Sparkles, label: "Agent 协作", shellClassName: "border-amber-200/70 bg-amber-50/70" },
  tool: { icon: Wrench, label: "工具活动", shellClassName: "border-sky-200/70 bg-sky-50/65" },
  skill: { icon: BrainCircuit, label: "Skill 调用", shellClassName: "border-emerald-200/70 bg-emerald-50/65" },
  mcp: { icon: Box, label: "MCP 调用", shellClassName: "border-cyan-200/70 bg-cyan-50/65" },
  workflow: { icon: Workflow, label: "执行流程", shellClassName: "border-[color:var(--app-border)] bg-[color:var(--app-panel)]" },
  system: { icon: AlertTriangle, label: "系统提示", shellClassName: "border-rose-200/60 bg-rose-50/60" },
};

export function TimelineMessageBlock({ density, evidenceState, group, onToggleEvidence }) {
  const item = group.items[0];
  const textClassName = density === "compact" ? "text-[14px] leading-7" : "text-[15px] leading-8";
  if (group.speakerRole === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[min(92%,42rem)] rounded-[1.8rem] bg-[color:var(--app-panel-strong)] px-4 py-3.5 shadow-[var(--app-shadow-soft)]">
          <MarkdownBlock className={`${textClassName} text-[color:var(--app-text)] [overflow-wrap:anywhere]`} content={item.data?.markdown || item.data?.message} variant="body" />
          {renderInlineEvidence(item.data?.evidence_refs || [], evidenceState, onToggleEvidence)}
        </div>
      </div>
    );
  }
  return (
    <div className="flex gap-3 sm:gap-4">
      <MessageAvatar agent={group.speakerRole === "agent"} label={group.speakerLabel || "DA"} />
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="mb-2 flex items-center gap-2 text-[11px] text-[color:var(--app-text-faint)]">
          <span className="font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-soft)]">{group.speakerLabel || "DigAgent"}</span>
          <span>{formatTime(item.created_at)}</span>
        </div>
        <div className="rounded-[1.6rem] bg-[color:var(--app-panel)] px-4 py-3.5 shadow-[var(--app-shadow-soft)] ring-1 ring-[color:var(--app-border)]">
          <MarkdownBlock className={`${textClassName} text-[color:var(--app-text)] [overflow-wrap:anywhere]`} content={item.data?.markdown || item.data?.message} variant="body" />
          {renderInlineEvidence(item.data?.evidence_refs || [], evidenceState, onToggleEvidence)}
        </div>
      </div>
    </div>
  );
}

export function TimelineClusterBlock({ group }) {
  const [open, setOpen] = useState(group.type === "agent" && group.items.length === 1);
  const meta = GROUP_META[group.type] || GROUP_META.system;
  const Icon = meta.icon;
  return (
    <section className={`rounded-[1.8rem] border px-4 py-3 shadow-[var(--app-shadow-soft)] ${meta.shellClassName}`}>
      <button type="button" onClick={() => setOpen((value) => !value)} className="flex w-full items-start justify-between gap-4 text-left">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-[color:var(--app-text-faint)]">
            <Icon size={14} className="text-[color:var(--app-text-soft)]" />
            <span>{meta.label}</span>
            <Badge className="bg-white/80 text-[10px] text-[color:var(--app-text-soft)]">{group.count}</Badge>
          </div>
          <div className="mt-2 text-[15px] font-medium text-[color:var(--app-text)]">{group.title}</div>
          <div className="mt-1 text-sm leading-7 text-[color:var(--app-text-soft)]">{group.summary}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-1 text-[11px] text-[color:var(--app-text-faint)]">
          <span>{formatTime(group.latest_at || group.created_at)}</span>
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>
      </button>
      {open ? (
        <div className="mt-4 grid gap-3 border-t border-[color:var(--app-border)]/80 pt-4">
          {group.items.map((item) => <ClusterRow key={item.event_id} item={item} />)}
        </div>
      ) : null}
    </section>
  );
}

export function TimelineApprovalBlock(props) {
  const item = props.item || props.group?.items?.[0];
  const approval = item?.data || {};
  const state = item?.type === "approval_notice" ? approval.state : "required";
  const resolving = props.resolvingApprovalIds?.has(approval.approval_id);
  const resolved = props.resolvedApprovalIds?.has(approval.approval_id);
  const superseded = props.supersededApprovalIds?.has(approval.approval_id) || state === "superseded";
  const disabled = Boolean(resolving || resolved || superseded || item?.type === "approval_notice");
  return (
    <section className="rounded-[1.8rem] border border-orange-200/80 bg-orange-50/80 px-4 py-4 shadow-[var(--app-shadow-soft)]">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-orange-700/80">
            <ShieldAlert size={14} />
            <span>需要确认</span>
          </div>
          <div className="mt-2 text-[15px] font-medium text-orange-950">{approval.title || "需要确认"}</div>
          <div className="mt-1 text-sm leading-7 text-orange-900/85">{approval.summary || approval.reason || approval.message || approval.name}</div>
          <div className="mt-3 flex flex-wrap gap-2">
            {[approval.name || approval.approval_id, approval.new_approval_id ? `替代 ${approval.new_approval_id}` : null, approval.status].filter(Boolean).map((value) => (
              <Badge key={String(value)} className="bg-white/85 text-orange-800">{value}</Badge>
            ))}
          </div>
        </div>
        <span className="shrink-0 pt-1 text-[11px] text-orange-700/70">{formatTime(item?.created_at)}</span>
      </div>
      {item?.type === "approval_required" ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" disabled={disabled} onClick={() => !disabled && props.onResolveApproval(approval, true)}>{resolving ? "处理中..." : "允许继续"}</Button>
          <Button size="sm" variant="danger" disabled={disabled} onClick={() => !disabled && props.onResolveApproval(approval, false)}>拒绝请求</Button>
        </div>
      ) : null}
    </section>
  );
}

export function TimelineReportBlock({ expandedItems, group, onDownloadReport, onToggleItem, onToggleReport, reportOpenIds, reportsById }) {
  const item = group.items[0];
  const data = item.data || {};
  const open = expandedItems.has(item.event_id);
  const reportId = data.report_id;
  return (
    <section className="rounded-[1.8rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-4 shadow-[var(--app-shadow)]">
      <button type="button" onClick={() => onToggleItem(item.event_id, item.turn_id)} className="flex w-full items-start justify-between gap-4 text-left">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-[color:var(--app-text-faint)]">
            <FileText size={14} className="text-[color:var(--app-text-soft)]" />
            <span>执行总结</span>
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusPill status={data.status || "completed"} />
            {[data.report_id ? "报告" : null, data.evidence_count ? `${data.evidence_count} 证据` : null, data.artifact_count ? `${data.artifact_count} 附件` : null].filter(Boolean).map((value) => (
              <Badge key={value}>{value}</Badge>
            ))}
          </div>
          <div className="mt-3 text-[15px] font-medium leading-7 text-[color:var(--app-text)]">{data.goal || "本轮执行"}</div>
          <div className="mt-2 text-sm leading-7 text-[color:var(--app-text-soft)]">{data.result_summary || data.action_summary || "本轮执行已经生成结果摘要。"}</div>
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-1 text-[11px] text-[color:var(--app-text-faint)]">
          <span>{formatTime(item.created_at)}</span>
          {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </div>
      </button>
      {open ? (
        <div className="mt-4 grid gap-4 border-t border-[color:var(--app-border)] pt-4">
          <SummaryLine label="最近动作" value={data.action_summary} />
          <SummaryLine label="结果" value={data.result_summary} />
          <SummaryLine label="目标范围" value={data.target} />
          {reportId ? (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" onClick={() => onToggleReport(reportId)}>{reportOpenIds.has(reportId) ? "收起报告" : "查看报告"}</Button>
              <Button size="sm" variant="secondary" onClick={() => onDownloadReport(reportId, "markdown")}>Markdown</Button>
              <Button size="sm" variant="secondary" onClick={() => onDownloadReport(reportId, "pdf")}>PDF</Button>
            </div>
          ) : null}
          {reportId && reportOpenIds.has(reportId) && reportsById[reportId] ? <ReportInline report={reportsById[reportId]} onDownload={onDownloadReport} /> : null}
        </div>
      ) : null}
    </section>
  );
}

export function TimelineRunningBlock() {
  return (
    <div className="flex items-center gap-3 px-1 text-sm text-[color:var(--app-text-soft)]">
      <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[color:var(--app-panel)] ring-1 ring-[color:var(--app-border)]">
        <LoaderCircle size={15} className="animate-spin" />
      </div>
      <div>
        <div className="font-medium text-[color:var(--app-text)]">DigAgent 正在处理你的任务</div>
        <div className="text-[13px] text-[color:var(--app-text-faint)]">主回答会随着执行进度持续更新。</div>
      </div>
    </div>
  );
}

function MessageAvatar({ agent = false, label }) {
  return (
    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full shadow-[var(--app-shadow-soft)] ${agent ? "bg-[color:var(--app-panel-strong)] text-[color:var(--app-text)]" : "bg-[color:var(--app-text)] text-white"}`}>
      {agent ? <Sparkles size={16} /> : <Bot size={16} />}
      <span className="sr-only">{label}</span>
    </div>
  );
}

function ClusterRow({ item }) {
  const meta = rowMeta(item);
  const Icon = meta.icon;
  return (
    <details className="rounded-[1.35rem] border border-white/80 bg-white/80 px-3.5 py-3">
      <summary className="cursor-pointer list-none">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-[color:var(--app-text)]">
              <Icon size={15} className="text-[color:var(--app-text-soft)]" />
              <span>{meta.title}</span>
            </div>
            <div className="mt-1 text-sm leading-7 text-[color:var(--app-text-soft)]">{meta.summary}</div>
            <div className="mt-2 flex flex-wrap gap-2">{meta.badges.map((value) => <Badge key={String(value)}>{value}</Badge>)}</div>
          </div>
          <div className="flex shrink-0 items-center gap-1 text-[11px] text-[color:var(--app-text-faint)]">
            <span>{formatTime(item.created_at)}</span>
            <ChevronDown size={14} />
          </div>
        </div>
      </summary>
      {meta.detail ? <RenderDetail content={meta.detail} /> : null}
    </details>
  );
}

function rowMeta(item) {
  if (item.type === "participant_handoff") {
    return metaRow(ArrowRightLeft, `由 ${item.data?.handoff_from || "assistant"} 转交给 ${item.data?.handoff_to || "agent"}`, item.data?.summary, []);
  }
  if (item.type === "participant_message" || item.type === "assistant_message") {
    return metaRow(Sparkles, item.data?.participant_profile ? `@${item.data.participant_profile}` : `@${item.data?.speaker_profile || "agent"}`, item.data?.summary || item.data?.message, [item.data?.participant_profile || item.data?.speaker_profile], item.data?.markdown || item.data?.message);
  }
  if (item.type === "assistant_process") {
    return metaRow(Workflow, item.data?.title || "处理中", item.data?.summary, [item.data?.speaker_profile], item.data?.detail);
  }
  if (item.type === "tool_observation") {
    return metaRow(Wrench, item.data?.title || "工具结果", item.data?.summary, [item.data?.tool_name, item.data?.status, item.data?.source_host].filter(Boolean), item.data?.detail);
  }
  if (item.type === "tool_action") {
    return metaRow(Wrench, item.data?.title || "发起工具调用", item.data?.summary, [item.data?.tool_name, item.data?.argument_count ? `${item.data.argument_count} 个参数` : null].filter(Boolean), item.data?.detail);
  }
  return metaRow(AlertTriangle, item.data?.title || "系统提示", item.data?.summary, []);
}

function metaRow(icon, title, summary, badges, detail = "") {
  return {
    icon,
    title,
    summary,
    badges,
    detail,
  };
}

function RenderDetail({ content }) {
  const value = String(content || "").trim();
  if (!value) {
    return null;
  }
  if (value.startsWith("{") || value.startsWith("[") || value.includes("\n")) {
    return <pre className="mt-3 overflow-x-auto whitespace-pre-wrap rounded-[1rem] bg-slate-950 px-3 py-3 text-xs leading-6 text-slate-100">{value}</pre>;
  }
  return <MarkdownBlock className="mt-3 text-sm text-[color:var(--app-text-soft)]" content={value} variant="muted" />;
}

function SummaryLine({ label, value }) {
  if (!value) {
    return null;
  }
  return <div className="text-sm leading-7 text-[color:var(--app-text-soft)]"><span className="mr-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-faint)]">{label}</span>{value}</div>;
}
