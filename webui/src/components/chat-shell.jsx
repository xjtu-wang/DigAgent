import React, { useEffect, useMemo, useState } from "react";
import { Archive, ArrowUp, Settings2, ShieldCheck, SquarePen, XCircle } from "lucide-react";
import { compactText } from "../chat-utils";
import { collectComposerMentions, normalizeMentionAgents } from "../composer-utils";
import { countOverrides } from "../permissions-store";
import { ChatTimeline } from "./chat-timeline";
import { ComposerMentionInput } from "./composer-mention-input";
import { PermissionsPanel } from "./permissions-panel";
import { InspectorDrawer, InspectorToggleButton } from "./runtime-panels";
import { MobileSidebar, MobileSidebarButton, SessionSidebar } from "./session-sidebar";
import { StatusPill } from "./status-pill";
import { Badge, Button } from "./ui";

function ClampedText({ className = "", text }) {
  const value = text || "新聊天";
  return (
    <div
      className={`overflow-hidden text-ellipsis [overflow-wrap:anywhere] ${className}`}
      style={{ WebkitBoxOrient: "vertical", WebkitLineClamp: 1, display: "-webkit-box" }}
      title={value}
    >
      {value}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col items-center justify-center px-6 text-center">
      <h1 className="text-3xl font-semibold tracking-tight text-slate-900 sm:text-[2rem]">今天想让 DigAgent 帮你完成什么？</h1>
      <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-500">直接开始对话。执行卡片、审批和 workflow 会在主聊天流与右侧检查面板里同步更新。</p>
    </div>
  );
}

function HeaderActions({ canArchiveCurrentSession, canDeleteCurrentSession, onDeleteSession, onOpenPermissions, onOpenSettings, onStartFreshSession, onToggleArchive, permissionBadge, session }) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <Button variant="ghost" size="sm" onClick={onStartFreshSession}><SquarePen size={15} className="mr-2" />新聊天</Button>
      <Button variant="ghost" size="sm" onClick={onOpenPermissions} disabled={!session?.session_id}>
        <ShieldCheck size={15} className="mr-2" />
        会话权限
        {permissionBadge ? <Badge className="ml-2 bg-slate-900 text-[10px] text-white">{permissionBadge}</Badge> : null}
      </Button>
      <Button variant="ghost" size="sm" onClick={onOpenSettings}><Settings2 size={15} className="mr-2" />设置</Button>
      <Button variant="ghost" size="sm" onClick={onToggleArchive} disabled={!canArchiveCurrentSession}><Archive size={15} className="mr-2" />{session?.status === "archived" ? "恢复" : "归档"}</Button>
      <Button variant="ghost" size="sm" onClick={() => onDeleteSession(session?.session_id)} disabled={!canDeleteCurrentSession}>删除</Button>
    </div>
  );
}

function WorkspaceHeader({ activeTurn, canArchiveCurrentSession, canDeleteCurrentSession, currentTurn, inspectorOpen, onDeleteSession, onOpenPermissions, onOpenSettings, onOpenSidebar, onStartFreshSession, onToggleArchive, onToggleInspector, permissionBadge, session }) {
  const previewTurn = activeTurn || currentTurn;
  return (
    <header className="flex h-14 shrink-0 items-center border-b border-slate-200/70 bg-white px-3 md:px-4">
      <div className="flex w-full items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <MobileSidebarButton onClick={onOpenSidebar} />
          <div className="min-w-0">
            <ClampedText className="text-[15px] font-semibold text-slate-900" text={session?.title} />
            <div className="flex items-center gap-2 text-xs text-slate-500">
              <StatusPill status={session?.status || "idle"} />
              {previewTurn ? <ClampedText className="min-w-0" text={compactText(previewTurn.goal || previewTurn.user_task || previewTurn.task, 80)} /> : null}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <HeaderActions
            canArchiveCurrentSession={canArchiveCurrentSession}
            canDeleteCurrentSession={canDeleteCurrentSession}
            onDeleteSession={onDeleteSession}
            onOpenPermissions={onOpenPermissions}
            onOpenSettings={onOpenSettings}
            onStartFreshSession={onStartFreshSession}
            onToggleArchive={onToggleArchive}
            permissionBadge={permissionBadge}
            session={session}
          />
          <InspectorToggleButton open={inspectorOpen} onClick={onToggleInspector} />
        </div>
      </div>
    </header>
  );
}

function ComposerPanel({ activeTurn, agents, onCancelTurn, onDownloadReport, onSendMessage, permissionOverrides, runtimeDraft, session, settings, setTask, task }) {
  const mentionAgents = useMemo(() => normalizeMentionAgents(agents), [agents]);
  const chips = useMemo(() => {
    const entries = [runtimeDraft.profile];
    if (runtimeDraft.repoPath) entries.push(runtimeDraft.repoPath);
    if (runtimeDraft.domain) entries.push(runtimeDraft.domain);
    if (runtimeDraft.autoApprove) entries.push("页面自动审批");
    if (permissionOverrides?.auto_approve) entries.push("会话自动审批");
    return entries;
  }, [permissionOverrides?.auto_approve, runtimeDraft]);
  const submitPayload = useMemo(() => ({
    content: task.trim(),
    mentions: collectComposerMentions(task, mentionAgents).filter((item) => item.configured).map((item) => item.name),
  }), [mentionAgents, task]);

  return (
    <div className="border-t border-slate-200/70 bg-white px-3 pb-4 pt-3 md:px-4">
      <div className="mx-auto max-w-3xl">
        <div className="rounded-[1.75rem] border border-slate-200 bg-white shadow-[0_2px_10px_rgba(0,0,0,0.04)] transition focus-within:border-slate-300 focus-within:shadow-[0_4px_16px_rgba(0,0,0,0.06)]">
          <ComposerMentionInput
            agents={agents}
            enterToSend={settings.chatPreferences.enterToSend}
            onSubmit={(payload) => void onSendMessage(payload)}
            placeholder="向 DigAgent 发送消息，输入 @agent 可自动补全"
            setValue={setTask}
            value={task}
          />
          <div className="flex flex-wrap items-center justify-between gap-2 px-3 pb-3">
            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              {chips.map((chip) => <Badge key={chip} className="bg-slate-100 text-[11px] text-slate-600">{chip}</Badge>)}
            </div>
            <div className="flex items-center gap-2">
              {activeTurn ? <Button variant="ghost" size="sm" onClick={onCancelTurn}><XCircle size={14} className="mr-1.5" />取消</Button> : null}
              {session?.latest_report_id ? (
                <>
                  <Button variant="ghost" size="sm" onClick={() => onDownloadReport(session.latest_report_id, "markdown")}>Markdown</Button>
                  <Button variant="ghost" size="sm" onClick={() => onDownloadReport(session.latest_report_id, "pdf")}>PDF</Button>
                </>
              ) : null}
              <Button size="sm" className="h-9 w-9 rounded-full p-0" onClick={() => void onSendMessage(submitPayload)} disabled={!submitPayload.content}>
                <ArrowUp size={16} />
              </Button>
            </div>
          </div>
        </div>
        <div className="mt-2 text-center text-[11px] text-slate-400">{settings.chatPreferences.enterToSend ? "Enter 发送 · Shift+Enter 换行" : "Enter 换行 · Shift+Enter 换行"}</div>
      </div>
    </div>
  );
}

export function WorkspacePage({ catalog, controller, onOpenSettings, settings }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(settings.layoutPreferences.sidebarCollapsed);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [inspectorTab, setInspectorTab] = useState(settings.layoutPreferences.inspectorDefaultTab);
  const [permissionsOpen, setPermissionsOpen] = useState(false);
  const permissionCount = useMemo(() => countOverrides(controller.permissionOverrides), [controller.permissionOverrides]);

  useEffect(() => {
    setSidebarCollapsed(settings.layoutPreferences.sidebarCollapsed);
    setInspectorTab(settings.layoutPreferences.inspectorDefaultTab);
  }, [settings.layoutPreferences.inspectorDefaultTab, settings.layoutPreferences.sidebarCollapsed]);

  useEffect(() => {
    if (controller.running && settings.layoutPreferences.openInspectorOnTurn) {
      setInspectorOpen(true);
    }
  }, [controller.running, settings.layoutPreferences.openInspectorOnTurn]);

  return (
    <div className="flex h-screen overflow-hidden bg-white text-slate-900">
      <div className="hidden h-full lg:block">
        <SessionSidebar activeSessionId={controller.session?.session_id} collapsed={sidebarCollapsed} groups={controller.sessionGroups} onDelete={controller.deleteSessionById} onNewChat={controller.startFreshSession} onOpenSettings={onOpenSettings} onSearchChange={controller.setSessionSearch} onSelect={(sessionId) => void controller.hydrateSession(sessionId)} onToggleCollapsed={() => setSidebarCollapsed((value) => !value)} sessionSearch={controller.sessionSearch} />
      </div>

      <MobileSidebar open={sidebarOpen} activeSessionId={controller.session?.session_id} groups={controller.sessionGroups} onClose={() => setSidebarOpen(false)} onDelete={controller.deleteSessionById} onNewChat={() => { controller.startFreshSession(); setSidebarOpen(false); }} onOpenSettings={() => { setSidebarOpen(false); onOpenSettings(); }} onSearchChange={controller.setSessionSearch} onSelect={(sessionId) => { setSidebarOpen(false); void controller.hydrateSession(sessionId); }} onToggleCollapsed={() => {}} sessionSearch={controller.sessionSearch} />

      <div className="flex min-w-0 flex-1 overflow-hidden">
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <WorkspaceHeader activeTurn={controller.activeTurn} canArchiveCurrentSession={controller.canArchiveCurrentSession} canDeleteCurrentSession={controller.canDeleteCurrentSession} currentTurn={controller.currentTurn} inspectorOpen={inspectorOpen} onDeleteSession={controller.deleteSessionById} onOpenPermissions={() => setPermissionsOpen(true)} onOpenSettings={onOpenSettings} onOpenSidebar={() => setSidebarOpen(true)} onStartFreshSession={controller.startFreshSession} onToggleArchive={() => void controller.toggleArchive()} onToggleInspector={() => setInspectorOpen((value) => !value)} permissionBadge={permissionCount > 0 ? permissionCount : null} session={controller.session} />

          <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-white">
            <div className="flex-1 overflow-x-hidden overflow-y-auto px-4 py-6 md:px-6">
              {controller.primaryTimeline.length === 0 && controller.pendingApprovals.length === 0 ? (
                <EmptyState />
              ) : (
                <ChatTimeline
                  density={settings.chatPreferences.timelineDensity}
                  evidenceState={controller.evidenceState}
                  expandedItems={controller.expandedItems}
                  onDownloadReport={controller.downloadReport}
                  onResolveApproval={controller.resolveApproval}
                  onToggleEvidence={controller.toggleEvidence}
                  onToggleItem={controller.toggleItem}
                  onToggleReport={controller.toggleReport}
                  pendingApprovals={controller.pendingApprovals}
                  reportOpenIds={controller.openReportIds}
                  reportsById={controller.reportsById}
                  resolvedApprovalIds={controller.resolvedApprovalIds}
                  resolvingApprovalIds={controller.resolvingApprovalIds}
                  running={controller.running}
                  supersededApprovalIds={controller.supersededApprovalIds}
                  supersededApprovals={controller.supersededApprovals}
                  timeline={controller.primaryTimeline}
                />
              )}
            </div>

            <ComposerPanel activeTurn={controller.activeTurn} agents={catalog?.profiles || []} onCancelTurn={() => void controller.cancelCurrentTurn()} onDownloadReport={controller.downloadReport} onSendMessage={controller.sendMessage} permissionOverrides={controller.permissionOverrides} runtimeDraft={controller.runtimeDraft} session={controller.session} settings={settings} setTask={controller.setTask} task={controller.task} />
          </main>
        </div>

        <PermissionsPanel catalog={catalog} controller={controller} onClose={() => setPermissionsOpen(false)} open={permissionsOpen} />

        <InspectorDrawer open={inspectorOpen} activityEvents={controller.activityEvents} catalog={catalog} currentTab={inspectorTab} currentTurn={controller.currentTurn} messages={controller.messages} onChangeTab={setInspectorTab} onClose={() => setInspectorOpen(false)} onRuntimeDraftChange={controller.setRuntimeDraft} onSelectNode={controller.setSelectedNodeId} onSelectTurn={controller.selectTurn} planGraph={controller.planGraph} runtimeDraft={controller.runtimeDraft} selectedGraphNode={controller.selectedGraphNode} selectedNodeId={controller.selectedNodeId} session={controller.session} turns={controller.turns} workflowPreferences={settings.workflowPreferences} />
      </div>
    </div>
  );
}
