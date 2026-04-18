import React, { useEffect, useRef, useState } from "react";
import { ArrowLeft, Download, RotateCcw, Save, Upload } from "lucide-react";
import { parseImportedSettings } from "../settings-store";
import { Badge, Button, Card, Input, Select, SectionLabel, Toggle } from "./ui";

function SettingsSection({ children, description, id, title }) {
  return (
    <section id={id} className="scroll-mt-8">
      <Card className="p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <SectionLabel>{title}</SectionLabel>
            <div className="mt-2 text-lg font-semibold text-slate-900">{description}</div>
          </div>
        </div>
        <div className="mt-6 grid gap-4">{children}</div>
      </Card>
    </section>
  );
}

function SummaryCard({ summary }) {
  if (!summary) {
    return (
      <Card className="p-6">
        <SectionLabel>Environment</SectionLabel>
        <div className="mt-3 text-sm text-slate-500">正在加载后端环境摘要。</div>
      </Card>
    );
  }

  return (
    <Card className="p-6">
      <SectionLabel>Backend Summary</SectionLabel>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <div className="rounded-[1.4rem] bg-slate-50 p-4">
          <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Model</div>
          <div className="mt-2 text-sm font-medium text-slate-900">{summary.model || "未配置"}</div>
        </div>
        <div className="rounded-[1.4rem] bg-slate-50 p-4">
          <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Base URL</div>
          <div className="mt-2 break-all text-sm font-medium text-slate-900">{summary.base_url || "未配置"}</div>
        </div>
        <div className="rounded-[1.4rem] bg-slate-50 p-4">
          <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Workspace</div>
          <div className="mt-2 break-all text-sm font-medium text-slate-900">{summary.workspace_root}</div>
        </div>
        <div className="rounded-[1.4rem] bg-slate-50 p-4">
          <div className="text-xs uppercase tracking-[0.18em] text-slate-400">Runtime</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge>{summary.can_use_model ? "model-ready" : "model-unavailable"}</Badge>
            <Badge>{summary.fake_model ? "fake-model" : "real-model"}</Badge>
            <Badge>{summary.has_nvd_api_key ? "nvd-ready" : "nvd-missing"}</Badge>
            <Badge>{summary.approval_timeout_sec}s approval</Badge>
          </div>
        </div>
      </div>
    </Card>
  );
}

function downloadSettingsJson(settings) {
  const blob = new Blob([JSON.stringify(settings, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "digagent-webui-settings.json";
  anchor.click();
  URL.revokeObjectURL(url);
}

export function SettingsPage({ catalog, onNavigateHome, onResetSettings, onSaveSettings, settings, settingsSummary }) {
  const [draft, setDraft] = useState(settings);
  const [statusMessage, setStatusMessage] = useState("");
  const fileInputRef = useRef(null);
  const profiles = Array.isArray(catalog?.profiles) ? catalog.profiles : [];

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  function updateSection(section, patch) {
    setDraft((current) => ({
      ...current,
      [section]: { ...current[section], ...patch },
    }));
  }

  async function handleImport(event) {
    const [file] = Array.from(event.target.files || []);
    if (!file) {
      return;
    }
    const text = await file.text();
    setDraft(parseImportedSettings(text));
    setStatusMessage("已导入本地 JSON，保存后生效。");
    event.target.value = "";
  }

  function handleSave() {
    onSaveSettings(draft);
    setStatusMessage("设置已保存到当前浏览器。");
  }

  function handleReset() {
    const next = onResetSettings();
    setDraft(next);
    setStatusMessage("已恢复默认设置。");
  }

  const sections = [
    { id: "runtime", label: "执行默认值" },
    { id: "chat", label: "输入与聊天" },
    { id: "layout", label: "布局与面板" },
    { id: "workflow", label: "Workflow" },
  ];

  return (
    <div className="min-h-screen bg-[linear-gradient(180deg,#f5f3ee_0%,#eff3f7_100%)] px-3 py-3 text-slate-900 md:px-5">
      <div className="mx-auto flex min-h-[calc(100vh-1.5rem)] max-w-[1680px] overflow-hidden rounded-[2.4rem] border border-white/60 bg-[#f8f7f4]/92 shadow-[0_28px_90px_rgba(15,23,42,0.1)] backdrop-blur">
        <aside className="hidden w-[280px] shrink-0 border-r border-slate-200 bg-[#111827] px-5 py-6 text-white lg:block">
          <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">DIGAGENT</div>
          <div className="mt-3 text-2xl font-semibold">Settings</div>
          <div className="mt-2 text-sm leading-7 text-slate-400">这些设置只保存在当前浏览器里，作为 WebUI 的全局默认值使用。</div>
          <div className="mt-8 grid gap-2">
            {sections.map((section) => (
              <a key={section.id} href={`#${section.id}`} className="rounded-2xl px-4 py-3 text-sm text-slate-300 transition hover:bg-white/8 hover:text-white">
                {section.label}
              </a>
            ))}
          </div>
        </aside>

        <div className="flex min-w-0 flex-1 flex-col">
          <header className="border-b border-slate-200 bg-white/92 px-4 py-4 backdrop-blur md:px-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">WebUI</div>
                <div className="mt-1 text-2xl font-semibold text-slate-900">高自定义设置</div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button variant="ghost" onClick={onNavigateHome}>
                  <ArrowLeft size={15} className="mr-2" />
                  返回聊天
                </Button>
                <Button variant="secondary" onClick={() => downloadSettingsJson(draft)}>
                  <Download size={15} className="mr-2" />
                  导出 JSON
                </Button>
                <Button variant="secondary" onClick={() => fileInputRef.current?.click()}>
                  <Upload size={15} className="mr-2" />
                  导入 JSON
                </Button>
                <Button variant="secondary" onClick={handleReset}>
                  <RotateCcw size={15} className="mr-2" />
                  恢复默认
                </Button>
                <Button onClick={handleSave}>
                  <Save size={15} className="mr-2" />
                  保存
                </Button>
              </div>
            </div>
            {statusMessage ? <div className="mt-3 text-sm text-slate-500">{statusMessage}</div> : null}
            <input ref={fileInputRef} type="file" accept="application/json" className="hidden" onChange={(event) => void handleImport(event)} />
          </header>

          <main className="min-h-0 flex-1 overflow-y-auto px-4 py-6 md:px-6">
            <div className="mx-auto grid max-w-6xl gap-6">
              <SummaryCard summary={settingsSummary} />

              <SettingsSection id="runtime" title="执行默认值" description="控制新消息和新会话默认使用的执行参数。">
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">默认 Profile</div>
                  <Select value={draft.runtimeDefaults.profile} onChange={(event) => updateSection("runtimeDefaults", { profile: event.target.value })}>
                    {(profiles.length ? profiles : [{ name: draft.runtimeDefaults.profile }]).map((item) => (
                      <option key={item.name} value={item.name}>
                        {item.name}
                      </option>
                    ))}
                  </Select>
                </div>
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">默认仓库路径</div>
                    <Input value={draft.runtimeDefaults.repoPath} onChange={(event) => updateSection("runtimeDefaults", { repoPath: event.target.value })} placeholder="例如 /mnt/d/CodeLab/DigAgent" />
                  </div>
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">默认域名</div>
                    <Input value={draft.runtimeDefaults.domain} onChange={(event) => updateSection("runtimeDefaults", { domain: event.target.value })} placeholder="例如 example.com" />
                  </div>
                </div>
                <Toggle
                  checked={draft.runtimeDefaults.autoApprove}
                  onChange={(checked) => updateSection("runtimeDefaults", { autoApprove: checked })}
                  label="默认自动审批"
                  description="保存后作为浏览器默认值，对之后新发送的消息生效；不会自动处理当前已经弹出的审批请求。"
                />
              </SettingsSection>

              <SettingsSection id="chat" title="输入与聊天" description="调整主聊天区的输入和时间线行为。">
                <Toggle
                  checked={draft.chatPreferences.enterToSend}
                  onChange={(checked) => updateSection("chatPreferences", { enterToSend: checked })}
                  label="Enter 发送"
                  description="打开后使用 Enter 发送消息，Shift+Enter 换行。关闭后 Enter 只换行。"
                />
                <Toggle
                  checked={draft.chatPreferences.showKeySystemCards}
                  onChange={(checked) => updateSection("chatPreferences", { showKeySystemCards: checked })}
                  label="主时间线显示关键系统卡片"
                  description="审批、等待输入、失败、报告等关键事件会显示在聊天主线里。"
                />
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">时间线密度</div>
                  <Select value={draft.chatPreferences.timelineDensity} onChange={(event) => updateSection("chatPreferences", { timelineDensity: event.target.value })}>
                    <option value="comfortable">comfortable</option>
                    <option value="compact">compact</option>
                  </Select>
                </div>
              </SettingsSection>

              <SettingsSection id="layout" title="布局与面板" description="控制侧栏、检查抽屉和默认观察方式。">
                <Toggle
                  checked={draft.layoutPreferences.sidebarCollapsed}
                  onChange={(checked) => updateSection("layoutPreferences", { sidebarCollapsed: checked })}
                  label="默认折叠左侧栏"
                  description="桌面端初始进入聊天页时，左侧会话栏将以紧凑模式打开。"
                />
                <Toggle
                  checked={draft.layoutPreferences.openInspectorOnTurn}
                  onChange={(checked) => updateSection("layoutPreferences", { openInspectorOnTurn: checked })}
                  label="执行时自动展开检查面板"
                  description="当新的 turn 开始执行时，自动打开右侧检查抽屉。"
                />
                <div>
                  <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">检查面板默认标签</div>
                  <Select value={draft.layoutPreferences.inspectorDefaultTab} onChange={(event) => updateSection("layoutPreferences", { inspectorDefaultTab: event.target.value })}>
                    <option value="workflow">workflow</option>
                    <option value="execution">execution</option>
                    <option value="activity">activity</option>
                    <option value="session">session</option>
                  </Select>
                </div>
              </SettingsSection>

              <SettingsSection id="workflow" title="Workflow" description="调整 workflow 检查面板的聚焦和元数据显示方式。">
                <Toggle
                  checked={draft.workflowPreferences.focusActiveOnOpen}
                  onChange={(checked) => updateSection("workflowPreferences", { focusActiveOnOpen: checked })}
                  label="打开时聚焦当前活跃步骤"
                  description="首次展开 workflow 标签时，自动滚动到当前活跃或选中的步骤。"
                />
                <Toggle
                  checked={draft.workflowPreferences.focusActiveOnUpdate}
                  onChange={(checked) => updateSection("workflowPreferences", { focusActiveOnUpdate: checked })}
                  label="更新时跟随活跃步骤"
                  description="workflow 收到新节点状态后自动滚动到最新活跃步骤。"
                />
                <Toggle
                  checked={draft.workflowPreferences.showEventMetadata}
                  onChange={(checked) => updateSection("workflowPreferences", { showEventMetadata: checked })}
                  label="显示事件摘要"
                  description="在 workflow 步骤卡片上显示最近一次关键系统事件摘要。"
                />
              </SettingsSection>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
