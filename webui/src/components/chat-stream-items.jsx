import React from "react";
import { AlertTriangle, ArrowRight, Bot, BrainCircuit, Eye, LoaderCircle, ShieldAlert, Wrench } from "lucide-react";
import { formatTime } from "../chat-utils";
import { renderInlineEvidence } from "./timeline-inline";
import { MarkdownBlock } from "./markdown-block";
import { Badge, Button } from "./ui";

function chips(values) {
  return values.filter(Boolean).map((value) => <Badge key={String(value)} className="bg-white/70 text-[11px] text-slate-600">{value}</Badge>);
}

function BubbleShell({ children, tone = "assistant" }) {
  const classes = tone === "user"
    ? "ml-auto max-w-[88%] rounded-[1.6rem] bg-[#f4f4f4] px-4 py-3 text-slate-900"
    : "min-w-0 flex-1";
  return <div className={classes}>{children}</div>;
}

function AgentAvatar({ label = "A", muted = false }) {
  return (
    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${muted ? "bg-slate-200 text-slate-600" : "bg-slate-900 text-white"}`}>
      {label.slice(0, 2).toUpperCase()}
    </div>
  );
}

export function MessageItem({ density, evidenceState, item, onToggleEvidence }) {
  const textClass = density === "compact" ? "text-[14px] leading-7" : "text-[15px] leading-8";
  const evidenceRefs = item.data?.evidence_refs || [];
  const addressed = item.data?.addressed_participants || [];
  if (item.type === "local_user" || item.type === "user_message") {
    return (
      <div className="flex justify-end">
        <BubbleShell tone="user">
          {addressed.length ? <div className="mb-2 flex flex-wrap gap-1.5">{chips(addressed.map((value) => `@${value}`))}</div> : null}
          <MarkdownBlock className={`text-slate-900 [overflow-wrap:anywhere] ${textClass}`} content={item.data?.markdown || item.data?.message} variant="body" />
          {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
        </BubbleShell>
      </div>
    );
  }
  return (
    <div className="group flex gap-4">
      <AgentAvatar label="DA" />
      <div className="min-w-0 flex-1 pt-0.5">
        <MarkdownBlock className={`text-slate-900 ${textClass} [overflow-wrap:anywhere]`} content={item.data?.markdown || item.data?.message} variant="body" />
        {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
        <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
          {item.data?.speaker_profile ? <span className="[overflow-wrap:anywhere]">{item.data.speaker_profile}</span> : null}
          <span>{formatTime(item.created_at)}</span>
        </div>
      </div>
    </div>
  );
}

export function ThoughtItem({ item }) {
  const detail = item.data?.detail || "";
  const summary = item.data?.summary || detail;
  return (
    <details className="rounded-[1.5rem] border border-slate-200 bg-slate-100/80 px-4 py-3 text-slate-700" open={false}>
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <BrainCircuit size={15} className="shrink-0 text-slate-500" />
          <span className="truncate text-sm font-medium text-slate-700">{summary}</span>
        </div>
        <span className="shrink-0 text-[11px] text-slate-400">{item.data?.speaker_profile || "assistant"}</span>
      </summary>
      <MarkdownBlock className="mt-3 text-slate-700" content={detail} variant="muted" />
    </details>
  );
}

export function ToolItem({ item, observation = false }) {
  const facts = Array.isArray(item.data?.facts) ? item.data.facts : [];
  return (
    <div className={`rounded-[1.5rem] border px-4 py-3 ${observation ? "border-sky-200 bg-sky-50/70" : "border-slate-200 bg-white"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            {observation ? <Eye size={15} className="text-sky-700" /> : <Wrench size={15} className="text-slate-500" />}
            <span className="[overflow-wrap:anywhere]">{item.data?.title}</span>
          </div>
          <div className="mt-1.5 text-sm leading-7 text-slate-600 [overflow-wrap:anywhere]">{item.data?.summary}</div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1.5">
          {chips([
            item.data?.tool_name,
            observation ? item.data?.status : item.data?.argument_count ? `${item.data.argument_count} 参数` : null,
            observation ? item.data?.source_host : null,
          ])}
        </div>
      </div>
      {facts.length ? (
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {facts.map((fact, index) => (
            <div key={index} className="rounded-xl border border-white/80 bg-white/80 px-3 py-2 text-sm text-slate-700 [overflow-wrap:anywhere]">
              {typeof fact === "string" ? fact : fact?.value || fact?.label || fact?.key}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ParticipantHandoffItem({ item }) {
  return (
    <div className="rounded-[1.5rem] border border-amber-200 bg-amber-50/80 px-4 py-3">
      <div className="flex items-center gap-2 text-sm font-medium text-amber-950">
        <ArrowRight size={15} />
        <span className="[overflow-wrap:anywhere]">
          {item.data?.handoff_from || "assistant"}
          {" -> "}
          {item.data?.handoff_to || "agent"}
        </span>
      </div>
      <div className="mt-1.5 text-sm leading-7 text-amber-900/80 [overflow-wrap:anywhere]">{item.data?.summary}</div>
    </div>
  );
}

export function ParticipantMessageItem({ item }) {
  const participant = item.data?.participant_profile || "agent";
  return (
    <div className="flex gap-4">
      <AgentAvatar label={participant} muted />
      <div className="min-w-0 flex-1 rounded-[1.5rem] border border-slate-200 bg-white px-4 py-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">{participant}</div>
        <MarkdownBlock className="text-slate-800 [overflow-wrap:anywhere]" content={item.data?.markdown || item.data?.message || item.data?.summary} />
      </div>
    </div>
  );
}

export function ApprovalItem({ item, onResolveApproval, resolvedApprovalIds, resolvingApprovalIds, supersededApprovalIds, supersededApprovals }) {
  const approval = item.data || {};
  const resolved = resolvedApprovalIds?.has(approval.approval_id);
  const pending = resolvingApprovalIds?.has(approval.approval_id);
  const superseded = supersededApprovalIds?.has(approval.approval_id);
  const replacement = superseded ? supersededApprovals?.[approval.approval_id] : null;
  const disabled = Boolean(resolved || pending || superseded);
  const title = superseded ? "审批已被替代" : resolved ? "审批已处理" : pending ? "审批提交中..." : "需要审批";
  return (
    <div className={`rounded-[1.5rem] border px-4 py-3 ${superseded || resolved ? "border-slate-200 bg-slate-50 text-slate-600" : "border-orange-200 bg-orange-50 text-orange-950"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlert size={15} />
            <span className="[overflow-wrap:anywhere]">{title}</span>
          </div>
          <MarkdownBlock className="mt-1.5 [overflow-wrap:anywhere]" content={approval.reason || approval.message || approval.name} />
          <div className="mt-1 text-[11px] text-orange-700 [overflow-wrap:anywhere]">{approval.name || approval.approval_id}</div>
          {superseded && replacement?.newApprovalId ? <div className="mt-1 text-[11px] text-slate-500">已由 {replacement.newApprovalId} 替代</div> : null}
        </div>
        <Badge className="bg-white text-orange-900">{approval.approval_id}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, true)}>{pending ? "处理中..." : "批准"}</Button>
        <Button size="sm" variant="danger" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, false)}>拒绝</Button>
      </div>
    </div>
  );
}

export function NoticeItem({ item }) {
  const isFailure = item.data?.severity === "error";
  return (
    <div className={`rounded-[1.5rem] border px-4 py-3 ${isFailure ? "border-rose-200 bg-rose-50" : "border-slate-200 bg-slate-50"}`}>
      <div className="flex items-start gap-2">
        <AlertTriangle size={15} className={isFailure ? "text-rose-600" : "text-slate-500"} />
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-900 [overflow-wrap:anywhere]">{item.data?.title}</div>
          <MarkdownBlock className="mt-1.5 [overflow-wrap:anywhere]" content={item.data?.summary} variant="muted" />
        </div>
      </div>
    </div>
  );
}

export function RunningItem() {
  return (
    <div className="flex gap-4">
      <AgentAvatar label="DA" />
      <div className="flex min-w-0 items-center gap-2 pt-1.5 text-sm text-slate-500">
        <LoaderCircle size={14} className="animate-spin shrink-0" />
        <span className="[overflow-wrap:anywhere]">正在继续执行...</span>
      </div>
    </div>
  );
}
