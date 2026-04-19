import React from "react";
import {
  Bot,
  Brain,
  ChevronDown,
  ChevronUp,
  Download,
  Eye,
  FileText,
  LoaderCircle,
  MessageSquareText,
  ArrowRightLeft,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import { formatTime } from "../chat-utils";
import { buildTurnFlowBlocks } from "./chat-flow-model";
import { MarkdownBlock } from "./markdown-block";
import { ReportInline, renderInlineEvidence } from "./timeline-inline";
import { Badge, Button } from "./ui";

function DetailContent({ content }) {
  const value = typeof content === "string" ? content.trim() : "";
  if (!value) {
    return null;
  }
  const looksStructured = value.startsWith("{")
    || value.startsWith("[")
    || value.startsWith("<")
    || value.includes("\n");
  if (looksStructured) {
    return <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-2xl bg-slate-950 px-4 py-3 text-xs leading-6 text-slate-100 [overflow-wrap:anywhere]">{value}</pre>;
  }
  return <MarkdownBlock className="mt-3" content={value} variant="muted" />;
}

function BlockChips({ items, tone = "neutral" }) {
  const chips = items.filter(Boolean);
  if (!chips.length) {
    return null;
  }
  const chipClassName = tone === "alert"
    ? "bg-orange-100 text-orange-900"
    : tone === "tool"
      ? "bg-sky-100 text-sky-900"
      : tone === "observation"
        ? "bg-emerald-100 text-emerald-900"
        : tone === "handoff"
          ? "bg-amber-100 text-amber-900"
          : "bg-slate-100 text-slate-700";
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {chips.map((chip) => <span key={chip} className={`rounded-full px-2.5 py-1 text-[11px] ${chipClassName}`}>{chip}</span>)}
    </div>
  );
}

function ThoughtBlock({ block }) {
  return (
    <details className="rounded-[1.4rem] border border-slate-200 bg-slate-100/90 px-4 py-3 text-slate-700">
      <summary className="cursor-pointer list-none">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
              <Brain size={15} className="text-slate-500" />
              <span className="[overflow-wrap:anywhere]">{block.title}</span>
            </div>
            <MarkdownBlock className="mt-2" content={block.summary} variant="muted" />
            <BlockChips items={block.chips} />
          </div>
          <div className="flex shrink-0 items-center gap-2 text-[11px] text-slate-400">
            <span>{formatTime(block.created_at)}</span>
            <ChevronDown size={14} />
          </div>
        </div>
      </summary>
      <DetailContent content={block.detail} />
    </details>
  );
}

function InlineFlowBlock({ block }) {
  const config = {
    participant_handoff: {
      icon: ArrowRightLeft,
      borderClassName: "border-amber-200 bg-amber-50/90 text-amber-950",
      tone: "handoff",
    },
    participant_message: {
      icon: MessageSquareText,
      borderClassName: "border-slate-200 bg-white text-slate-900",
      tone: "neutral",
    },
    tool_action: {
      icon: Wrench,
      borderClassName: "border-sky-200 bg-sky-50/90 text-sky-950",
      tone: "tool",
    },
    tool_observation: {
      icon: Eye,
      borderClassName: "border-emerald-200 bg-emerald-50/90 text-emerald-950",
      tone: "observation",
    },
  }[block.type];
  const Icon = config.icon;
  const detail = typeof block.detail === "string" ? block.detail.trim() : "";
  if (block.type === "tool_observation" && detail) {
    return (
      <details className={`rounded-[1.4rem] border px-4 py-3 ${config.borderClassName}`}>
        <summary className="cursor-pointer list-none">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Icon size={15} />
                <span className="[overflow-wrap:anywhere]">{block.title}</span>
              </div>
              <MarkdownBlock className="mt-2" content={block.summary} variant="muted" />
              <BlockChips items={block.chips} tone={config.tone} />
            </div>
            <div className="flex shrink-0 items-center gap-2 text-[11px] opacity-70">
              <span>{formatTime(block.created_at)}</span>
              <ChevronDown size={14} />
            </div>
          </div>
        </summary>
        <DetailContent content={detail} />
      </details>
    );
  }
  return (
    <div className={`rounded-[1.4rem] border px-4 py-3 ${config.borderClassName}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <Icon size={15} />
            <span className="[overflow-wrap:anywhere]">{block.title}</span>
          </div>
          <MarkdownBlock className="mt-2" content={block.summary} variant="muted" />
          <BlockChips items={block.chips} tone={config.tone} />
          <DetailContent content={detail} />
        </div>
        <div className="shrink-0 text-[11px] opacity-70">{formatTime(block.created_at)}</div>
      </div>
    </div>
  );
}

function FlowBlock({ block }) {
  if (block.type === "assistant_thought") {
    return <ThoughtBlock block={block} />;
  }
  return <InlineFlowBlock block={block} />;
}

function TurnSummaryLine({ label, value }) {
  if (!value) {
    return null;
  }
  return (
    <div className="text-sm leading-6 text-slate-600">
      <span className="mr-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">{label}</span>
      <span className="[overflow-wrap:anywhere]">{value}</span>
    </div>
  );
}

export function TurnFlowThread({
  expanded,
  item,
  onDownloadReport,
  onToggle,
  onToggleReport,
  reportOpenIds,
  reportsById,
}) {
  const data = item.data || {};
  const blocks = buildTurnFlowBlocks(item);
  const reportId = data.report_id;
  const shouldExpand = expanded;
  return (
    <div className="rounded-[1.6rem] border border-slate-200 bg-white px-4 py-3 shadow-[0_12px_30px_rgba(15,23,42,0.05)]">
      <button type="button" onClick={() => onToggle(item.event_id, item.turn_id)} className="w-full text-left">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge className="bg-slate-100 text-slate-700">{data.status_label}</Badge>
              {data.tool_count ? <Badge className="bg-slate-100 text-slate-600">{data.tool_count} 工具</Badge> : null}
              {data.approval_count ? <Badge className="bg-slate-100 text-slate-600">{data.approval_count} 审批</Badge> : null}
              {data.evidence_count ? <Badge className="bg-slate-100 text-slate-600">{data.evidence_count} 证据</Badge> : null}
            </div>
            <div className="mt-3 text-[15px] font-medium leading-7 text-slate-900 [overflow-wrap:anywhere]">{data.goal || "本轮执行"}</div>
            <div className="mt-2 grid gap-1">
              <TurnSummaryLine label="最近动作" value={data.action_summary} />
              {!shouldExpand ? <TurnSummaryLine label="结果" value={data.result_summary} /> : null}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2 text-[11px] text-slate-400">
            <span>{formatTime(item.created_at)}</span>
            {shouldExpand ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </div>
        </div>
      </button>

      {shouldExpand ? (
        <div className="mt-4 space-y-3 border-l border-slate-200 pl-4">
          {blocks.length ? blocks.map((block) => <FlowBlock key={block.block_id} block={block} />) : <div className="rounded-[1.4rem] border border-dashed border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-500">当前没有可展示的过程块。</div>}
          {reportId ? (
            <div className="pt-1">
              <div className="flex flex-wrap gap-2">
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
              {reportOpenIds.has(reportId) && reportsById[reportId] ? <ReportInline report={reportsById[reportId]} onDownload={onDownloadReport} /> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function ApprovalRequestBlock({
  item,
  onResolveApproval,
  resolvedApprovalIds,
  resolvingApprovalIds,
  supersededApprovalIds,
  supersededApprovals,
}) {
  const approval = item.data || {};
  const resolved = resolvedApprovalIds?.has(approval.approval_id);
  const pending = resolvingApprovalIds?.has(approval.approval_id);
  const superseded = supersededApprovalIds?.has(approval.approval_id);
  const replacement = superseded ? supersededApprovals?.[approval.approval_id] : null;
  const disabled = Boolean(resolved || pending || superseded);
  const title = superseded ? "审批已被新动作替代" : resolved ? "审批已处理" : pending ? "审批提交中…" : "审批请求";
  return (
    <div className={`rounded-[1.4rem] border px-4 py-3 ${superseded || resolved ? "border-slate-200 bg-slate-50 text-slate-600" : "border-orange-200 bg-orange-50 text-orange-950"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldAlert size={15} />
            <span className="[overflow-wrap:anywhere]">{title}</span>
          </div>
          <MarkdownBlock className="mt-2" content={approval.reason || approval.message || approval.name} variant="muted" />
          <BlockChips items={[approval.name, replacement?.newApprovalId ? `替代 ${replacement.newApprovalId}` : ""].filter(Boolean)} tone="alert" />
        </div>
        <div className="shrink-0 text-[11px] text-orange-700">{formatTime(item.created_at)}</div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, true)}>{pending ? "处理中…" : "批准"}</Button>
        <Button size="sm" variant="danger" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, false)}>拒绝</Button>
      </div>
    </div>
  );
}

export function AssistantMessageBlock({ density, evidenceState, item, onToggleEvidence }) {
  const textClass = density === "compact" ? "text-[14px] leading-7" : "text-[15px] leading-8";
  const message = item.data?.markdown || item.data?.message || "";
  const evidenceRefs = item.data?.evidence_refs || [];
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

export function RunningContinuation() {
  return (
    <div className="flex gap-4">
      <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-white">
        <Bot size={14} />
      </div>
      <div className="flex min-w-0 items-center gap-2 pt-1.5 text-sm text-slate-500">
        <LoaderCircle size={14} className="shrink-0 animate-spin" />
        <span className="[overflow-wrap:anywhere]">正在继续执行…</span>
      </div>
    </div>
  );
}
