import React, { useMemo } from "react";
import { ShieldCheck, X } from "lucide-react";
import { cn } from "../lib";
import {
  DEFAULT_RISK_TAGS,
  countOverrides,
  isOverridesEmpty,
  setAutoApprove,
  setBudget,
  setRule,
} from "../permissions-store";
import { notInProfileLabel, permissionRuleLabel, profileSummaryLabel } from "../ui-copy";
import { Badge, Button, Input, SectionLabel, Toggle } from "./ui";

const TOOL_RULES = [
  { value: "inherit", label: permissionRuleLabel("inherit") },
  { value: "allow", label: permissionRuleLabel("allow") },
  { value: "confirm", label: permissionRuleLabel("confirm") },
  { value: "deny", label: permissionRuleLabel("deny") },
];

const MCP_RULES = [
  { value: "inherit", label: permissionRuleLabel("inherit") },
  { value: "allow", label: permissionRuleLabel("allow") },
  { value: "deny", label: permissionRuleLabel("deny") },
];

function RuleRow({ label, description, badge, rule, onChange, options }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-medium text-slate-900">
            <span className="truncate">{label}</span>
            {badge}
          </div>
          {description ? <div className="mt-1 text-xs leading-5 text-slate-500">{description}</div> : null}
        </div>
        <div className="flex shrink-0 rounded-full bg-slate-100 p-0.5 text-xs">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              onClick={() => onChange(option.value)}
              className={cn(
                "rounded-full px-3 py-1.5 font-medium transition",
                rule === option.value ? "bg-slate-900 text-white" : "text-slate-500 hover:text-slate-900",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function activeProfileName(catalog, controller) {
  return controller?.runtimeDraft?.profile || controller?.session?.root_agent_profile || catalog?.profiles?.[0]?.name;
}

function useToolCatalog(catalog, profile) {
  return useMemo(() => {
    const seen = new Map();
    const addEntry = (entry) => {
      if (!entry?.name || seen.has(entry.name)) return;
      seen.set(entry.name, entry);
    };
    (catalog?.tools || []).forEach((tool) => {
      addEntry({
        name: tool.name,
        description: tool.description,
        risk_tags: tool.risk_tags || [],
        origin: "tool",
      });
    });
    ["delegate_subagent", "skill_consult", "report_export"].forEach((name) => {
      addEntry({ name, description: "系统操作", risk_tags: [], origin: "system" });
    });
    const allowset = new Set(profile?.tool_allowlist || []);
    return Array.from(seen.values())
      .map((entry) => ({ ...entry, in_profile: allowset.has(entry.name) }))
      .sort((a, b) => Number(b.in_profile) - Number(a.in_profile) || a.name.localeCompare(b.name));
  }, [catalog, profile]);
}

export function PermissionsPanel({ catalog, controller, onClose, open }) {
  const overrides = controller.permissionOverrides;
  const profileName = activeProfileName(catalog, controller);
  const profile = useMemo(
    () => (catalog?.profiles || []).find((item) => item.name === profileName),
    [catalog, profileName],
  );
  const tools = useToolCatalog(catalog, profile);
  const mcpServers = catalog?.mcp_servers || [];
  const overrideCount = countOverrides(overrides);
  const sessionTitle = controller.session?.title || "当前会话";
  const hasSession = Boolean(controller.session?.session_id);

  function updateOverrides(next) {
    controller.setPermissionOverrides(next);
  }

  async function handleSave() {
    if (!hasSession) return;
    await controller.savePermissionOverrides({ replace: overrides });
  }

  async function handleReset() {
    if (!hasSession) return;
    await controller.savePermissionOverrides({ clear: true });
  }

  function handleExport() {
    const blob = new Blob([JSON.stringify(overrides, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "digagent-session-permissions.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function handleImport(event) {
    const [file] = Array.from(event.target.files || []);
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      updateOverrides(parsed);
    } catch {
      window.alert("无效的 JSON 文件");
    }
  }

  return (
    <aside
      className={cn(
        "fixed inset-y-0 right-0 z-40 flex w-full max-w-[480px] transform flex-col border-l border-slate-200 bg-[#f8f7f4] shadow-[0_28px_90px_rgba(15,23,42,0.12)] transition-transform duration-200 ease-out",
        open ? "translate-x-0" : "translate-x-full",
      )}
      aria-hidden={!open}
    >
      <header className="flex items-start justify-between gap-3 border-b border-slate-200 bg-white px-5 py-4">
        <div>
          <SectionLabel>会话权限</SectionLabel>
          <div className="mt-1 flex items-center gap-2 text-base font-semibold text-slate-900">
            <ShieldCheck size={16} className="text-slate-500" />
            <span className="truncate">{sessionTitle}</span>
          </div>
          <div className="mt-1 text-xs text-slate-500">
            {hasSession
              ? profileSummaryLabel(profileName, overrideCount)
              : "先打开或创建一个会话再配置权限。"}
          </div>
        </div>
        <button type="button" onClick={onClose} className="rounded-full p-1 text-slate-500 hover:bg-slate-100">
          <X size={16} />
        </button>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-5 py-3">
        <Button size="sm" onClick={() => void handleSave()} disabled={!hasSession}>
          保存到会话
        </Button>
        <Button size="sm" variant="secondary" onClick={() => void handleReset()} disabled={!hasSession || isOverridesEmpty(overrides)}>
          全部重置
        </Button>
        <Button size="sm" variant="ghost" onClick={handleExport}>
          导出 JSON
        </Button>
        <label className="cursor-pointer">
          <span className="inline-flex h-9 items-center rounded-2xl px-3 text-xs font-medium text-slate-600 hover:bg-slate-100">
            导入 JSON
          </span>
          <input type="file" accept="application/json" className="hidden" onChange={(event) => void handleImport(event)} />
        </label>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <section>
          <SectionLabel>总体</SectionLabel>
          <div className="mt-2 space-y-3">
            <Toggle
              checked={overrides.auto_approve}
              onChange={(value) => updateOverrides(setAutoApprove(overrides, value))}
              label="自动确认审批"
              description="开启后，本会话后续需要确认的操作会自动通过。修改后需要点击上方“保存到会话”才会真正生效。"
            />
            <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="text-sm font-medium text-slate-900">预算覆盖</div>
                  <div className="mt-1 text-xs text-slate-500">留空则沿用当前执行配置。超过上限的操作会被直接拒绝。</div>
                </div>
                {overrides.budget_override ? (
                  <Button size="sm" variant="ghost" onClick={() => updateOverrides(setBudget(overrides, null))}>
                    清除
                  </Button>
                ) : null}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <label className="text-xs text-slate-500">
                  <div className="mb-1">最多工具调用次数</div>
                  <Input
                    type="number"
                    min={0}
                    placeholder={profile?.runtime_budget?.max_tool_calls ?? ""}
                    value={overrides.budget_override?.max_tool_calls ?? ""}
                    onChange={(event) =>
                      updateOverrides(
                        setBudget(overrides, {
                          ...(overrides.budget_override || {}),
                          max_tool_calls: event.target.value,
                        }),
                      )
                    }
                  />
                </label>
                <label className="text-xs text-slate-500">
                  <div className="mb-1">最长运行时间（秒）</div>
                  <Input
                    type="number"
                    min={0}
                    placeholder={profile?.runtime_budget?.max_runtime_seconds ?? ""}
                    value={overrides.budget_override?.max_runtime_seconds ?? ""}
                    onChange={(event) =>
                      updateOverrides(
                        setBudget(overrides, {
                          ...(overrides.budget_override || {}),
                          max_runtime_seconds: event.target.value,
                        }),
                      )
                    }
                  />
                </label>
              </div>
            </div>
          </div>
        </section>

        <section>
          <div className="flex items-center justify-between">
            <SectionLabel>风险标签</SectionLabel>
            <div className="text-xs text-slate-400">命中多条时以最严格规则为准</div>
          </div>
          <div className="mt-2 space-y-2">
            {DEFAULT_RISK_TAGS.map((tag) => (
              <RuleRow
                key={tag}
                label={tag}
                description="影响所有带有该标签的工具或动作。"
                rule={overrides.risk_tag_rules[tag] || "inherit"}
                onChange={(value) => updateOverrides(setRule(overrides, "risk_tag_rules", tag, value))}
                options={TOOL_RULES}
              />
            ))}
          </div>
        </section>

        <section>
          <SectionLabel>MCP 服务器</SectionLabel>
          <div className="mt-2 space-y-2">
            {mcpServers.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-3 text-xs text-slate-400">
                当前环境没有注册 MCP 服务器。
              </div>
            ) : null}
            {mcpServers.map((server) => (
              <RuleRow
                key={server.server_id}
                label={server.name || server.server_id}
                description={server.description || server.server_id}
                rule={overrides.mcp_server_rules[server.server_id] || "inherit"}
                onChange={(value) => updateOverrides(setRule(overrides, "mcp_server_rules", server.server_id, value))}
                options={MCP_RULES}
                badge={profile && !profile.mcp_server_allowlist?.includes(server.server_id) ? (
                  <Badge className="bg-amber-100 text-[10px] text-amber-700">{notInProfileLabel()}</Badge>
                ) : null}
              />
            ))}
          </div>
        </section>

        <section>
          <div className="flex items-center justify-between">
            <SectionLabel>工具</SectionLabel>
            <div className="text-xs text-slate-400">覆盖执行配置中的默认允许列表</div>
          </div>
          <div className="mt-2 space-y-2">
            {tools.map((tool) => (
              <RuleRow
                key={tool.name}
                label={tool.name}
                description={tool.description}
                rule={overrides.tool_rules[tool.name] || "inherit"}
                onChange={(value) => updateOverrides(setRule(overrides, "tool_rules", tool.name, value))}
                options={TOOL_RULES}
                badge={
                  <>
                    {tool.risk_tags?.length
                      ? tool.risk_tags.map((tag) => (
                          <Badge key={tag} className="bg-rose-50 text-[10px] text-rose-600">{tag}</Badge>
                        ))
                      : null}
                    {!tool.in_profile ? (
                      <Badge className="bg-amber-100 text-[10px] text-amber-700">{notInProfileLabel()}</Badge>
                    ) : null}
                  </>
                }
              />
            ))}
          </div>
        </section>
      </div>
    </aside>
  );
}
