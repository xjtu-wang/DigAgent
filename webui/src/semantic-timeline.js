import { filterPrimaryTimeline, mergeHistory } from "./timeline-utils.js";

export function buildPrimaryTimeline(messages, events, turns, showKeySystemCards = true) {
  return filterPrimaryTimeline(mergeHistory(messages, events, turns), showKeySystemCards);
}
