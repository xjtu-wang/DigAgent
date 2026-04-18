import test from "node:test";
import assert from "node:assert/strict";
import { filterActivityEvents, filterPrimaryTimeline, mergeHistory } from "./timeline-utils.js";

test("filterPrimaryTimeline keeps messages, turn cards, and key approval cards", () => {
  const timeline = [
    { event_id: "1", type: "local_user", created_at: "2026-04-17T10:00:00Z" },
    { event_id: "2", type: "turn_card", created_at: "2026-04-17T10:00:01Z" },
    { event_id: "3", type: "assistant_message", created_at: "2026-04-17T10:00:02Z" },
    { event_id: "4", type: "approval_required", created_at: "2026-04-17T10:00:03Z" },
    { event_id: "5", type: "completed", created_at: "2026-04-17T10:00:04Z" },
  ];
  assert.deepEqual(filterPrimaryTimeline(timeline, true).map((item) => item.event_id), ["1", "2", "3", "4"]);
  assert.deepEqual(filterPrimaryTimeline(timeline, false).map((item) => item.event_id), ["1", "2", "3"]);
});

test("filterActivityEvents keeps execution activity sorted by newest first", () => {
  const events = [
    { event_id: "older", type: "plan", created_at: "2026-04-17T10:00:01Z" },
    { event_id: "newer", type: "tool_result", created_at: "2026-04-17T10:00:05Z" },
    { event_id: "ignored", type: "assistant_message", created_at: "2026-04-17T10:00:06Z" },
  ];
  assert.deepEqual(filterActivityEvents(events).map((item) => item.event_id), ["newer", "older"]);
});

test("mergeHistory inserts a turn execution card between user prompt and assistant reply", () => {
  const messages = [
    { message_id: "msg-user", session_id: "sess-1", turn_id: "turn-1", role: "user", content: "检查仓库", created_at: "2026-04-17T10:00:00Z", evidence_refs: [], artifact_refs: [] },
    { message_id: "msg-assistant", session_id: "sess-1", turn_id: "turn-1", role: "assistant", content: "已完成检查", created_at: "2026-04-17T10:00:03Z", evidence_refs: [], artifact_refs: [] },
  ];
  const turns = [{ turn_id: "turn-1", session_id: "sess-1", status: "completed", goal: "检查仓库", created_at: "2026-04-17T10:00:00Z", finished_at: "2026-04-17T10:00:03Z", evidence_ids: [], artifact_ids: [], approval_ids: [], pending_approvals: [] }];
  const events = [{ event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "tool_result", created_at: "2026-04-17T10:00:02Z", data: { summary: "读取了关键文件" } }];
  assert.deepEqual(mergeHistory(messages, events, turns).map((item) => item.type), ["local_user", "turn_card", "tool_result", "assistant_message"]);
});
