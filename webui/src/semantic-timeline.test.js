import test from "node:test";
import assert from "node:assert/strict";
import { buildPrimaryTimeline } from "./semantic-timeline.js";

test("buildPrimaryTimeline folds workflow and tool activity into a single turn card", () => {
  const turns = [{
    turn_id: "turn-1",
    session_id: "sess-1",
    status: "completed",
    goal: "检查页面",
    created_at: "2026-04-17T10:00:00Z",
    updated_at: "2026-04-17T10:00:06Z",
    approval_ids: [],
    evidence_ids: [],
    artifact_ids: [],
  }];
  const messages = [
    { message_id: "msg-user", session_id: "sess-1", turn_id: "turn-1", role: "user", content: "检查页面", created_at: "2026-04-17T10:00:00Z", evidence_refs: [], artifact_refs: [] },
    { message_id: "msg-assistant", session_id: "sess-1", turn_id: "turn-1", role: "assistant", content: "结论", created_at: "2026-04-17T10:00:06Z", evidence_refs: [], artifact_refs: [] },
  ];
  const events = [
    { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "先看页面" } },
    { event_id: "evt-2", session_id: "sess-1", turn_id: "turn-1", type: "task_node_started", created_at: "2026-04-17T10:00:02Z", data: { title: "抓取页面" } },
    {
      event_id: "evt-3",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-17T10:00:03Z",
      data: {
        payload: {
          id: "model-1",
          name: "model",
          result: {
            messages: [{
              content: "调用工具",
              tool_calls: [{ id: "call-1", name: "web_fetch", args: { url: "https://example.com" } }],
            }],
          },
        },
      },
    },
    {
      event_id: "evt-4",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-17T10:00:04Z",
      data: {
        payload: {
          id: "tools-1",
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
                raw_output: JSON.stringify({ url: "https://example.com", body_excerpt: "<html>example</html>" }),
                source: { tool_name: "web_fetch", url: "https://example.com" },
              }),
            }],
          },
        },
      },
    },
    { event_id: "evt-5", session_id: "sess-1", turn_id: "turn-1", type: "approval_required", created_at: "2026-04-17T10:00:05Z", data: { approval_id: "apr-1", reason: "需要网络访问" } },
  ];

  const timeline = buildPrimaryTimeline(messages, events, turns, true);
  assert.deepEqual(timeline.map((item) => item.type), [
    "local_user",
    "turn_card",
    "approval_required",
    "assistant_message",
  ]);

  const turnCard = timeline[1];
  assert.equal(turnCard.data.workflow.count, 2);
  assert.equal(turnCard.data.workflow.items[0].summary, "先看页面");
  assert.equal(turnCard.data.workflow.items[1].title, "步骤开始");
  assert.equal(turnCard.data.tools.count, 1);
  assert.equal(turnCard.data.tools.items[0].summary, "Fetched example");
  assert.ok(turnCard.data.tools.items[0].chips.includes("success"));
  assert.ok(turnCard.data.tools.items[0].chips.includes("example.com"));
  assert.equal(turnCard.data.activity.count, 1);
  assert.equal(turnCard.data.activity.items[0].type, "approval_required");
  assert.equal(turnCard.data.debug.tool_calls[0].tool_name, "web_fetch");
  assert.match(turnCard.data.debug.tool_calls[0].raw_output, /body_excerpt/);
});

test("buildPrimaryTimeline hides key approval cards when disabled but keeps turn data", () => {
  const turns = [{ turn_id: "turn-1", session_id: "sess-1", status: "awaiting_approval", created_at: "2026-04-17T10:00:00Z", updated_at: "2026-04-17T10:00:02Z", approval_ids: ["apr-1"], evidence_ids: [], artifact_ids: [] }];
  const messages = [{ message_id: "msg-user", session_id: "sess-1", turn_id: "turn-1", role: "user", content: "继续", created_at: "2026-04-17T10:00:00Z", evidence_refs: [], artifact_refs: [] }];
  const events = [{ event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "approval_required", created_at: "2026-04-17T10:00:01Z", data: { approval_id: "apr-1", reason: "需要执行命令" } }];

  const timeline = buildPrimaryTimeline(messages, events, turns, false);
  assert.deepEqual(timeline.map((item) => item.type), ["local_user", "turn_card"]);
  assert.equal(timeline[1].data.activity.count, 1);
  assert.equal(timeline[1].data.approval_count, 1);
});
