import React from "react";
import { ChevronDown, ChevronUp, Download, ExternalLink, FileJson, FileText, Gauge, Sparkles, Wrench } from "lucide-react";
import { formatTime } from "../chat-utils";
import { MarkdownBlock } from "./markdown-block";
import { ReportInline, renderInlineEvidence } from "./timeline-inline";
import { Badge, Button } from "./ui";

const COUNT_FIELDS = [
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

function SummaryRow({ label, value }) {
  if (!value) {
    return null;
  }
  return (
    <div className="grid gap-1">
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{label}</div>
      <MarkdownBlock className="[overflow-wrap:anywhere]" content={value} />
    </div>
  );
}

function ChipRow({ chips }) {
  if (!chips?.length) {
    return null;
  }
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {chips.map((chip) => <Badge key={chip} className="bg-slate-100 text-slate-600">{chip}</Badge>)}
    </div>
  );
}

function Section({ children, count, emptyLabel, icon: Icon, title }) {
  return (
    <section className="rounded-[1.4rem] border border-slate-100 bg-[linear-gradient(180deg,#ffffff_0%,#f8fafc_100%)] p-3.5">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">
        <Icon size={12} />
        <span>{title}</span>
        <Badge className="bg-white text-slate-600">{count}</Badge>
      </div>
      {count ? children : <div className="rounded-xl border border-dashed border-slate-200 px-3 py-2.5 text-sm text-slate-500">{emptyLabel}</div>}
    </section>
  );
}

function EventRow({ item }) {
  const detail = firstText(item.detail);
  const showDetail = detail && detail !== item.summary;
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
            <span className="[overflow-wrap:anywhere]">{firstText(item.title, item.type, "事件")}</span>
          </div>
          <MarkdownBlock className="mt-2 text-sm leading-6 text-slate-700 [overflow-wrap:anywhere]" content={firstText(item.summary, "暂无摘要。")} variant="muted" />
          <ChipRow chips={item.chips} />
        </div>
        <div className="shrink-0 text-[11px] text-slate-400">{formatTime(item.created_at)}</div>
      </div>
      {showDetail ? (
        <details className="mt-2 rounded-xl border border-slate-100 bg-slate-50 px-3 py-2.5">
          <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">展开全文</summary>
          <MarkdownBlock className="mt-2 text-sm leading-6 text-slate-700 [overflow-wrap:anywhere]" content={detail} variant="muted" />
        </details>
      ) : null}
    </div>
  );
}

function ToolRow({ item }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-3 py-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
            <span className="[overflow-wrap:anywhere]">{firstText(item.title, item.tool_name, "工具摘要")}</span>
            {item.tool_name ? <Badge className="bg-slate-100 text-slate-700">{item.tool_name}</Badge> : null}
          </div>
          <MarkdownBlock className="mt-2 text-sm leading-6 text-slate-700 [overflow-wrap:anywhere]" content={firstText(item.summary, "暂无工具摘要。")} variant="muted" />
          {item.source_url ? (
            <a href={item.source_url} target="_blank" rel="noreferrer" className="mt-2 flex min-w-0 max-w-full items-start gap-1 text-sm text-sky-700 hover:text-sky-800">
              <ExternalLink size={13} className="mt-1 shrink-0" />
              <span className="min-w-0 [overflow-wrap:anywhere]">{item.source_url}</span>
            </a>
          ) : null}
          <ChipRow chips={item.chips} />
        </div>
        <div className="shrink-0 text-[11px] text-slate-400">{formatTime(item.created_at)}</div>
      </div>
    </div>
  );
}

function DebugBlock({ label, value }) {
  const content = stringifyValue(value);
  if (!content) {
    return null;
  }
  return (
    <details className="rounded-xl border border-slate-200 bg-white px-3 py-2.5">
      <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</summary>
      <pre className="mt-2 whitespace-pre-wrap break-words text-xs leading-6 text-slate-700 [overflow-wrap:anywhere]">{content}</pre>
    </details>
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
  const data = item.data || {};
  const workflow = data.workflow?.items || [];
  const tools = data.tools?.items || [];
  const activity = data.activity?.items || [];
  const debug = data.debug || {};
  const reportId = data.report_id;
  const evidenceRefs = debug.turn?.evidence_ids || [];
  const countBadges = COUNT_FIELDS
    .map(([key, label]) => (data[key] == null ? null : <Badge key={key} className="bg-slate-100 text-slate-600">{data[key]} {label}</Badge>))
    .filter(Boolean);

  return (
    <div className="min-w-0 rounded-[1.7rem] border border-slate-200 bg-white px-5 py-4 shadow-[0_18px_44px_rgba(15,23,42,0.05)]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm font-medium text-slate-900">
            <Gauge size={15} className="text-slate-500" />
            <span>本轮执行</span>
            <Badge className="bg-slate-100 text-slate-700">{data.status_label}</Badge>
          </div>
          <div className="mt-1 text-[11px] text-slate-400 [overflow-wrap:anywhere]">{data.turn_id}</div>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-slate-400">
          <span>{formatTime(item.created_at)}</span>
          <button type="button" onClick={() => onToggle(item.event_id, item.turn_id)} className="inline-flex items-center gap-1 rounded-full border border-slate-200 px-2.5 py-1 text-slate-600 hover:bg-slate-50">
            <FileJson size={12} />
            {expanded ? "收起 Debug" : "展开 Debug"}
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

      {countBadges.length ? <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-slate-500">{countBadges}</div> : null}

      <div className="mt-4 grid gap-4">
        <Section icon={Sparkles} title="Workflow" count={data.workflow?.count || 0} emptyLabel="暂无 workflow 事件。">
          <div className="grid gap-3">{workflow.map((entry) => <EventRow key={entry.event_id} item={entry} />)}</div>
        </Section>
        <Section icon={Wrench} title="Tools" count={data.tools?.count || 0} emptyLabel="暂无工具调用。">
          <div className="grid gap-3">{tools.map((tool) => <ToolRow key={tool.tool_call_id || tool.event_id} item={tool} />)}</div>
        </Section>
        <Section icon={FileText} title="Activity" count={data.activity?.count || 0} emptyLabel="暂无活动记录。">
          <div className="grid gap-3">{activity.map((entry) => <EventRow key={entry.event_id} item={entry} />)}</div>
        </Section>
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
        <Section icon={FileJson} title="Debug" count={(debug.tool_calls?.length || 0) + 3} emptyLabel="暂无调试数据。">
          <div className="grid gap-3">
            <DebugBlock label="Turn 对象" value={debug.turn} />
            <DebugBlock label="Messages" value={debug.messages} />
            <DebugBlock label="Recent Events" value={debug.recent_events} />
            {(debug.tool_calls || []).map((tool, index) => (
              <DebugBlock key={tool.tool_call_id || `${tool.tool_name || "tool"}-${index}`} label={`Tool ${tool.tool_name || index + 1}`} value={tool} />
            ))}
          </div>
        </Section>
      ) : null}
    </div>
  );
}
