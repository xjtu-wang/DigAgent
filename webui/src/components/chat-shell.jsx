import React, { useEffect, useMemo, useRef, useState } from "react";
import { Archive, ArrowUp, Paperclip, Settings2, ShieldCheck, SquarePen, X, XCircle } from "lucide-react";
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
import { composerPlaceholder, composerRuntimeChips, enterHintLabel } from "../ui-copy";

function ClampedText({ className = "", text }) {
  const value = text || "新对话";
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
    <div className="mx-auto flex h-full max-w-[48rem] flex-col items-center justify-center px-6 text-center">
      <div className="rounded-full bg-[color:var(--app-panel)] px-4 py-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--app-text-faint)] ring-1 ring-[color:var(--app-border)]">DigAgent</div>
      <h1 className="mt-6 max-w-3xl font-[var(--font-display)] text-[2.4rem] leading-tight text-[color:var(--app-text)] sm:text-[3rem]">先说清目标，再按需要查看执行过程。</h1>
      <p className="mt-4 max-w-2xl text-sm leading-8 text-[color:var(--app-text-soft)]">直接发送消息即可。工具调用、Agent 协作、确认请求、执行流程和结果报告都会继续保留，但只会在需要时展开显示。</p>
    </div>
  );
}

function ActionButton({ badge = null, children, disabled = false, onClick }) {
  return (
    <Button variant="ghost" size="sm" disabled={disabled} onClick={onClick} className="h-9 gap-2 px-3 text-[color:var(--app-text-soft)]">
      {children}
      {badge ? <Badge className="bg-[color:var(--app-text)] text-[10px] text-white">{badge}</Badge> : null}
    </Button>
  );
}

function WorkspaceHeader({ activeTurn, canArchiveCurrentSession, canDeleteCurrentSession, currentTurn, inspectorOpen, onDeleteSession, onOpenPermissions, onOpenSettings, onOpenSidebar, onStartFreshSession, onToggleArchive, onToggleInspector, permissionBadge, session }) {
  const previewTurn = activeTurn || currentTurn;
  return (
    <header className="border-b border-[color:var(--app-border)] bg-[color:var(--app-panel)]/90 px-3 py-3 md:px-5">
      <div className="flex items-start justify-between gap-4">
        <div className="flex min-w-0 items-start gap-3">
          <MobileSidebarButton onClick={onOpenSidebar} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <ClampedText className="text-[17px] font-semibold text-[color:var(--app-text)]" text={session?.title} />
              <StatusPill status={session?.status || "idle"} />
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px] text-[color:var(--app-text-faint)]">
              {previewTurn ? <ClampedText className="max-w-[32rem]" text={compactText(previewTurn.goal || previewTurn.user_task || previewTurn.task, 110)} /> : <span>当前会话还没有执行记录。</span>}
            </div>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
          <ActionButton onClick={onStartFreshSession}><SquarePen size={15} />新对话</ActionButton>
          <ActionButton badge={permissionBadge} disabled={!session?.session_id} onClick={onOpenPermissions}><ShieldCheck size={15} />会话权限</ActionButton>
          <ActionButton onClick={onOpenSettings}><Settings2 size={15} />设置</ActionButton>
          <ActionButton disabled={!canArchiveCurrentSession} onClick={onToggleArchive}><Archive size={15} />{session?.status === "archived" ? "恢复" : "归档"}</ActionButton>
          <Button variant="ghost" size="sm" disabled={!canDeleteCurrentSession} onClick={() => onDeleteSession(session?.session_id)} className="h-9 px-3 text-[color:var(--app-text-faint)]">删除</Button>
          <InspectorToggleButton open={inspectorOpen} onClick={onToggleInspector} />
        </div>
      </div>
    </header>
  );
}

function ComposerPanel({ activeTurn, agents, attachmentDrafts, onCancelTurn, onDownloadReport, onRemoveAttachment, onSendMessage, onUploadAttachments, permissionOverrides, runtimeDraft, session, settings, setTask, task }) {
  const mentionAgents = useMemo(() => normalizeMentionAgents(agents), [agents]);
  const chips = useMemo(
    () => composerRuntimeChips(runtimeDraft, permissionOverrides),
    [permissionOverrides, runtimeDraft],
  );
  const submitPayload = useMemo(() => ({
    content: task.trim(),
    mentions: collectComposerMentions(task, mentionAgents).filter((item) => item.configured).map((item) => item.name),
  }), [mentionAgents, task]);

  return (
    <div className="border-t border-[color:var(--app-border)] bg-[color:var(--app-panel)] px-3 pb-4 pt-3 md:px-5">
      <div className="mx-auto max-w-[52rem]">
        <div className="rounded-[2rem] border border-[color:var(--app-border)] bg-[color:var(--app-panel)] shadow-[var(--app-shadow)]">
          <ComposerMentionInput
            agents={agents}
            enterToSend={settings.chatPreferences.enterToSend}
            onSubmit={(payload) => void onSendMessage(payload)}
            placeholder={composerPlaceholder()}
            setValue={setTask}
            value={task}
          />
          {attachmentDrafts.length ? (
            <div className="flex flex-wrap gap-2 px-4 pb-3">
              {attachmentDrafts.map((item) => (
                <Badge key={item.artifact_id} className="gap-1.5 bg-emerald-50 text-emerald-800">
                  <Paperclip size={12} />
                  <span className="max-w-[14rem] truncate">{item.filename || item.artifact_id}</span>
                  <button type="button" className="rounded-full p-0.5 hover:bg-emerald-100" onClick={() => onRemoveAttachment(item.artifact_id)} aria-label="移除附件">
                    <X size={12} />
                  </button>
                </Badge>
              ))}
            </div>
          ) : null}
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 pb-4">
            <div className="flex min-w-0 flex-wrap gap-2">
              {chips.map((chip) => <Badge key={chip}>{chip}</Badge>)}
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <label className="inline-flex h-9 cursor-pointer items-center justify-center rounded-full px-3 text-sm text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel-muted)]">
                <Paperclip size={15} className="mr-1.5" />附件
                <input type="file" multiple className="sr-only" onChange={(event) => { void onUploadAttachments(event.target.files); event.target.value = ""; }} />
              </label>
              {activeTurn ? <Button variant="ghost" size="sm" onClick={onCancelTurn}><XCircle size={14} className="mr-1.5" />取消</Button> : null}
              {session?.latest_report_id ? (
                <>
                  <Button variant="secondary" size="sm" onClick={() => onDownloadReport(session.latest_report_id, "markdown")}>Markdown</Button>
                  <Button variant="secondary" size="sm" onClick={() => onDownloadReport(session.latest_report_id, "pdf")}>PDF</Button>
                </>
              ) : null}
              <Button size="sm" className="h-10 w-10 rounded-full p-0" onClick={() => void onSendMessage(submitPayload)} disabled={!submitPayload.content}>
                <ArrowUp size={16} />
              </Button>
            </div>
          </div>
        </div>
        <div className="mt-2 text-center text-[11px] text-[color:var(--app-text-faint)]">{enterHintLabel(settings.chatPreferences.enterToSend)}</div>
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
  const autoOpenStateRef = useRef({ ready: false, runningTurnId: null, sessionId: null });

  useEffect(() => {
    setSidebarCollapsed(settings.layoutPreferences.sidebarCollapsed);
    setInspectorTab(settings.layoutPreferences.inspectorDefaultTab);
  }, [settings.layoutPreferences.inspectorDefaultTab, settings.layoutPreferences.sidebarCollapsed]);

  useEffect(() => {
    const sessionId = controller.session?.session_id || null;
    const runningTurnId = controller.running ? controller.activeTurn?.turn_id || null : null;
    const previousState = autoOpenStateRef.current;
    const shouldAutoOpen = previousState.ready
      && settings.layoutPreferences.openInspectorOnTurn
      && sessionId
      && sessionId === previousState.sessionId
      && runningTurnId
      && runningTurnId !== previousState.runningTurnId
      && controller.turns.length > 1;
    if (shouldAutoOpen) {
      setInspectorOpen(true);
    }
    autoOpenStateRef.current = { ready: true, runningTurnId, sessionId };
  }, [controller.activeTurn?.turn_id, controller.running, controller.session?.session_id, controller.turns.length, settings.layoutPreferences.openInspectorOnTurn]);

  useEffect(() => {
    controller.setInspectorDemanded(inspectorOpen);
  }, [controller, inspectorOpen]);

  return (
    <div className="flex h-screen overflow-hidden bg-[color:var(--app-canvas)] text-[color:var(--app-text)]">
      <div className="hidden h-full lg:block">
        <SessionSidebar activeSessionId={controller.session?.session_id} collapsed={sidebarCollapsed} groups={controller.sessionGroups} onDelete={controller.deleteSessionById} onNewChat={() => { setInspectorOpen(false); controller.startFreshSession(); }} onOpenSettings={onOpenSettings} onSearchChange={controller.setSessionSearch} onSelect={(sessionId) => void controller.hydrateSession(sessionId)} onToggleCollapsed={() => setSidebarCollapsed((value) => !value)} sessionSearch={controller.sessionSearch} />
      </div>

      <MobileSidebar open={sidebarOpen} activeSessionId={controller.session?.session_id} groups={controller.sessionGroups} onClose={() => setSidebarOpen(false)} onDelete={controller.deleteSessionById} onNewChat={() => { setInspectorOpen(false); controller.startFreshSession(); setSidebarOpen(false); }} onOpenSettings={() => { setSidebarOpen(false); onOpenSettings(); }} onSearchChange={controller.setSessionSearch} onSelect={(sessionId) => { setSidebarOpen(false); void controller.hydrateSession(sessionId); }} onToggleCollapsed={() => {}} sessionSearch={controller.sessionSearch} />

      <div className="flex min-w-0 flex-1 overflow-hidden">
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <WorkspaceHeader activeTurn={controller.activeTurn} canArchiveCurrentSession={controller.canArchiveCurrentSession} canDeleteCurrentSession={controller.canDeleteCurrentSession} currentTurn={controller.currentTurn} inspectorOpen={inspectorOpen} onDeleteSession={controller.deleteSessionById} onOpenPermissions={() => setPermissionsOpen(true)} onOpenSettings={onOpenSettings} onOpenSidebar={() => setSidebarOpen(true)} onStartFreshSession={() => { setInspectorOpen(false); controller.startFreshSession(); }} onToggleArchive={() => void controller.toggleArchive()} onToggleInspector={() => setInspectorOpen((value) => !value)} permissionBadge={permissionCount > 0 ? permissionCount : null} session={controller.session} />

          <main className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
            <div className="flex-1 overflow-x-hidden overflow-y-auto px-3 py-5 md:px-6 md:py-6">
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

            <ComposerPanel activeTurn={controller.activeTurn} agents={catalog?.profiles || []} attachmentDrafts={controller.attachmentDrafts} onCancelTurn={() => void controller.cancelCurrentTurn()} onDownloadReport={controller.downloadReport} onRemoveAttachment={controller.removeAttachmentDraft} onSendMessage={controller.sendMessage} onUploadAttachments={controller.uploadAttachments} permissionOverrides={controller.permissionOverrides} runtimeDraft={controller.runtimeDraft} session={controller.session} settings={settings} setTask={controller.setTask} task={controller.task} />
          </main>
        </div>

        <PermissionsPanel catalog={catalog} controller={controller} onClose={() => setPermissionsOpen(false)} open={permissionsOpen} />

        <InspectorDrawer open={inspectorOpen} activityEvents={controller.activityEvents} catalog={catalog} currentTab={inspectorTab} currentTurn={controller.currentTurn} messages={controller.messages} onChangeTab={setInspectorTab} onClose={() => setInspectorOpen(false)} onRuntimeDraftChange={controller.setRuntimeDraft} onSelectNode={controller.setSelectedNodeId} onSelectTurn={controller.selectTurn} planGraph={controller.planGraph} runtimeDraft={controller.runtimeDraft} selectedGraphNode={controller.selectedGraphNode} selectedNodeId={controller.selectedNodeId} session={controller.session} turns={controller.turns} workflowPreferences={settings.workflowPreferences} />
      </div>
    </div>
  );
}
