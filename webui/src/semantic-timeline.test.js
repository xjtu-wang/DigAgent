import test from "node:test";
import assert from "node:assert/strict";
import { buildPrimaryTimeline } from "./semantic-timeline.js";

test("buildPrimaryTimeline emits a chat-style conversation flow", () => {
  const turns = [{
    turn_id: "turn-1",
    session_id: "sess-1",
    status: "completed",
    created_at: "2026-04-17T10:00:00Z",
    updated_at: "2026-04-17T10:00:06Z",
  }];
  const messages = [
    {
      message_id: "msg-user",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "user",
      content: "@hephaestus-deepworker 检查页面",
      created_at: "2026-04-17T10:00:00Z",
      mentions: ["hephaestus-deepworker"],
      evidence_refs: [],
      artifact_refs: [],
    },
    {
      message_id: "msg-assistant",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "assistant",
      content: "结论",
      created_at: "2026-04-17T10:00:06Z",
      evidence_refs: [],
      artifact_refs: [],
    },
  ];
  const events = [
    { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "先看页面。" } },
    {
      event_id: "evt-2",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-17T10:00:02Z",
      data: {
        payload: {
          name: "model",
          result: {
            messages: [{
              content: "调用抓取工具",
              tool_calls: [{ id: "call-1", name: "web_fetch", args: { url: "https://example.com" } }],
            }],
          },
        },
      },
    },
    {
      event_id: "evt-3",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-17T10:00:03Z",
      data: {
        payload: {
          name: "tools",
          result: {
            messages: [{
              type: "tool",
              name: "web_fetch",
              tool_call_id: "call-1",
              status: "success",
              content: JSON.stringify({
                title: "Web Fetch: https://example.com",
                summary: "Fetched example",
                source: { tool_name: "web_fetch", url: "https://example.com" },
              }),
            }],
          },
        },
      },
    },
    {
      event_id: "evt-4",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "participant_handoff",
      created_at: "2026-04-17T10:00:04Z",
      data: { handoff_from: "sisyphus-default", handoff_to: "hephaestus-deepworker", summary: "转交给代码工作 agent。" },
    },
    {
      event_id: "evt-5",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "participant_message",
      created_at: "2026-04-17T10:00:05Z",
      data: { participant_profile: "hephaestus-deepworker", message: "页面结构没有异常。" },
    },
  ];

  const timeline = buildPrimaryTimeline(messages, events, turns, true);

  assert.deepEqual(timeline.map((item) => item.type), [
    "user_message",
    "assistant_thought",
    "tool_action",
    "tool_observation",
    "participant_handoff",
    "participant_message",
    "assistant_message",
  ]);
  assert.deepEqual(timeline[0].data.addressed_participants, ["hephaestus-deepworker"]);
  assert.equal(timeline[1].data.detail, "先看页面。");
  assert.equal(timeline[2].data.tool_name, "web_fetch");
  assert.equal(timeline[2].data.argument_count, 1);
  assert.equal(timeline[3].data.source_host, "example.com");
  assert.equal(timeline[4].data.handoff_to, "hephaestus-deepworker");
  assert.equal(timeline[5].data.participant_profile, "hephaestus-deepworker");
});

test("buildPrimaryTimeline hides approval and notice cards when disabled", () => {
  const timeline = buildPrimaryTimeline(
    [{
      message_id: "msg-user",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "user",
      content: "继续",
      created_at: "2026-04-17T10:00:00Z",
      evidence_refs: [],
      artifact_refs: [],
    }],
    [
      { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "approval_required", created_at: "2026-04-17T10:00:01Z", data: { approval_id: "apr-1", reason: "需要执行命令" } },
      { event_id: "evt-2", session_id: "sess-1", turn_id: "turn-1", type: "failed", created_at: "2026-04-17T10:00:02Z", data: { error: "boom" } },
    ],
    [],
    false,
  );

  assert.deepEqual(timeline.map((item) => item.type), ["user_message"]);
});
