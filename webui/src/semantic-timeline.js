import { buildConversationItems } from "./conversation-items.js";

function normalizeOptions(input) {
  if (typeof input === "boolean") {
    return { showKeySystemCards: input, activeTurnId: null };
  }
  return {
    showKeySystemCards: input?.showKeySystemCards ?? true,
    activeTurnId: input?.activeTurnId ?? null,
  };
}

export function buildPrimaryTimeline(messages, events, turns, options = true) {
  void turns;
  return buildConversationItems(messages, events, normalizeOptions(options));
}
