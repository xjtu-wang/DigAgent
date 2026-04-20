import React, { useEffect, useMemo, useRef, useState } from "react";
import { ChevronRight, Workflow, X } from "lucide-react";
import { buildWorkflowItems, compactText, formatTime, graphNodeQuestion, graphNodeStyles, projectWorkflowNode } from "../chat-utils";
import { eventSummary } from "../timeline-utils";
import { loadWorkflowPreferences, normalizeWorkflowPreferences, updateWorkflowPreferences } from "../settings-store";
import { eventCountLabel, inspectorTabLabel, workflowCountLabel } from "../ui-copy";
import { ExecutionPanel } from "./inspector-execution-panel";
import { StatusPill } from "./status-pill";
import { Button, Input, Select, Toggle } from "./ui";

export { StatusPill };

function FactChips({ items }) {
  if (!items?.length) {
    return null;
  }
  return <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-[color:var(--app-text-soft)]">{items.map((item) => <span key={item} className="rounded-full bg-[color:var(--app-panel-muted)] px-2.5 py-1">{item}</span>)}</div>;
}

function RawDebugBlock({ label, openByDefault, payload }) {
  if (!payload) {
    return null;
  }
  return (
    <details open={openByDefault} className="rounded-[1.4rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel-muted)] px-4 py-3">
      <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-faint)]">{label || "原始数据"}</summary>
      <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs leading-6 text-[color:var(--app-text-soft)]">{JSON.stringify(payload, null, 2)}</pre>
    </details>
  );
}

function StructuredSections({ sections }) {
  return (
    <div className="grid gap-3">
      {sections.map((section) => (
        <div key={section.label} className="rounded-[1.4rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-3">
          <div className="text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-faint)]">{section.label}</div>
          <div className="mt-2 text-sm leading-7 text-[color:var(--app-text-soft)]">{section.value}</div>
        </div>
      ))}
    </div>
  );
}

function workflowSettings(preferences) {
  return loadWorkflowPreferences(globalThis?.localStorage, normalizeWorkflowPreferences(preferences));
}

export function WorkflowView({ active, items, preferences, selectedNodeId, onSelect }) {
  const activeCardRef = useRef(null);
  const wasActiveRef = useRef(false);
  const workflowPreferences = preferences || normalizeWorkflowPreferences();

  useEffect(() => {
    if (!active || !workflowPreferences.focusActiveOnOpen || wasActiveRef.current) {
      wasActiveRef.current = active;
      return;
    }
    activeCardRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    wasActiveRef.current = active;
  }, [active, items, workflowPreferences.focusActiveOnOpen]);

  useEffect(() => {
    if (active && workflowPreferences.focusActiveOnUpdate) {
      activeCardRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }, [active, items, workflowPreferences.focusActiveOnUpdate]);

  if (!items.length) {
    return <div className="flex h-full min-h-[360px] items-center justify-center rounded-[1.8rem] border border-dashed border-[color:var(--app-border)] bg-[color:var(--app-panel)] text-sm text-[color:var(--app-text-soft)]">当前还没有可展示的执行流程。</div>;
  }

  return (
    <div className="flex h-full min-h-[420px] flex-col rounded-[1.8rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] shadow-[var(--app-shadow-soft)]">
      <div className="flex items-center justify-between border-b border-[color:var(--app-border)] px-4 py-3">
        <div>
          <div className="text-sm font-medium text-[color:var(--app-text)]">执行流程</div>
          <div className="mt-1 text-xs text-[color:var(--app-text-soft)]">按执行顺序展示关键步骤、摘要和当前状态，原始数据收起在调试区。</div>
        </div>
        <span className="rounded-full bg-[color:var(--app-panel-muted)] px-3 py-1 text-xs text-[color:var(--app-text-soft)]">{workflowCountLabel(items.length)}</span>
      </div>
      <div className="flex-1 overflow-y-auto rounded-b-[1.8rem] bg-[radial-gradient(circle_at_top,_rgba(52,211,153,0.08),_transparent_45%),linear-gradient(180deg,rgba(255,255,255,0.9)_0%,rgba(244,242,236,0.72)_100%)] px-4 py-4">
        <div className="grid gap-4">
          {items.map((node, index) => {
            const isSelected = selectedNodeId === node.node_id;
            const isPinned = isSelected || node.is_active;
            return (
              <div key={node.node_id} className="relative pl-10">
                {index < items.length - 1 ? <div className="absolute left-[15px] top-10 bottom-[-18px] w-px bg-slate-200" /> : null}
                <div className={`absolute left-0 top-4 flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold ${graphNodeStyles[node.status] || graphNodeStyles.pending}`}>{index + 1}</div>
                <button ref={isPinned ? activeCardRef : null} type="button" onClick={() => onSelect(node.node_id)} className={`w-full rounded-[1.6rem] border px-4 py-4 text-left transition hover:-translate-y-0.5 ${graphNodeStyles[node.status] || graphNodeStyles.pending} ${isSelected ? "ring-2 ring-slate-800/20" : ""}`}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{node.title}</div>
                      <div className="mt-1 text-xs opacity-70">{node.metadataBadges.join(" · ")}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {node.is_active ? <span className="rounded-full bg-white/70 px-3 py-1 text-xs">进行中</span> : null}
                      <StatusPill status={node.status} />
                    </div>
                  </div>
                  <div className="mt-3 text-sm leading-6 text-slate-700">{node.status === "waiting_user_input" ? graphNodeQuestion(node) : node.summary}</div>
                  <FactChips items={[node.startedAt ? `开始 ${formatTime(node.startedAt)}` : null, node.completedAt ? `结束 ${formatTime(node.completedAt)}` : null, node.lastEventAt ? `更新 ${formatTime(node.lastEventAt)}` : null, eventCountLabel(node.eventCount)].filter(Boolean)} />
                  {workflowPreferences.showEventMetadata && node.lastEventSummary ? <div className="mt-3 rounded-[1rem] bg-white/60 px-3 py-2 text-xs text-slate-600">{node.lastEventSummary}</div> : null}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function taskNodeActivity(item) {
  const node = projectWorkflowNode({ ...item.data, node_id: item.data?.node_id || item.event_id }, []);
  const prefix = item.type === "task_node_started" ? "开始" : item.type === "task_node_completed" ? "完成" : item.type === "task_node_waiting_approval" ? "等待确认" : "等待补充";
  return { title: `${prefix} · ${node.title}`, summary: node.summary, metadata: [node.kindLabel, item.type], debugPayload: item.data, debugLabel: node.debugLabel };
}

function genericActivity(item) {
  const data = item.data || {};
  if (item.type === "task_graph_updated") {
    const counts = [`进行中 ${(data.active_node_ids || []).length}`, `完成 ${(data.completed_node_ids || []).length}`, `阻塞 ${(data.blocked_node_ids || []).length}`];
    return { title: "执行流程已更新", summary: counts.join(" · "), metadata: [item.type], debugPayload: data, debugLabel: "图原始数据" };
  }
  if (item.type === "approval_resolved") {
    return { title: eventSummary(item), summary: data.status === "approved" ? "已批准，执行可以继续推进。" : "已拒绝，本次动作不会继续。", metadata: [item.type], debugPayload: data, debugLabel: "审批原始数据" };
  }
  if (item.type === "turn_terminal_recorded") {
    return { title: eventSummary(item), summary: [`耗时 ${data.duration_seconds ?? "?"}s`, `证据 ${(data.evidence_count || 0)}`, `附件 ${(data.artifact_count || 0)}`].join(" · "), metadata: [item.type], debugPayload: data, debugLabel: "结束态原始数据" };
  }
  return { title: eventSummary(item), summary: compactText(data.summary || data.reason || data.goal || data.preview || data.message || data.title || "无额外摘要。", 180), metadata: [item.type], debugPayload: data, debugLabel: "活动原始数据" };
}

function ActivityFeed({ events, preferences }) {
  const workflowPreferences = preferences || normalizeWorkflowPreferences();
  return (
    <div className="grid gap-3">
      {events.length === 0 ? <div className="rounded-[1.6rem] border border-dashed border-[color:var(--app-border)] px-4 py-6 text-sm text-[color:var(--app-text-soft)]">当前没有系统活动记录。</div> : null}
      {events.map((item) => {
        const card = item.type.startsWith("task_node_") ? taskNodeActivity(item) : genericActivity(item);
        return (
          <details key={item.event_id} open={false} className="rounded-[1.6rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-4 py-4 shadow-[var(--app-shadow-soft)]">
            <summary className="cursor-pointer list-none">
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-[color:var(--app-text)]">{compactText(card.title, 100)}</div>
                  <div className="mt-1 text-sm leading-6 text-[color:var(--app-text-soft)]">{card.summary}</div>
                  {workflowPreferences.showEventMetadata ? <FactChips items={[...card.metadata, formatTime(item.created_at)].filter(Boolean)} /> : null}
                </div>
                <div className="flex shrink-0 items-center gap-2 text-xs text-[color:var(--app-text-faint)]">
                  <span>{formatTime(item.created_at)}</span>
                  <ChevronRight size={14} />
                </div>
              </div>
            </summary>
            <div className="mt-4">
              <RawDebugBlock label={card.debugLabel} openByDefault={workflowPreferences.expandDebugDataByDefault} payload={card.debugPayload} />
            </div>
          </details>
        );
      })}
    </div>
  );
}

function SessionSettingsPanel({ catalog, displayPreferences, onDisplayPreferencesChange, runtimeDraft, onRuntimeDraftChange }) {
  const profiles = Array.isArray(catalog?.profiles) ? catalog.profiles : [];
  return (
    <div className="grid gap-4">
      <section className="rounded-[1.8rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] p-4 shadow-[var(--app-shadow-soft)]">
        <div className="text-sm font-medium text-[color:var(--app-text)]">当前发送设置</div>
        <div className="mt-4 grid gap-3">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">执行配置</div>
            <Select value={runtimeDraft.profile} onChange={(event) => onRuntimeDraftChange((current) => ({ ...current, profile: event.target.value }))}>
              {(profiles.length ? profiles : [{ name: runtimeDraft.profile }]).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </Select>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">代码仓库</div>
            <Input value={runtimeDraft.repoPath} onChange={(event) => onRuntimeDraftChange((current) => ({ ...current, repoPath: event.target.value }))} placeholder="仓库路径（可选）" />
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">目标域名</div>
            <Input value={runtimeDraft.domain} onChange={(event) => onRuntimeDraftChange((current) => ({ ...current, domain: event.target.value }))} placeholder="目标域名（可选）" />
          </div>
        </div>
      </section>
      <Toggle checked={runtimeDraft.autoApprove} onChange={(checked) => onRuntimeDraftChange((current) => ({ ...current, autoApprove: checked }))} label="本页后续消息自动确认审批" description="只影响当前浏览器页面里之后新发送的消息，不会自动处理已经出现的确认请求。若想对整个会话持久生效，请到“会话权限”里保存。" />
      <section className="rounded-[1.8rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] p-4 shadow-[var(--app-shadow-soft)]">
        <div className="text-sm font-medium text-[color:var(--app-text)]">执行详情显示</div>
        <div className="mt-4 grid gap-3">
          <Toggle checked={displayPreferences.showEventMetadata} onChange={(checked) => onDisplayPreferencesChange({ showEventMetadata: checked })} label="显示时间与标签" description="在执行流程和系统事件卡片里展示节点类型、时间戳和关键标签，不直接铺满原始 JSON。" />
          <Toggle checked={displayPreferences.expandDebugDataByDefault} onChange={(checked) => onDisplayPreferencesChange({ expandDebugDataByDefault: checked })} label="默认展开原始调试数据" description="关闭后仅显示摘要；需要排查时再点开原始 payload。" />
        </div>
      </section>
    </div>
  );
}

function InspectorBody(props) {
  const tabs = ["workflow", "execution", "activity", "session"].map((id) => ({ id, label: inspectorTabLabel(id) }));
  const { activityEvents, catalog, currentTab, currentTurn, messages, onChangeTab, onClose, onRuntimeDraftChange, onSelectNode, onSelectTurn, planGraph, runtimeDraft, selectedGraphNode, selectedNodeId, session, turns, workflowPreferences } = props;
  const [displayPreferences, setDisplayPreferences] = useState(() => workflowSettings(workflowPreferences));
  const workflowItems = useMemo(() => buildWorkflowItems(planGraph, activityEvents), [planGraph, activityEvents]);
  const selectedWorkflowNode = useMemo(() => workflowItems.find((item) => item.node_id === selectedNodeId) || workflowItems.find((item) => item.node_id === selectedGraphNode?.node_id) || workflowItems.find((item) => item.is_active) || workflowItems[0] || null, [selectedGraphNode?.node_id, selectedNodeId, workflowItems]);

  useEffect(() => {
    setDisplayPreferences(workflowSettings(workflowPreferences));
  }, [workflowPreferences]);

  function saveDisplayPreferences(patch) {
    const next = updateWorkflowPreferences(patch);
    setDisplayPreferences(next);
  }

  return (
    <div className="flex h-full flex-col bg-[color:var(--app-panel)]">
      <div className="border-b border-[color:var(--app-border)] px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-faint)]">执行详情</div>
            <div className="mt-1 text-base font-semibold text-[color:var(--app-text)]">{session?.title || "当前会话"}</div>
          </div>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-full text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel-muted)]"><X size={16} /></button>
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {tabs.map((tab) => <button key={tab.id} type="button" onClick={() => onChangeTab(tab.id)} className={`rounded-full px-3 py-1.5 text-sm transition ${currentTab === tab.id ? "bg-[color:var(--app-text)] text-white" : "text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel-muted)]"}`}>{tab.label}</button>)}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        {currentTab === "workflow" ? <div className="grid gap-4"><WorkflowView active items={workflowItems} preferences={displayPreferences} selectedNodeId={selectedNodeId} onSelect={onSelectNode} /><section className="rounded-[1.8rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] p-4 shadow-[var(--app-shadow-soft)]"><div className="flex items-center justify-between gap-3"><div><div className="text-sm font-medium text-[color:var(--app-text)]">{selectedWorkflowNode?.title || "步骤详情"}</div><div className="mt-1 text-xs text-[color:var(--app-text-soft)]">{selectedWorkflowNode ? selectedWorkflowNode.kindLabel : "选择一个执行步骤查看详情"}</div></div>{selectedWorkflowNode ? <StatusPill status={selectedWorkflowNode.status} /> : null}</div>{selectedWorkflowNode ? <div className="mt-4 grid gap-4"><StructuredSections sections={selectedWorkflowNode.detailSections} />{selectedWorkflowNode.block_reason ? <div className="rounded-[1.4rem] border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900">{selectedWorkflowNode.block_reason}</div> : null}<FactChips items={displayPreferences.showEventMetadata ? [selectedWorkflowNode.rawTitle && selectedWorkflowNode.rawTitle !== selectedWorkflowNode.title ? `原始标题 ${selectedWorkflowNode.rawTitle}` : null, ...selectedWorkflowNode.metadataBadges].filter(Boolean) : []} /><RawDebugBlock label={selectedWorkflowNode.debugLabel} openByDefault={displayPreferences.expandDebugDataByDefault} payload={selectedWorkflowNode.debugPayload} /></div> : <div className="mt-4 text-sm text-[color:var(--app-text-soft)]">当前没有可查看的执行流程详情。</div>}</section></div> : null}
        {currentTab === "execution" ? <ExecutionPanel activityEvents={activityEvents} currentTurn={currentTurn} messages={messages} onSelectTurn={onSelectTurn} planGraph={planGraph} turns={turns} /> : null}
        {currentTab === "activity" ? <ActivityFeed events={activityEvents} preferences={displayPreferences} /> : null}
        {currentTab === "session" ? <SessionSettingsPanel catalog={catalog} displayPreferences={displayPreferences} onDisplayPreferencesChange={saveDisplayPreferences} runtimeDraft={runtimeDraft} onRuntimeDraftChange={onRuntimeDraftChange} /> : null}
      </div>
    </div>
  );
}

export function InspectorDrawer(props) {
  if (!props.open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-40 flex bg-black/16">
      <button type="button" className="flex-1" aria-label="关闭执行详情" onClick={props.onClose} />
      <div className="h-full w-[min(100vw,460px)] border-l border-[color:var(--app-border)] bg-[color:var(--app-panel)] shadow-[var(--app-shadow)]">
        <InspectorBody {...props} />
      </div>
    </div>
  );
}

export function InspectorToggleButton({ open, onClick }) {
  return (
    <Button variant="ghost" size="sm" onClick={onClick}>
      <Workflow size={15} className="mr-2" />
      {open ? "收起详情" : "执行详情"}
    </Button>
  );
}
