import React, { useEffect, useMemo, useRef } from "react";
import { ChevronRight, Workflow, X } from "lucide-react";
import { buildWorkflowItems, compactText, formatTime, graphNodeQuestion, graphNodeStyles } from "../chat-utils";
import { eventSummary } from "../timeline-utils";
import { ExecutionPanel, KnowledgeBasePanel } from "./inspector-execution-panel";
import { StatusPill } from "./status-pill";
import { Button, Input, Select, Toggle } from "./ui";

export { StatusPill };

export function WorkflowView({ active, graph, events, preferences, selectedNodeId, onSelect }) {
  const activeCardRef = useRef(null);
  const wasActiveRef = useRef(false);
  const items = useMemo(() => buildWorkflowItems(graph, events), [graph, events]);
  const workflowPreferences = preferences || { focusActiveOnOpen: true, focusActiveOnUpdate: true, showEventMetadata: true };

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
    return <div className="flex h-full min-h-[360px] items-center justify-center rounded-[1.8rem] border border-dashed border-slate-300 bg-white text-sm text-slate-500">当前没有活跃 workflow。</div>;
  }

  return (
    <div className="flex h-full min-h-[420px] flex-col rounded-[1.8rem] border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div>
          <div className="text-sm font-medium text-slate-900">Agent Workflow</div>
          <div className="mt-1 text-xs text-slate-500">planning: {graph?.planning_state || "complete"} · version: {graph?.graph_version || 1} · 来源: {graph?.source_label || "未知"}</div>
        </div>
        <span className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-700">{items.length} steps</span>
      </div>
      <div className="flex-1 overflow-y-auto rounded-b-[1.8rem] bg-[radial-gradient(circle_at_top,_rgba(15,23,42,0.04),_transparent_48%),linear-gradient(180deg,#f8fafc_0%,#eef2f7_100%)] px-4 py-4">
        <div className="grid gap-4">
          {items.map((node, index) => {
            const isSelected = selectedNodeId === node.node_id;
            const isPinned = isSelected || node.is_active;
            const metaParts = [node.kind, node.toolName, node.ownerProfileName].filter(Boolean);
            return (
              <div key={node.node_id} className="relative pl-10">
                {index < items.length - 1 ? <div className="absolute left-[15px] top-10 bottom-[-18px] w-px bg-slate-200" /> : null}
                <div className={`absolute left-0 top-4 flex h-8 w-8 items-center justify-center rounded-full border text-xs font-semibold ${graphNodeStyles[node.status] || graphNodeStyles.pending}`}>{index + 1}</div>
                <button
                  ref={isPinned ? activeCardRef : null}
                  type="button"
                  onClick={() => onSelect(node.node_id)}
                  className={`w-full rounded-[1.6rem] border px-4 py-4 text-left transition hover:-translate-y-0.5 ${graphNodeStyles[node.status] || graphNodeStyles.pending} ${isSelected ? "ring-2 ring-slate-800/20" : ""}`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{node.title}</div>
                      <div className="mt-1 text-xs opacity-70">{metaParts.join(" · ")}</div>
                    </div>
                    <div className="flex items-center gap-2">
                      {node.is_active ? <span className="rounded-full bg-white/70 px-3 py-1 text-xs">active</span> : null}
                      <StatusPill status={node.status} />
                    </div>
                  </div>
                  <div className="mt-3 text-sm leading-6 text-slate-700">{node.status === "waiting_user_input" ? graphNodeQuestion(node) : node.summary || node.description}</div>
                  <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
                    {node.startedAt ? <span>started {formatTime(node.startedAt)}</span> : null}
                    {node.completedAt ? <span>completed {formatTime(node.completedAt)}</span> : null}
                    {node.lastEventAt ? <span>updated {formatTime(node.lastEventAt)}</span> : null}
                    <span>{node.eventCount} events</span>
                  </div>
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

function ActivityFeed({ events }) {
  return (
    <div className="grid gap-3">
      {events.length === 0 ? <div className="rounded-[1.6rem] border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-500">当前没有系统活动记录。</div> : null}
      {events.map((item) => (
        <details key={item.event_id} className="rounded-[1.6rem] border border-slate-200 bg-white px-4 py-4 shadow-sm">
          <summary className="cursor-pointer list-none">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-sm font-medium text-slate-900">{compactText(eventSummary(item), 100)}</div>
                <div className="mt-1 text-xs text-slate-500">{item.type}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-xs text-slate-400">
                <span>{formatTime(item.created_at)}</span>
                <ChevronRight size={14} />
              </div>
            </div>
          </summary>
          <pre className="mt-4 overflow-x-auto whitespace-pre-wrap rounded-[1.4rem] bg-slate-50 p-3 text-xs text-slate-700">{JSON.stringify(item.data || {}, null, 2)}</pre>
        </details>
      ))}
    </div>
  );
}

function SessionSettingsPanel({ catalog, runtimeDraft, onRuntimeDraftChange }) {
  const profiles = Array.isArray(catalog?.profiles) ? catalog.profiles : [];
  return (
    <div className="grid gap-4">
      <section className="rounded-[1.8rem] border border-slate-200 bg-white p-4 shadow-sm">
        <div className="text-sm font-medium text-slate-900">当前发送覆盖</div>
        <div className="mt-4 grid gap-3">
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Profile</div>
            <Select value={runtimeDraft.profile} onChange={(event) => onRuntimeDraftChange((current) => ({ ...current, profile: event.target.value }))}>
              {(profiles.length ? profiles : [{ name: runtimeDraft.profile }]).map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
            </Select>
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Repository</div>
            <Input value={runtimeDraft.repoPath} onChange={(event) => onRuntimeDraftChange((current) => ({ ...current, repoPath: event.target.value }))} placeholder="仓库路径（可选）" />
          </div>
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Domain</div>
            <Input value={runtimeDraft.domain} onChange={(event) => onRuntimeDraftChange((current) => ({ ...current, domain: event.target.value }))} placeholder="目标域名（可选）" />
          </div>
        </div>
      </section>
      <Toggle checked={runtimeDraft.autoApprove} onChange={(checked) => onRuntimeDraftChange((current) => ({ ...current, autoApprove: checked }))} label="当前页面后续发送自动审批" description="只影响当前浏览器页面后续新发送的消息；不会自动处理已经出现的审批。若想对整个会话持久生效，请到“会话权限”里保存。" />
    </div>
  );
}

function InspectorBody(props) {
  const tabs = [{ id: "workflow", label: "Workflow" }, { id: "execution", label: "执行" }, { id: "activity", label: "活动" }, { id: "session", label: "会话" }];
  const { activityEvents, catalog, currentTab, currentTurn, cveQuery, cveResults, cveStatus, messages, onChangeTab, onClose, onRuntimeDraftChange, onSearchCve, onSelectNode, onSelectTurn, onSyncCve, planGraph, runtimeDraft, selectedGraphNode, selectedNodeId, session, setCveQuery, turns, workflowPreferences } = props;
  return (
    <div className="flex h-full flex-col bg-white">
      <div className="border-b border-slate-200 px-4 py-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-400">Inspector</div>
            <div className="mt-1 text-base font-semibold text-slate-900">{session?.title || "当前会话"}</div>
          </div>
          <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100"><X size={16} /></button>
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {tabs.map((tab) => <button key={tab.id} type="button" onClick={() => onChangeTab(tab.id)} className={`rounded-lg px-3 py-1.5 text-sm transition ${currentTab === tab.id ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`}>{tab.label}</button>)}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {currentTab === "workflow" ? (
          <div className="grid gap-4">
            <WorkflowView active graph={planGraph} events={activityEvents} preferences={workflowPreferences} selectedNodeId={selectedNodeId} onSelect={onSelectNode} />
            <section className="rounded-[1.8rem] border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">{selectedGraphNode?.title || "步骤详情"}</div>
                  <div className="mt-1 text-xs text-slate-500">{selectedGraphNode ? selectedGraphNode.kind : "选择一个 workflow 步骤查看详情"}</div>
                </div>
                {selectedGraphNode ? <StatusPill status={selectedGraphNode.status} /> : null}
              </div>
              {selectedGraphNode ? (
                <div className="mt-4 grid gap-4">
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded-[1.4rem] bg-slate-50 p-4 text-sm leading-7 text-slate-700">{selectedGraphNode.description || selectedGraphNode.summary}</pre>
                  {selectedGraphNode.block_reason ? <div className="rounded-[1.4rem] border border-orange-200 bg-orange-50 p-4 text-sm text-orange-900">{selectedGraphNode.block_reason}</div> : null}
                  <div className="rounded-[1.4rem] bg-slate-50 p-4">
                    <div className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">动作数据</div>
                    <pre className="mt-3 overflow-x-auto whitespace-pre-wrap text-xs text-slate-700">{JSON.stringify(selectedGraphNode.action_request || selectedGraphNode.metadata || {}, null, 2)}</pre>
                  </div>
                </div>
              ) : <div className="mt-4 text-sm text-slate-500">当前没有可查看的 workflow 详情。</div>}
            </section>
          </div>
        ) : null}
        {currentTab === "execution" ? <ExecutionPanel activityEvents={activityEvents} currentTurn={currentTurn} messages={messages} onSelectTurn={onSelectTurn} planGraph={planGraph} turns={turns} /> : null}
        {currentTab === "activity" ? <ActivityFeed events={activityEvents} /> : null}
        {currentTab === "session" ? <div className="grid gap-4"><SessionSettingsPanel catalog={catalog} runtimeDraft={runtimeDraft} onRuntimeDraftChange={onRuntimeDraftChange} /><KnowledgeBasePanel cveQuery={cveQuery} cveResults={cveResults} cveStatus={cveStatus} onSearchCve={onSearchCve} onSyncCve={onSyncCve} setCveQuery={setCveQuery} /></div> : null}
      </div>
    </div>
  );
}

export function InspectorDrawer(props) {
  if (!props.open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-40 flex bg-black/20">
      <button type="button" className="flex-1" aria-label="关闭检查面板" onClick={props.onClose} />
      <div className="h-full w-[min(100vw,440px)] border-l border-slate-200 bg-white shadow-xl">
        <InspectorBody {...props} />
      </div>
    </div>
  );
}

export function InspectorToggleButton({ open, onClick }) {
  return (
    <Button variant="ghost" size="sm" onClick={onClick}>
      <Workflow size={15} className="mr-2" />
      {open ? "收起检查" : "检查"}
    </Button>
  );
}
