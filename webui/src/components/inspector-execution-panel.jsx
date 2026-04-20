import React, { useMemo } from "react";
import { compactText, formatTime } from "../chat-utils";
import { buildTurnInspectorStats } from "../inspector-store";
import { turnGoal, turnTargetSummary } from "../turn-utils";
import { StatusPill } from "./status-pill";

export function ExecutionPanel({ activityEvents, currentTurn, messages, onSelectTurn, planGraph, turns }) {
  const stats = useMemo(() => buildTurnInspectorStats(currentTurn, messages, activityEvents, planGraph), [activityEvents, currentTurn, messages, planGraph]);
  return (
    <div className="grid gap-4">
      <section className="rounded-[1.8rem] border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-sm font-medium text-slate-900">当前执行</div>
            <div className="mt-1 text-xs text-slate-500">{currentTurn?.turn_id || "当前没有选中的执行"}</div>
          </div>
          <StatusPill status={currentTurn?.status || "idle"} />
        </div>
        <div className="mt-4 grid gap-4">
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">目标</div>
            <div className="text-sm leading-7 text-slate-700">{turnGoal(currentTurn, messages.find((item) => item.turn_id === currentTurn?.turn_id && item.role === "user")) || "发送一条消息后会在这里看到执行目标。"}</div>
          </div>
          {turnTargetSummary(currentTurn || {}) ? (
            <div>
              <div className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">目标范围</div>
              <div className="text-sm leading-7 text-slate-700">{turnTargetSummary(currentTurn)}</div>
            </div>
          ) : null}
        </div>
        <div className="mt-4 grid gap-2 text-xs text-slate-500">
          <div>总耗时 {stats?.durationLabel || "未记录"}</div>
          <div>活动记录 {stats?.eventCount || 0}</div>
          <div>工作流节点 {stats?.nodeCount || 0} · {stats?.graphSourceLabel || "无"}</div>
          <div>回复长度 {stats?.responseChars || 0} chars</div>
          <div>证据 {stats?.evidenceCount || 0} · 附件 {stats?.artifactCount || 0} · 审批 {stats?.approvalCount || 0}</div>
        </div>
        <div className="mt-4 rounded-[1.4rem] bg-slate-50 p-3 text-xs text-slate-600">
          {stats?.hasRecordedBudgetUsage
            ? `记录的执行预算使用: 工具调用 ${stats.budgetUsage.tool_calls_used}/${stats.budgetMax.max_tool_calls}，活跃工具 ${stats.budgetUsage.active_tools}/${stats.budgetMax.max_parallel_tools}，活跃子代理 ${stats.budgetUsage.active_subagents}/${stats.budgetMax.max_parallel_subagents}，运行时长 ${Number(stats.budgetUsage.runtime_seconds_used || 0).toFixed(1)}/${stats.budgetMax.max_runtime_seconds}s`
            : "当前执行没有持久化的预算用量记录，面板优先展示可从持久化数据推导出的真实统计。"}
        </div>
      </section>

      <section className="rounded-[1.8rem] border border-slate-200 bg-white p-4 shadow-sm">
        <div className="text-sm font-medium text-slate-900">历史执行</div>
        <div className="mt-3 grid gap-2">
          {turns.length === 0 ? <div className="text-sm text-slate-500">当前会话还没有执行记录。</div> : null}
          {turns.map((turn) => (
            <button
              key={turn.turn_id}
              type="button"
              onClick={() => onSelectTurn(turn.turn_id)}
              className={`rounded-[1.4rem] border px-3 py-3 text-left ${currentTurn?.turn_id === turn.turn_id ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white"}`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="truncate text-sm font-medium text-slate-900">{compactText(turnGoal(turn), 72) || turn.turn_id}</div>
                <StatusPill status={turn.status} />
              </div>
              <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
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
