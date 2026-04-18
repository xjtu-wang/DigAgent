import React from "react";
import { AlertTriangle, Bot, ExternalLink, FileText, LoaderCircle, ShieldAlert, Sparkles, Wrench } from "lucide-react";
import { eventSummary, systemEventLabels } from "../timeline-utils";
import { formatTime } from "../chat-utils";
import { MarkdownBlock } from "./markdown-block";
import { TurnExecutionCard } from "./turn-execution-card";
import { CollapsibleSection, FactGrid, renderInlineEvidence, ReportInline } from "./timeline-inline";
import { Badge, Button } from "./ui";

const TURN_COUNT_FIELDS = [
  ["semantic_action_count", "语义动作"],
  ["raw_event_count", "原始事件"],
  ["tool_count", "工具"],
  ["approval_count", "审批"],
  ["evidence_count", "证据"],
  ["artifact_count", "附件"],
];

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

function stringifyValue(value) {
  if (value == null || value === "") {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
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
          <MarkdownBlock className={`text-slate-900 ${textClass}`} content={message} variant="body" />
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
          <MarkdownBlock className="text-slate-900" content={message} variant="body" />
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
  const reason = firstText(approval.reason, approval.message, approval.name);
  return (
    <div className={`rounded-xl border px-4 py-3 ${superseded || resolved ? "border-slate-200 bg-slate-50 text-slate-600" : "border-orange-200 bg-orange-50 text-orange-950"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlert size={15} />
            {superseded ? "审批已被新动作替代" : resolved ? "审批已处理" : pending ? "审批提交中…" : "需要审批"}
          </div>
          <MarkdownBlock className="mt-1.5" content={reason} />
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
          <MarkdownBlock className="mt-1.5" content={statusCardContent(item)} variant="muted" />
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

function AssistantProcessCard({ item }) {
  const data = item.data || {};
  const message = firstText(data.message, data.preview);
  const preview = data.preview && data.preview !== message ? data.preview : message;
  return (
    <div className="group flex gap-4">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-100 text-slate-700">
        <Sparkles size={14} />
      </div>
      <div className="min-w-0 flex-1 pt-0.5">
        <details className="rounded-[1.5rem] border border-slate-200 bg-slate-50 px-4 py-3">
          <summary className="cursor-pointer list-none">
            <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
              <span>{firstText(data.title, "处理中")}</span>
              {data.chunk_count ? <Badge className="bg-white text-slate-600">{data.chunk_count} 段</Badge> : null}
            </div>
            <MarkdownBlock className="mt-2" content={preview} variant="muted" />
          </summary>
          {message && message !== preview ? <MarkdownBlock className="mt-3" content={message} variant="muted" /> : null}
        </details>
        <div className="mt-1 text-[11px] text-slate-400 opacity-0 transition group-hover:opacity-100">{formatTime(item.created_at)}</div>
      </div>
    </div>
  );
}

function ToolSummaryCard({ item }) {
  const data = item.data || {};
  const summary = firstText(data.summary, data.raw_message, "暂无工具摘要。");
  const callArgs = stringifyValue(data.call_args);
  const rawOutput = firstText(data.raw_output, stringifyValue(data.raw_output_object));
  return (
    <div className="min-w-0 rounded-[1.6rem] border border-slate-200 bg-white px-5 py-4 shadow-[0_18px_44px_rgba(15,23,42,0.05)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
            <Wrench size={15} className="text-slate-500" />
            <span className="truncate" title={firstText(data.title, data.tool_name, "工具摘要")}>{firstText(data.title, data.tool_name, "工具摘要")}</span>
            {data.tool_name ? <Badge className="bg-slate-100 text-slate-700">{data.tool_name}</Badge> : null}
            {data.status ? <Badge className="bg-slate-100 text-slate-700">{data.status}</Badge> : null}
          </div>
          <MarkdownBlock className="mt-2" content={summary} />
        </div>
        <div className="text-[11px] text-slate-400">{formatTime(item.created_at)}</div>
      </div>
      {data.source_url ? (
        <a href={data.source_url} target="_blank" rel="noreferrer" className="mt-3 flex min-w-0 max-w-full items-start gap-1 text-sm text-sky-700 hover:text-sky-800">
          <ExternalLink size={13} className="mt-1 shrink-0" />
          <span className="min-w-0 break-all [overflow-wrap:anywhere]">{data.source_url}</span>
        </a>
      ) : null}
      <FactGrid facts={data.facts} />
      <div className="mt-3 grid gap-3">
        <CollapsibleSection label="请求消息" content={data.request_message} />
        <CollapsibleSection label="请求参数" content={callArgs} code />
        <CollapsibleSection label="响应摘要" content={data.body_excerpt} />
        <CollapsibleSection label="原始消息" content={stringifyValue(data.raw_message)} code />
        <CollapsibleSection label="原始输出" content={rawOutput} code />
      </div>
    </div>
  );
}

function TurnSummaryCard({ item, onDownloadReport, onToggleReport, reportOpenIds, reportsById }) {
  const data = item.data || {};
  const badges = TURN_COUNT_FIELDS
    .map(([key, label]) => (data[key] == null ? null : <Badge key={key} className="bg-slate-100 text-slate-600">{data[key]} {label}</Badge>))
    .filter(Boolean);
  const reportId = data.report_id;
  return (
    <div className="rounded-[1.6rem] border border-slate-200 bg-white px-5 py-4 shadow-[0_18px_44px_rgba(15,23,42,0.05)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
            <Sparkles size={15} className="text-slate-500" />
            <span>本轮摘要</span>
            {data.status_label ? <Badge className="bg-slate-100 text-slate-700">{data.status_label}</Badge> : null}
          </div>
          <div className="mt-1 text-[11px] text-slate-400">{data.turn_id}</div>
        </div>
        <div className="text-[11px] text-slate-400">{formatTime(item.created_at)}</div>
      </div>
      <MarkdownBlock className="mt-3" content={firstText(data.result_summary, "暂无结果摘要。")} />
      {badges.length ? <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">{badges}</div> : null}
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
  if (props.item.type === "assistant_process") {
    return <AssistantProcessCard {...props} />;
  }
  if (props.item.type === "tool_summary_card") {
    return <ToolSummaryCard {...props} />;
  }
  if (props.item.type === "turn_summary_card") {
    return <TurnSummaryCard {...props} />;
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
    <div className="mx-auto flex min-w-0 w-full max-w-3xl flex-col gap-6">
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
