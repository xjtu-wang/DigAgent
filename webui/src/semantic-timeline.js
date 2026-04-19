import { buildConversationItems } from "./conversation-items.js";

export function buildPrimaryTimeline(messages, events, turns, showKeySystemCards = true) {
  void turns;
  return buildConversationItems(messages, events, showKeySystemCards);
}
