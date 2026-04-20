import React, { useMemo } from "react";
import { compactText, formatTime } from "../chat-utils";
import { buildTurnInspectorStats } from "../inspector-store";
import { turnGoal, turnTargetSummary } from "../turn-utils";
import { eventCountLabel, responseCharsLabel, workflowCountLabel } from "../ui-copy";
import { StatusPill } from "./status-pill";

export function ExecutionPanel({ activityEvents, currentTurn, messages, onSelectTurn, planGraph, turns }) {
  const stats = useMemo(() => buildTurnInspectorStats(currentTurn, messages, activityEvents, planGraph), [activityEvents, currentTurn, messages, planGraph]);
  return (
    <div className="grid gap-4">
      <section className="rounded-[1.8rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] p-4 shadow-[var(--app-shadow-soft)]">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-[color:var(--app-text)]">当前执行</div>
            <div className="mt-1 text-xs text-[color:var(--app-text-soft)]">{currentTurn?.turn_id || "当前还没有选中的执行"}</div>
          </div>
          <StatusPill status={currentTurn?.status || "idle"} />
        </div>
        <div className="mt-4 grid gap-4">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-faint)]">目标</div>
            <div className="text-sm leading-7 text-[color:var(--app-text-soft)]">{turnGoal(currentTurn, messages.find((item) => item.turn_id === currentTurn?.turn_id && item.role === "user")) || "发送一条消息后，这里会显示本轮执行的目标。"}</div>
          </div>
          {turnTargetSummary(currentTurn || {}) ? (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-faint)]">目标范围</div>
              <div className="text-sm leading-7 text-[color:var(--app-text-soft)]">{turnTargetSummary(currentTurn)}</div>
            </div>
          ) : null}
        </div>
        <div className="mt-4 grid gap-2 text-xs text-[color:var(--app-text-soft)]">
          <div>总耗时 {stats?.durationLabel || "未记录"}</div>
          <div>系统事件 {eventCountLabel(stats?.eventCount || 0)}</div>
          <div>执行流程节点 {workflowCountLabel(stats?.nodeCount || 0)} · {stats?.graphSourceLabel || "无"}</div>
          <div>回复长度 {responseCharsLabel(stats?.responseChars || 0)}</div>
          <div>证据 {stats?.evidenceCount || 0} · 附件 {stats?.artifactCount || 0} · 审批 {stats?.approvalCount || 0}</div>
        </div>
        <div className="mt-4 rounded-[1.4rem] bg-[color:var(--app-panel-muted)] p-3 text-xs text-[color:var(--app-text-soft)]">
          {stats?.hasRecordedBudgetUsage
            ? `已记录的预算使用情况：工具调用 ${stats.budgetUsage.tool_calls_used}/${stats.budgetMax.max_tool_calls}，活跃工具 ${stats.budgetUsage.active_tools}/${stats.budgetMax.max_parallel_tools}，活跃子 Agent ${stats.budgetUsage.active_subagents}/${stats.budgetMax.max_parallel_subagents}，运行时长 ${Number(stats.budgetUsage.runtime_seconds_used || 0).toFixed(1)}/${stats.budgetMax.max_runtime_seconds} 秒`
            : "当前执行还没有持久化的预算用量记录，这里优先展示能从已保存数据中还原的真实统计。"}
        </div>
      </section>

      <section className="rounded-[1.8rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] p-4 shadow-[var(--app-shadow-soft)]">
        <div className="text-sm font-medium text-[color:var(--app-text)]">历史执行</div>
        <div className="mt-3 grid gap-2">
          {turns.length === 0 ? <div className="text-sm text-[color:var(--app-text-soft)]">当前会话还没有执行记录。</div> : null}
          {turns.map((turn) => (
            <button
              key={turn.turn_id}
              type="button"
              onClick={() => onSelectTurn(turn.turn_id)}
              className={`rounded-[1.4rem] border px-3 py-3 text-left ${currentTurn?.turn_id === turn.turn_id ? "border-[color:var(--app-border-strong)] bg-[color:var(--app-panel-muted)]" : "border-[color:var(--app-border)] bg-[color:var(--app-panel)]"}`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="truncate text-sm font-medium text-[color:var(--app-text)]">{compactText(turnGoal(turn), 72) || turn.turn_id}</div>
                <StatusPill status={turn.status} />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-[color:var(--app-text-faint)]">
                <span>{turn.turn_id}</span>
                <span>{formatTime(turn.created_at)}</span>
              </div>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
