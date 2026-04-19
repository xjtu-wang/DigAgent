import React from "react";
import { AlertTriangle, Bot, FileText, LoaderCircle, ShieldAlert } from "lucide-react";
import { eventSummary, systemEventLabels } from "../timeline-utils";
import { formatTime } from "../chat-utils";
import { MarkdownBlock } from "./markdown-block";
import { TurnExecutionCard } from "./turn-execution-card";
import { renderInlineEvidence } from "./timeline-inline";
import { Badge, Button } from "./ui";

function firstText(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
    if (typeof value === "number") {
      return String(value);
    }
  }
  return "";
}

function statusCardContent(item) {
  const data = item.data || {};
  return firstText(data.markdown, data.summary, data.preview, data.reason, data.question, data.prompt, data.error, eventSummary(item));
}

function MessageBubble({ density, evidenceState, item, onToggleEvidence }) {
  const isAssistant = item.type === "assistant_message";
  const evidenceRefs = item.data?.evidence_refs || [];
  const textClass = density === "compact" ? "text-[14px] leading-7" : "text-[15px] leading-8";
  const message = firstText(item.data?.markdown, item.data?.message);
  if (isAssistant) {
    return (
      <div className="group flex gap-4">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white">
          <Bot size={14} />
        </div>
        <div className="min-w-0 flex-1 pt-0.5">
          <MarkdownBlock className={`text-slate-900 ${textClass} [overflow-wrap:anywhere]`} content={message} variant="body" />
          {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
          <div className="mt-1 text-[11px] text-slate-400 opacity-0 transition group-hover:opacity-100">{formatTime(item.created_at)}</div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-end">
      <div className="min-w-0 max-w-[85%]">
        <div className={`rounded-[1.4rem] bg-[#f4f4f4] px-4 py-2.5 text-slate-900 ${textClass}`}>
          <MarkdownBlock className="text-slate-900 [overflow-wrap:anywhere]" content={message} variant="body" />
        </div>
        {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
      </div>
    </div>
  );
}

function ApprovalCard({ item, onResolveApproval, resolvedApprovalIds, resolvingApprovalIds, supersededApprovalIds, supersededApprovals }) {
  const approval = item.data || {};
  const resolved = resolvedApprovalIds?.has(approval.approval_id);
  const pending = resolvingApprovalIds?.has(approval.approval_id);
  const superseded = supersededApprovalIds?.has(approval.approval_id);
  const replacement = superseded ? supersededApprovals?.[approval.approval_id] : null;
  const disabled = Boolean(resolved || pending || superseded);
  const reason = firstText(approval.reason, approval.message, approval.name);
  const title = superseded ? "审批已被新动作替代" : resolved ? "审批已处理" : pending ? "审批提交中…" : "需要审批";
  return (
    <div className={`rounded-xl border px-4 py-3 ${superseded || resolved ? "border-slate-200 bg-slate-50 text-slate-600" : "border-orange-200 bg-orange-50 text-orange-950"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlert size={15} />
            <span className="[overflow-wrap:anywhere]">{title}</span>
          </div>
          <MarkdownBlock className="mt-1.5 [overflow-wrap:anywhere]" content={reason} />
          <div className="mt-1 text-[11px] text-orange-700 [overflow-wrap:anywhere]">{approval.name}</div>
          {superseded && replacement?.newApprovalId ? <div className="mt-1 text-[11px] text-slate-500 [overflow-wrap:anywhere]">已由新的审批 {replacement.newApprovalId} 替代</div> : null}
        </div>
        <Badge className="bg-white text-orange-900">{approval.approval_id}</Badge>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, true)}>{pending ? "处理中…" : "批准"}</Button>
        <Button size="sm" variant="danger" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, false)}>拒绝</Button>
      </div>
    </div>
  );
}

function StatusEventCard({ item }) {
  const isFailure = item.type === "approval_expired";
  return (
    <div className={`rounded-xl border px-4 py-3 ${isFailure ? "border-rose-200 bg-rose-50" : "border-slate-200 bg-slate-50"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            {isFailure ? <AlertTriangle size={15} className="text-rose-600" /> : <FileText size={15} className="text-slate-500" />}
            <span className="[overflow-wrap:anywhere]">{systemEventLabels[item.type] || item.type}</span>
          </div>
          <MarkdownBlock className="mt-1.5 [overflow-wrap:anywhere]" content={statusCardContent(item)} variant="muted" />
        </div>
        <div className="text-[11px] text-slate-400">{formatTime(item.created_at)}</div>
      </div>
    </div>
  );
}

function TimelineItem(props) {
  if (props.item.type === "local_user" || props.item.type === "assistant_message") {
    return <MessageBubble {...props} />;
  }
  if (props.item.type === "turn_card") {
    return <TurnExecutionCard {...props} expanded={props.expandedItems.has(props.item.event_id)} onToggle={props.onToggleItem} />;
  }
  if (props.item.type === "approval_required") {
    return <ApprovalCard {...props} />;
  }
  return <StatusEventCard item={props.item} />;
}

export function ChatTimeline(props) {
  const { pendingApprovals = [], running, timeline } = props;
  const timelineApprovalIds = new Set(timeline.map((item) => item?.data?.approval_id).filter(Boolean));
  const visiblePendingApprovals = pendingApprovals.filter((item) => !timelineApprovalIds.has(item.approval_id));
  return (
    <div className="mx-auto flex min-w-0 w-full max-w-3xl flex-col gap-6 overflow-x-hidden">
      {timeline.map((item) => <TimelineItem key={item.event_id} {...props} item={item} />)}
      {visiblePendingApprovals.map((approval) => (
        <ApprovalCard
          key={approval.approval_id}
          item={{ event_id: `pending-${approval.approval_id}`, type: "approval_required", data: approval }}
          onResolveApproval={props.onResolveApproval}
          resolvedApprovalIds={props.resolvedApprovalIds}
          resolvingApprovalIds={props.resolvingApprovalIds}
          supersededApprovalIds={props.supersededApprovalIds}
          supersededApprovals={props.supersededApprovals}
        />
      ))}
      {running ? (
        <div className="flex gap-4">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white">
            <Bot size={14} />
          </div>
          <div className="flex min-w-0 items-center gap-2 pt-1.5 text-sm text-slate-500">
            <LoaderCircle size={14} className="animate-spin shrink-0" />
            <span className="[overflow-wrap:anywhere]">正在继续执行…</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
