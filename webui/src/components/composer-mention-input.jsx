import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  applyMentionCompletion,
  collectComposerMentions,
  normalizeMentionAgents,
  resolveActiveMention,
  searchMentionCandidates,
  shouldSubmitComposer,
} from "../composer-utils";
import { Badge } from "./ui";

function cycleIndex(index, total, delta) {
  if (!total) {
    return 0;
  }
  return (index + delta + total) % total;
}

function placeCaret(textarea, selectionStart, setSelectionStart) {
  requestAnimationFrame(() => {
    if (!textarea) {
      return;
    }
    textarea.focus();
    textarea.setSelectionRange(selectionStart, selectionStart);
    setSelectionStart(selectionStart);
  });
}

export function ComposerMentionInput({ agents, enterToSend, onSubmit, placeholder, setValue, value }) {
  const [activeIndex, setActiveIndex] = useState(0);
  const [isComposing, setIsComposing] = useState(false);
  const [selectionStart, setSelectionStart] = useState(() => String(value || "").length);
  const textareaRef = useRef(null);
  const mentionAgents = useMemo(() => normalizeMentionAgents(agents), [agents]);
  const mentions = useMemo(() => collectComposerMentions(value, mentionAgents), [mentionAgents, value]);
  const activeMention = useMemo(() => resolveActiveMention(value, selectionStart), [selectionStart, value]);
  const suggestions = useMemo(() => activeMention ? searchMentionCandidates(mentionAgents, activeMention.query) : [], [activeMention, mentionAgents]);

  useEffect(() => {
    setActiveIndex(0);
  }, [activeMention?.query, activeMention?.start, suggestions.length]);

  function updateSelection(target) {
    setSelectionStart(target.selectionStart ?? String(target.value || "").length);
  }

  function insertMention(agentName) {
    if (!activeMention) {
      return;
    }
    const next = applyMentionCompletion(value, activeMention, agentName);
    setValue(next.value);
    placeCaret(textareaRef.current, next.selectionStart, setSelectionStart);
  }

  function submitComposer() {
    const content = String(value || "").trim();
    if (!content) {
      return;
    }
    onSubmit({
      content,
      mentions: mentions.filter((item) => item.configured).map((item) => item.name),
    });
  }

  function handleKeyDown(event) {
    const suggestionOpen = suggestions.length > 0;
    if (suggestionOpen && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      setActiveIndex((current) => cycleIndex(current, suggestions.length, event.key === "ArrowDown" ? 1 : -1));
      return;
    }
    if (suggestionOpen && (event.key === "Tab" || (event.key === "Enter" && !event.shiftKey && !event.nativeEvent?.shiftKey))) {
      event.preventDefault();
      insertMention(suggestions[activeIndex]?.name || suggestions[0]?.name);
      return;
    }
    if (!shouldSubmitComposer(event, { enterToSend, isComposing })) {
      return;
    }
    event.preventDefault();
    submitComposer();
  }

  return (
    <div className="px-1 pt-1">
      <textarea
        ref={textareaRef}
        className="max-h-[240px] min-h-[56px] w-full resize-none border-0 bg-transparent px-4 py-3 text-[15px] leading-7 text-slate-900 outline-none transition placeholder:text-slate-400 focus:ring-0"
        placeholder={placeholder}
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          updateSelection(event.target);
        }}
        onClick={(event) => updateSelection(event.target)}
        onCompositionEnd={() => setIsComposing(false)}
        onCompositionStart={() => setIsComposing(true)}
        onKeyDown={handleKeyDown}
        onSelect={(event) => updateSelection(event.target)}
      />
      {mentions.length ? (
        <div className="flex flex-wrap gap-1.5 px-4 pb-2">
          {mentions.map((item) => (
            <Badge
              key={item.name}
              className={item.configured ? "bg-sky-100 text-sky-800" : "bg-amber-100 text-amber-800"}
            >
              @{item.name}
            </Badge>
          ))}
        </div>
      ) : null}
      {suggestions.length ? (
        <div className="mx-4 mb-2 rounded-2xl border border-slate-200 bg-white p-1 shadow-[0_12px_30px_rgba(15,23,42,0.08)]">
          {suggestions.map((item, index) => (
            <button
              key={item.name}
              type="button"
              className={`flex w-full items-start justify-between gap-3 rounded-xl px-3 py-2 text-left ${index === activeIndex ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-50"}`}
              onMouseDown={(event) => {
                event.preventDefault();
                insertMention(item.name);
              }}
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">@{item.name}</div>
                {item.description ? <div className={`mt-0.5 text-xs ${index === activeIndex ? "text-slate-300" : "text-slate-500"}`}>{item.description}</div> : null}
              </div>
              <div className={`shrink-0 text-[11px] ${index === activeIndex ? "text-slate-300" : "text-slate-400"}`}>Tab</div>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
