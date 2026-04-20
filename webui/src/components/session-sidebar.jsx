import React from "react";
import { Menu, MessageSquarePlus, Search, Settings2, Trash2, X } from "lucide-react";

function ClampedText({ className = "", lines = 1, text }) {
  const value = text || "新对话";
  return (
    <div
      className={`overflow-hidden text-ellipsis [overflow-wrap:anywhere] ${className}`}
      style={{ WebkitBoxOrient: "vertical", WebkitLineClamp: lines, display: "-webkit-box" }}
      title={value}
    >
      {value}
    </div>
  );
}

function SessionListItem({ item, active, onDelete, onSelect }) {
  const deleteDisabled = Boolean(item.active_turn_id);
  return (
    <div className={`group relative rounded-[1.25rem] border transition ${active ? "border-[color:var(--app-border-strong)] bg-[color:var(--app-panel)] shadow-[var(--app-shadow-soft)]" : "border-transparent hover:border-[color:var(--app-border)] hover:bg-[color:var(--app-panel)]"}`}>
      <button type="button" onClick={() => onSelect(item.session_id)} className="flex w-full min-w-0 items-start gap-3 px-3 py-3 text-left">
        <div className={`mt-1 h-2.5 w-2.5 shrink-0 rounded-full ${active ? "bg-[color:var(--app-accent)]" : "bg-[color:var(--app-border-strong)]"}`} />
        <div className="min-w-0 flex-1">
          <ClampedText className="text-sm font-medium text-[color:var(--app-text)]" lines={2} text={item.title} />
          {item.last_message_preview ? <ClampedText className="mt-1 text-[12px] leading-5 text-[color:var(--app-text-faint)]" lines={2} text={item.last_message_preview} /> : null}
        </div>
      </button>
      <button
        type="button"
        disabled={deleteDisabled}
        onClick={(event) => {
          event.stopPropagation();
          onDelete(item.session_id);
        }}
        className={`absolute right-2 top-2 flex h-8 w-8 items-center justify-center rounded-full opacity-0 transition group-hover:opacity-100 ${deleteDisabled ? "cursor-not-allowed text-[color:var(--app-text-faint)]" : "text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel-muted)] hover:text-[color:var(--app-danger)]"}`}
        title={deleteDisabled ? "请先结束当前执行" : "删除会话"}
      >
        <Trash2 size={14} />
      </button>
    </div>
  );
}

function SidebarContent({
  collapsed,
  activeSessionId,
  groups,
  onClose,
  onDelete,
  onNewChat,
  onOpenSettings,
  onSearchChange,
  onSelect,
  onToggleCollapsed,
  sessionSearch,
}) {
  if (collapsed) {
    return (
      <div className="flex h-full w-[72px] flex-col items-center border-r border-[color:var(--app-border)] bg-[color:var(--app-panel-muted)] px-3 py-4">
        <button type="button" onClick={onToggleCollapsed} className="mb-3 flex h-10 w-10 items-center justify-center rounded-full text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel)]">
          <Menu size={18} />
        </button>
        <button type="button" onClick={onNewChat} className="flex h-10 w-10 items-center justify-center rounded-full bg-[color:var(--app-text)] text-white shadow-[var(--app-shadow-soft)]" title="新建对话">
          <MessageSquarePlus size={18} />
        </button>
        <button type="button" onClick={onOpenSettings} className="mt-auto flex h-10 w-10 items-center justify-center rounded-full text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel)]" title="设置">
          <Settings2 size={18} />
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col border-r border-[color:var(--app-border)] bg-[color:var(--app-panel-muted)] px-4 py-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--app-text-faint)]">DigAgent</div>
          <div className="mt-1 text-lg font-semibold text-[color:var(--app-text)]">聊天工作台</div>
        </div>
        <div className="flex items-center gap-1">
          {onClose ? (
            <button type="button" onClick={onClose} className="flex h-9 w-9 items-center justify-center rounded-full text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel)] lg:hidden">
              <X size={16} />
            </button>
          ) : null}
          <button type="button" onClick={onToggleCollapsed} className="flex h-9 w-9 items-center justify-center rounded-full text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel)]">
            <Menu size={16} />
          </button>
        </div>
      </div>

      <button type="button" onClick={onNewChat} className="mt-4 flex h-11 items-center justify-center gap-2 rounded-full bg-[color:var(--app-text)] px-4 text-sm font-medium text-white shadow-[var(--app-shadow-soft)]">
        <MessageSquarePlus size={16} />
        新对话
      </button>

      <div className="relative mt-4">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[color:var(--app-text-faint)]" />
        <input
          className="h-11 w-full rounded-full border border-[color:var(--app-border)] bg-[color:var(--app-panel)] pl-10 pr-4 text-sm text-[color:var(--app-text)] placeholder:text-[color:var(--app-text-faint)] focus:border-[color:var(--app-border-strong)] focus:outline-none"
          placeholder="搜索会话"
          value={sessionSearch}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </div>

      <div className="mt-4 flex-1 overflow-y-auto pr-1">
        {groups.length === 0 ? <div className="rounded-[1.4rem] border border-dashed border-[color:var(--app-border)] px-4 py-6 text-sm leading-7 text-[color:var(--app-text-faint)]">还没有会话，开始一个新对话即可。</div> : null}
        {groups.map((group) => (
          <section key={group.key} className="mb-5">
            <div className="px-2 pb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--app-text-faint)]">{group.title}</div>
            <div className="grid gap-2">
              {group.items.map((item) => (
                <SessionListItem key={item.session_id} item={item} active={item.session_id === activeSessionId} onDelete={onDelete} onSelect={onSelect} />
              ))}
            </div>
          </section>
        ))}
      </div>

      <button type="button" onClick={onOpenSettings} className="mt-3 flex h-11 items-center gap-2 rounded-full px-3 text-sm text-[color:var(--app-text-soft)] transition hover:bg-[color:var(--app-panel)] hover:text-[color:var(--app-text)]">
        <Settings2 size={16} />
        设置
      </button>
    </div>
  );
}

export function SessionSidebar(props) {
  return (
    <aside className={`hidden h-full shrink-0 lg:flex ${props.collapsed ? "w-[72px]" : "w-[280px]"}`}>
      <SidebarContent {...props} />
    </aside>
  );
}

export function MobileSidebar({ open, ...props }) {
  if (!open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-50 flex bg-black/22 lg:hidden">
      <div className="h-full w-[min(88vw,320px)]">
        <SidebarContent {...props} collapsed={false} />
      </div>
      <button type="button" aria-label="关闭侧栏" className="flex-1" onClick={props.onClose} />
    </div>
  );
}

export function MobileSidebarButton({ onClick }) {
  return (
    <button type="button" onClick={onClick} className="flex h-10 w-10 items-center justify-center rounded-full text-[color:var(--app-text-soft)] hover:bg-[color:var(--app-panel-muted)] lg:hidden">
      <Menu size={18} />
    </button>
  );
}
