import React from "react";
import { AlertTriangle, ArrowRight, BrainCircuit, ChevronDown, Eye, LoaderCircle, ShieldAlert, Wrench } from "lucide-react";
import { formatTime } from "../chat-utils";
import { renderInlineEvidence } from "./timeline-inline";
import { MarkdownBlock } from "./markdown-block";
import { Badge, Button } from "./ui";

function chips(values, className = "bg-white/80 text-[11px] text-slate-600") {
  return values.filter(Boolean).map((value) => <Badge key={String(value)} className={className}>{value}</Badge>);
}

function BubbleShell({ children, tone = "assistant" }) {
  const classes = tone === "user" ? "ml-auto max-w-[88%] rounded-[1.6rem] bg-[#f4f4f4] px-4 py-3 text-slate-900" : "min-w-0 flex-1";
  return <div className={classes}>{children}</div>;
}

export function AgentAvatar({ label = "A", muted = false }) {
  return (
    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[12px] font-semibold ${muted ? "bg-slate-200 text-slate-600" : "bg-slate-900 text-white"}`}>
      {label.slice(0, 2).toUpperCase()}
    </div>
  );
}

function speakerLabel(item, fallback = "DA") {
  return String(item?.data?.speaker_profile || item?.data?.participant_profile || fallback);
}
function looksStructured(value) {
  const text = typeof value === "string" ? value.trim() : "";
  return Boolean(text) && (text.startsWith("{") || text.startsWith("[") || text.startsWith("<") || text.includes("\n"));
}

function DetailContent({ content }) {
  const value = typeof content === "string" ? content.trim() : "";
  if (!value) {
    return null;
  }
  if (looksStructured(value)) {
    return <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words rounded-2xl bg-slate-950 px-4 py-3 text-xs leading-6 text-slate-100 [overflow-wrap:anywhere]">{value}</pre>;
  }
  return <MarkdownBlock className="mt-3" content={value} variant="muted" />;
}

function DetailSections({ details = [] }) {
  if (!details.length) {
    return null;
  }
  return (
    <div className="mt-3 space-y-2">
      {details.map((detail, index) => (
        <div key={`${detail.label}-${index}`} className="rounded-[1.1rem] border border-white/80 bg-white/90 px-3 py-2.5">
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">{detail.label}</div>
          {detail.code
            ? <pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words rounded-xl bg-slate-950 px-3 py-2.5 text-xs leading-6 text-slate-100 [overflow-wrap:anywhere]">{detail.content}</pre>
            : <MarkdownBlock className="mt-2" content={detail.content} variant="muted" />}
        </div>
      ))}
    </div>
  );
}

function ProcessItemShell({ chips: chipValues = [], detail = "", details = [], icon: Icon, item, summary, title, tone = "neutral", children = null }) {
  const hasStringDetail = Boolean(detail && detail.trim() && detail.trim() !== summary?.trim());
  const hasDetail = hasStringDetail || details.length > 0;
  const toneClassName = tone === "process"
    ? "border-slate-200 bg-slate-50/90"
    : tone === "tool"
      ? "border-sky-200 bg-sky-50/70"
      : tone === "observation"
        ? "border-emerald-200 bg-emerald-50/70"
        : tone === "handoff"
          ? "border-amber-200 bg-amber-50/70"
          : tone === "alert"
            ? "border-orange-200 bg-orange-50/80"
            : tone === "error"
              ? "border-rose-200 bg-rose-50/80"
              : "border-slate-200 bg-white";
  const chipsClassName = tone === "alert"
    ? "bg-white text-[11px] text-orange-700"
    : "bg-white/80 text-[11px] text-slate-600";
  const body = (
    <>
      <div className="flex min-w-0 items-start gap-3">
        <Icon size={15} className="mt-0.5 shrink-0 text-slate-500" />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-slate-900 [overflow-wrap:anywhere]">{title}</div>
          <div className="mt-1 text-sm leading-7 text-slate-600 [overflow-wrap:anywhere]">{summary}</div>
          {chipValues.length ? <div className="mt-2 flex flex-wrap gap-1.5">{chips(chipValues, chipsClassName)}</div> : null}
        </div>
        <div className="shrink-0 text-[11px] text-slate-400">{formatTime(item.created_at)}</div>
      </div>
      {children}
    </>
  );
  if (!hasDetail) {
    return <div className={`rounded-[1.35rem] border px-4 py-3 ${toneClassName}`}>{body}</div>;
  }
  return (
    <details className={`rounded-[1.35rem] border px-4 py-3 ${toneClassName}`}>
      <summary className="cursor-pointer list-none">
        <div className="flex items-start gap-3">
          <Icon size={15} className="mt-0.5 shrink-0 text-slate-500" />
          <div className="min-w-0 flex-1">
            <div className="text-sm font-medium text-slate-900 [overflow-wrap:anywhere]">{title}</div>
            <div className="mt-1 text-sm leading-7 text-slate-600 [overflow-wrap:anywhere]">{summary}</div>
            {chipValues.length ? <div className="mt-2 flex flex-wrap gap-1.5">{chips(chipValues, chipsClassName)}</div> : null}
          </div>
          <div className="flex shrink-0 items-center gap-2 text-[11px] text-slate-400">
            <span>{formatTime(item.created_at)}</span>
            <ChevronDown size={14} />
          </div>
        </div>
      </summary>
      {details.length ? <DetailSections details={details} /> : <DetailContent content={detail} />}
      {children}
    </details>
  );
}

function processConfig(process) {
  if (process.kind === "tool") {
    return { icon: Wrench, tone: "tool" };
  }
  if (process.kind === "agent") {
    return { icon: ArrowRight, tone: "handoff" };
  }
  if (process.kind === "approval") {
    return { icon: ShieldAlert, tone: "alert" };
  }
  if (process.kind === "notice") {
    return { icon: AlertTriangle, tone: process.severity === "error" ? "error" : "neutral" };
  }
  return { icon: BrainCircuit, tone: "process" };
}

export function ProcessTimelineItem({ process }) {
  const config = processConfig(process);
  return (
    <ProcessItemShell
      chips={process.badges || []}
      details={process.details || []}
      icon={config.icon}
      item={process}
      summary={process.summary || "执行过程已更新。"}
      title={process.title || "执行过程"}
      tone={config.tone}
    />
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
  const label = speakerLabel(item);
  const isRoot = label === "assistant" || label === "sisyphus-default" || label === "DA";
  return (
    <div className="group flex gap-4">
      <AgentAvatar label={label} muted={!isRoot} />
      <div className="min-w-0 flex-1 pt-0.5">
        <MarkdownBlock className={`text-slate-900 ${textClass} [overflow-wrap:anywhere]`} content={item.data?.markdown || item.data?.message} variant="body" />
        {renderInlineEvidence(evidenceRefs, evidenceState, onToggleEvidence)}
        <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
          {label ? <span className="[overflow-wrap:anywhere]">{label}</span> : null}
          <span>{formatTime(item.created_at)}</span>
        </div>
      </div>
    </div>
  );
}

export function ThoughtItem({ item }) {
  const detail = item.data?.detail || "";
  const summary = item.data?.summary || detail || "智能体正在生成过程输出。";
  return (
    <ProcessItemShell
      chips={[item.data?.speaker_profile]}
      detail={detail}
      icon={BrainCircuit}
      item={item}
      summary={summary}
      title={item.data?.title || "过程输出"}
      tone="process"
    />
  );
}

export function ToolItem({ item, observation = false }) {
  const facts = Array.isArray(item.data?.facts) ? item.data.facts : [];
  const detail = item.data?.detail || (facts.length ? facts.map((fact) => typeof fact === "string" ? fact : fact?.value || fact?.label || fact?.key).join("\n") : "");
  return (
    <ProcessItemShell
      chips={[
        item.data?.tool_name,
        observation ? item.data?.status : item.data?.argument_count ? `${item.data.argument_count} 参数` : null,
        observation ? item.data?.source_host : null,
      ]}
      detail={detail}
      icon={observation ? Eye : Wrench}
      item={item}
      summary={item.data?.summary || (observation ? "工具返回了结果。" : "工具动作已发起。")}
      title={item.data?.title || (observation ? "工具结果" : "工具动作")}
      tone={observation ? "observation" : "tool"}
    />
  );
}

export function ParticipantHandoffItem({ item }) {
  return (
    <ProcessItemShell
      chips={[item.data?.handoff_from, item.data?.handoff_to]}
      detail=""
      icon={ArrowRight}
      item={item}
      summary={item.data?.summary || "任务已转交给其他 Agent。"}
      title={`${item.data?.handoff_from || "assistant"} -> ${item.data?.handoff_to || "agent"}`}
      tone="handoff"
    />
  );
}

export function ParticipantMessageItem({ item }) {
  const participant = item.data?.participant_profile || item.data?.speaker_profile || "agent";
  return (
    <ProcessItemShell
      chips={[participant]}
      detail={item.data?.markdown || item.data?.message || ""}
      icon={BrainCircuit}
      item={item}
      summary={item.data?.summary || item.data?.message || "参与者返回了阶段结果。"}
      title={`@${participant}`}
      tone="neutral"
    />
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
    <ProcessItemShell
      chips={[approval.name || approval.approval_id, replacement?.newApprovalId ? `替代 ${replacement.newApprovalId}` : null]}
      detail={approval.reason || approval.message || approval.name || ""}
      icon={ShieldAlert}
      item={item}
      summary={approval.reason || approval.message || approval.name || "执行被挂起，等待审批。"}
      title={title}
      tone="alert"
    >
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, true)}>{pending ? "处理中..." : "批准"}</Button>
        <Button size="sm" variant="danger" disabled={disabled} onClick={() => !disabled && onResolveApproval(approval, false)}>拒绝</Button>
      </div>
    </ProcessItemShell>
  );
}

export function NoticeItem({ item }) {
  const isFailure = item.data?.severity === "error";
  return (
    <ProcessItemShell
      chips={[item.data?.title]}
      detail={item.data?.summary || ""}
      icon={AlertTriangle}
      item={item}
      summary={item.data?.summary || "系统返回了一条执行通知。"}
      title={item.data?.title || "系统通知"}
      tone={isFailure ? "error" : "neutral"}
    />
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
