import React from "react";
import { ChevronDown, ChevronUp, Download, FileJson, FileText, Gauge, Sparkles } from "lucide-react";
import { formatTime } from "../chat-utils";
import { MarkdownBlock } from "./markdown-block";
import { ReportInline, renderInlineEvidence } from "./timeline-inline";
import { Badge, Button } from "./ui";

function SummaryRow({ label, value }) {
  if (!value) {
    return null;
  }
  return (
    <div className="grid gap-1">
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
      <MarkdownBlock content={value} />
    </div>
  );
}

function EventPreview({ items }) {
  if (!items?.length) {
    return null;
  }
  return (
    <div className="grid gap-2">
      {items.map((item) => (
        <div key={item.event_id} className="rounded-2xl bg-slate-50 px-3 py-2.5 text-sm text-slate-600">
          <div className="flex items-center justify-between gap-3 text-[11px] text-slate-400">
            <span className="truncate" title={item.type}>{item.type}</span>
            <span>{formatTime(item.created_at)}</span>
          </div>
          <MarkdownBlock className="mt-1.5" content={item.summary} variant="muted" />
        </div>
      ))}
    </div>
  );
}

export function TurnExecutionCard({
  evidenceState,
  expanded,
  item,
  onDownloadReport,
  onToggle,
  onToggleEvidence,
  onToggleReport,
  reportOpenIds,
  reportsById,
}) {
  const data = item.data;
  const reportId = data.report_id;
  const evidenceRefs = data.raw?.turn?.evidence_ids || [];

  return (
    <div className="rounded-[1.7rem] border border-slate-200 bg-white px-5 py-4 shadow-[0_18px_44px_rgba(15,23,42,0.05)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            <Sparkles size={15} className="text-slate-500" />
            本轮执行
            <Badge className="bg-slate-100 text-slate-700">{data.status_label}</Badge>
          </div>
          <div className="mt-1 text-[11px] text-slate-400">{data.turn_id}</div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <span>{formatTime(item.created_at)}</span>
          <button type="button" onClick={() => onToggle(item.event_id)} className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-slate-600 hover:bg-slate-50">
            <FileJson size={12} />
            {expanded ? "收起详情" : "展开详情"}
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </div>
      </div>

      <div className="mt-4 grid gap-4">
        <SummaryRow label="目标" value={data.goal || "本轮执行未记录明确目标。"} />
        <SummaryRow label="目标范围" value={data.target} />
        <SummaryRow label="最近动作" value={data.action_summary || "暂无动作摘要。"} />
        <SummaryRow label="结果摘要" value={data.result_summary || "暂无结果摘要。"} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-slate-500">
        <Badge className="bg-slate-100 text-slate-600">{data.event_count} 条事件</Badge>
        <Badge className="bg-slate-100 text-slate-600">{data.approval_count} 次审批</Badge>
        <Badge className="bg-slate-100 text-slate-600">{data.evidence_count} 条证据</Badge>
        <Badge className="bg-slate-100 text-slate-600">{data.artifact_count} 个附件</Badge>
      </div>

      <div className="mt-4 rounded-[1.4rem] border border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] p-3.5">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
          <Gauge size={12} />
          动作预览
        </div>
        <EventPreview items={data.event_preview} />
      </div>

      {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}

      {reportId ? (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => onToggleReport(reportId)}>
            <FileText size={13} className="mr-1.5" />
            {reportOpenIds.has(reportId) ? "收起报告" : "查看报告"}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onDownloadReport(reportId, "markdown")}>
            <Download size={13} className="mr-1.5" />
            Markdown
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onDownloadReport(reportId, "pdf")}>
            <Download size={13} className="mr-1.5" />
            PDF
          </Button>
        </div>
      ) : null}

      {reportId && reportOpenIds.has(reportId) && reportsById[reportId] ? <ReportInline report={reportsById[reportId]} onDownload={onDownloadReport} /> : null}

      {expanded ? (
        <div className="mt-4 grid gap-3 rounded-[1.4rem] border border-slate-200 bg-slate-50 p-4">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">原始 turn / 事件</div>
          <pre className="overflow-x-auto whitespace-pre-wrap break-words text-xs leading-6 text-slate-700 [overflow-wrap:anywhere]">{JSON.stringify(data.raw, null, 2)}</pre>
        </div>
      ) : null}
    </div>
  );
}
