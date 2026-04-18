import React from "react";
import { AlertTriangle, Bot, FileText, LoaderCircle, ShieldAlert } from "lucide-react";
import { eventSummary, systemEventLabels } from "../timeline-utils";
import { formatTime } from "../chat-utils";
import { TurnExecutionCard } from "./turn-execution-card";
import { renderInlineEvidence, ReportInline } from "./timeline-inline";
import { Badge, Button } from "./ui";

function MessageBubble({ density, evidenceState, item, onToggleEvidence }) {
  const isAssistant = item.type === "assistant_message";
  const evidenceRefs = item.data?.evidence_refs || [];
  const textClass = density === "compact" ? "text-[14px] leading-7" : "text-[15px] leading-8";
  if (isAssistant) {
    return (
      <div className="group flex gap-4">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white">
          <Bot size={14} />
        </div>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className={`whitespace-pre-wrap text-slate-900 ${textClass}`}>{item.data.message}</div>
          {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
          <div className="mt-1 text-[11px] text-slate-400 opacity-0 transition group-hover:opacity-100">{formatTime(item.created_at)}</div>
        </div>
      </div>
    );
  }
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%]">
        <div className={`rounded-[1.4rem] bg-[#f4f4f4] px-4 py-2.5 text-slate-900 ${textClass}`}>
          <div className="whitespace-pre-wrap">{item.data.message}</div>
        </div>
        {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
      </div>
    </div>
  );
}

function ApprovalCard({ item, onResolveApproval, resolvedApprovalIds, resolvingApprovalIds, supersededApprovalIds, supersededApprovals }) {
  const approval = item.data;
  const resolved = resolvedApprovalIds?.has(approval.approval_id);
  const pending = resolvingApprovalIds?.has(approval.approval_id);
  const superseded = supersededApprovalIds?.has(approval.approval_id);
  const replacement = superseded ? supersededApprovals?.[approval.approval_id] : null;
  const disabled = Boolean(resolved || pending || superseded);
  return (
    <div className={`rounded-xl border px-4 py-3 ${superseded || resolved ? "border-slate-200 bg-slate-50 text-slate-600" : "border-orange-200 bg-orange-50 text-orange-950"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlert size={15} />
            {superseded ? "审批已被新动作替代" : resolved ? "审批已处理" : pending ? "审批提交中…" : "需要审批"}
          </div>
          <div className="mt-1.5 text-sm leading-7">{approval.reason || approval.name}</div>
          <div className="mt-1 text-[11px] text-orange-700">{approval.name}</div>
          {superseded && replacement?.newApprovalId ? <div className="mt-1 text-[11px] text-slate-500">已由新的审批 {replacement.newApprovalId} 替代</div> : null}
        </div>
        <Badge className="bg-white text-orange-900">{approval.approval_id}</Badge>
      </div>
      <div className="mt-3 flex gap-2">
        <Button size="sm" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, true)}>{pending ? "处理中…" : "批准"}</Button>
        <Button size="sm" variant="danger" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, false)}>拒绝</Button>
      </div>
    </div>
  );
}

function StatusEventCard({ evidenceState, item, onDownloadReport, onToggleEvidence, onToggleReport, reportOpenIds, reportsById }) {
  const reportId = item.data?.report_id;
  const evidenceRefs = item.data?.evidence_refs || (item.data?.evidence_id ? [item.data.evidence_id] : []);
  const isFailure = item.type === "failed" || item.type === "timed_out";
  return (
    <div className={`rounded-xl border px-4 py-3 ${isFailure ? "border-rose-200 bg-rose-50" : "border-slate-200 bg-slate-50"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            {isFailure ? <AlertTriangle size={15} className="text-rose-600" /> : <FileText size={15} className="text-slate-500" />}
            {systemEventLabels[item.type] || item.type}
          </div>
          <div className="mt-1.5 text-sm leading-7 text-slate-600">{eventSummary(item)}</div>
        </div>
        <div className="text-[11px] text-slate-400">{formatTime(item.created_at)}</div>
      </div>
      {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
      {reportId ? (
        <div className="mt-3">
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => onToggleReport(reportId)}>查看报告</Button>
            <Button size="sm" variant="secondary" onClick={() => onDownloadReport(reportId, "markdown")}>Markdown</Button>
            <Button size="sm" variant="secondary" onClick={() => onDownloadReport(reportId, "pdf")}>PDF</Button>
          </div>
          {reportOpenIds.has(reportId) && reportsById[reportId] ? <ReportInline report={reportsById[reportId]} onDownload={onDownloadReport} /> : null}
        </div>
      ) : null}
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
  return <StatusEventCard {...props} />;
}

export function ChatTimeline(props) {
  const { pendingApprovals = [], running, timeline } = props;
  const timelineApprovalIds = new Set(timeline.map((item) => item?.data?.approval_id).filter(Boolean));
  const visiblePendingApprovals = pendingApprovals.filter((item) => !timelineApprovalIds.has(item.approval_id));
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
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
          <div className="flex items-center gap-2 pt-1.5 text-sm text-slate-500">
            <LoaderCircle size={14} className="animate-spin" />
            正在继续执行…
          </div>
        </div>
      ) : null}
    </div>
  );
}
