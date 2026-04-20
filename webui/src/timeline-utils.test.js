import test from "node:test";
import assert from "node:assert/strict";
import { eventSummary, filterActivityEvents, filterPrimaryTimeline, mergeHistory } from "./timeline-utils.js";

test("filterPrimaryTimeline keeps messages, turn cards, and key approval cards", () => {
  const timeline = [
    { event_id: "1", type: "user_message", created_at: "2026-04-17T10:00:00Z" },
    { event_id: "2", type: "assistant_process", created_at: "2026-04-17T10:00:01Z" },
    { event_id: "3", type: "tool_action", created_at: "2026-04-17T10:00:02Z" },
    { event_id: "4", type: "tool_observation", created_at: "2026-04-17T10:00:03Z" },
    { event_id: "5", type: "participant_message", created_at: "2026-04-17T10:00:04Z" },
    { event_id: "6", type: "approval_required", created_at: "2026-04-17T10:00:05Z" },
    { event_id: "7", type: "system_notice", created_at: "2026-04-17T10:00:06Z" },
    { event_id: "8", type: "assistant_message", created_at: "2026-04-17T10:00:07Z" },
  ];
  assert.deepEqual(filterPrimaryTimeline(timeline, true).map((item) => item.event_id), ["1", "2", "3", "4", "5", "6", "7", "8"]);
  assert.deepEqual(filterPrimaryTimeline(timeline, false).map((item) => item.event_id), ["1", "2", "3", "4", "5", "8"]);
});

test("filterActivityEvents keeps execution activity sorted by newest first", () => {
  const events = [
    { event_id: "older", type: "plan", created_at: "2026-04-17T10:00:01Z" },
    { event_id: "newer", type: "tool_result", created_at: "2026-04-17T10:00:05Z" },
    { event_id: "ignored", type: "assistant_message", created_at: "2026-04-17T10:00:06Z" },
  ];
  assert.deepEqual(filterActivityEvents(events).map((item) => item.event_id), ["newer", "older"]);
});

test("mergeHistory emits a sequential process flow instead of a turn card", () => {
  const messages = [
    { message_id: "msg-user", session_id: "sess-1", turn_id: "turn-1", role: "user", content: "检查仓库", created_at: "2026-04-17T10:00:00Z", evidence_refs: [], artifact_refs: [] },
    { message_id: "msg-assistant", session_id: "sess-1", turn_id: "turn-1", role: "assistant", content: "已完成检查", created_at: "2026-04-17T10:00:03Z", evidence_refs: [], artifact_refs: [] },
  ];
  const turns = [{ turn_id: "turn-1", session_id: "sess-1", status: "completed", goal: "检查仓库", created_at: "2026-04-17T10:00:00Z", finished_at: "2026-04-17T10:00:03Z", evidence_ids: [], artifact_ids: [], approval_ids: [], pending_approvals: [] }];
  const events = [
    { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "先读 README。" } },
    {
      event_id: "evt-observation",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "tool_result",
      created_at: "2026-04-17T10:00:02Z",
      data: { tool_call_id: "call-1", tool_name: "read_file", summary: "读取了关键文件" },
    },
    {
      event_id: "evt-action",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-17T10:00:03Z",
      data: {
        payload: {
          name: "model",
          result: {
            messages: [{ content: "读取文件", tool_calls: [{ id: "call-1", name: "read_file", args: { path: "README.md" } }] }],
          },
        },
      },
    },
  ];
  assert.deepEqual(mergeHistory(messages, events, turns).map((item) => item.type), [
    "user_message",
    "assistant_process",
    "tool_action",
    "tool_observation",
    "assistant_message",
  ]);
});

test("mergeHistory suppresses chunk-only process rows once the final reply is present", () => {
  const messages = [
    { message_id: "msg-user", session_id: "sess-1", turn_id: "turn-1", role: "user", content: "你好", created_at: "2026-04-17T10:00:00Z", evidence_refs: [], artifact_refs: [] },
    { message_id: "msg-assistant", session_id: "sess-1", turn_id: "turn-1", role: "assistant", content: "你好，我可以帮你分析问题。", created_at: "2026-04-17T10:00:03Z", evidence_refs: [], artifact_refs: [] },
  ];
  const turns = [{ turn_id: "turn-1", session_id: "sess-1", status: "completed", goal: "你好", created_at: "2026-04-17T10:00:00Z", finished_at: "2026-04-17T10:00:03Z", evidence_ids: [], artifact_ids: [], approval_ids: [], pending_approvals: [] }];
  const events = [
    { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "你好，" } },
    { event_id: "evt-2", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:02Z", data: { text: "我可以帮你分析问题。" } },
  ];

  assert.deepEqual(mergeHistory(messages, events, turns).map((item) => item.type), ["user_message", "assistant_message"]);
});

test("eventSummary uses user-facing wording for approval and workflow states", () => {
  assert.equal(eventSummary({ type: "approval_resolved", data: { status: "approved" } }), "已批准，执行继续");
  assert.equal(eventSummary({ type: "awaiting_approval", data: { approval_ids: ["apr-1", "apr-2"] } }), "等待确认（2 项）");
  assert.equal(eventSummary({ type: "graph_op_applied", data: {} }), "执行流程已更新");
  assert.equal(eventSummary({ type: "turn_terminal_recorded", data: { status: "awaiting_user_input" } }), "执行结束 · 等待补充信息");
});
