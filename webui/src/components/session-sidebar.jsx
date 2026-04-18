import React from "react";
import { Menu, MessageSquarePlus, Search, Settings2, Trash2, X } from "lucide-react";

function SessionListItem({ item, active, onDelete, onSelect }) {
  const deleteDisabled = Boolean(item.active_turn_id);

  return (
    <div className={`group relative flex items-center rounded-lg transition ${active ? "bg-slate-200/70" : "hover:bg-slate-200/50"}`}>
      <button type="button" onClick={() => onSelect(item.session_id)} className="min-w-0 flex-1 px-3 py-2 text-left">
        <div className="truncate text-sm text-slate-800">{item.title || "新聊天"}</div>
      </button>
      <button
        type="button"
        disabled={deleteDisabled}
        onClick={(event) => {
          event.stopPropagation();
          onDelete(item.session_id);
        }}
        className={`mr-1 rounded-md p-1.5 opacity-0 transition group-hover:opacity-100 ${deleteDisabled ? "cursor-not-allowed text-slate-300" : "text-slate-500 hover:bg-slate-300/60 hover:text-rose-600"}`}
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
      <div className="flex h-full w-[60px] flex-col items-center border-r border-slate-200/70 bg-[#f9f9f9] px-2 py-3">
        <button type="button" onClick={onToggleCollapsed} className="mb-2 flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-200/70">
          <Menu size={18} />
        </button>
        <button type="button" onClick={onNewChat} className="mb-1 flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-200/70" title="新建聊天">
          <MessageSquarePlus size={18} />
        </button>
        <button type="button" onClick={onOpenSettings} className="mt-auto flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-200/70" title="设置">
          <Settings2 size={18} />
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full flex-col border-r border-slate-200/70 bg-[#f9f9f9] px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <button type="button" onClick={onToggleCollapsed} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-200/70">
          <Menu size={16} />
        </button>
        <div className="flex items-center gap-1">
          {onClose ? (
            <button type="button" onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-200/70 lg:hidden">
              <X size={16} />
            </button>
          ) : null}
          <button type="button" onClick={onNewChat} className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-200/70" title="新建聊天">
            <MessageSquarePlus size={16} />
          </button>
        </div>
      </div>

      <div className="relative mt-3">
        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
        <input
          className="h-9 w-full rounded-lg border border-transparent bg-slate-200/40 pl-9 pr-3 text-sm text-slate-800 placeholder:text-slate-400 focus:border-slate-300 focus:bg-white focus:outline-none"
          placeholder="搜索聊天"
          value={sessionSearch}
          onChange={(event) => onSearchChange(event.target.value)}
        />
      </div>

      <div className="mt-3 flex-1 overflow-y-auto">
        {groups.length === 0 ? <div className="px-3 py-6 text-xs text-slate-400">还没有会话。直接开始一个新聊天。</div> : null}
        {groups.map((group) => (
          <section key={group.key} className="mb-3">
            <div className="px-3 pb-1 pt-2 text-[11px] font-medium text-slate-500">{group.title}</div>
            <div className="grid gap-0.5">
              {group.items.map((item) => (
                <SessionListItem key={item.session_id} item={item} active={item.session_id === activeSessionId} onDelete={onDelete} onSelect={onSelect} />
              ))}
            </div>
          </section>
        ))}
      </div>

      <button
        type="button"
        onClick={onOpenSettings}
        className="mt-2 flex h-10 items-center gap-2 rounded-lg px-3 text-sm text-slate-700 transition hover:bg-slate-200/60"
      >
        <Settings2 size={16} />
        <span>设置</span>
      </button>
    </div>
  );
}

export function SessionSidebar(props) {
  return (
    <aside className={`hidden h-full shrink-0 lg:flex ${props.collapsed ? "w-[60px]" : "w-[260px]"}`}>
      <SidebarContent {...props} />
    </aside>
  );
}

export function MobileSidebar({ open, ...props }) {
  if (!open) {
    return null;
  }
  return (
    <div className="fixed inset-0 z-50 flex bg-black/30 lg:hidden">
      <div className="h-full w-[min(82vw,300px)]">
        <SidebarContent {...props} collapsed={false} />
      </div>
      <button type="button" aria-label="关闭侧栏" className="flex-1" onClick={props.onClose} />
    </div>
  );
}

export function MobileSidebarButton({ onClick }) {
  return (
    <button type="button" onClick={onClick} className="flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-slate-100 lg:hidden">
      <Menu size={18} />
    </button>
  );
}
