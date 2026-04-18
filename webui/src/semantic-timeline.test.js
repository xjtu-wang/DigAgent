import test from "node:test";
import assert from "node:assert/strict";
import { buildPrimaryTimeline } from "./semantic-timeline.js";

test("buildPrimaryTimeline groups assistant chunks and tool results into semantic cards", () => {
  const turns = [{ turn_id: "turn-1", session_id: "sess-1", status: "completed", created_at: "2026-04-17T10:00:00Z", updated_at: "2026-04-17T10:00:05Z", approval_ids: [], evidence_ids: [], artifact_ids: [] }];
  const messages = [
    { message_id: "msg-user", session_id: "sess-1", turn_id: "turn-1", role: "user", content: "检查页面", created_at: "2026-04-17T10:00:00Z", evidence_refs: [], artifact_refs: [] },
    { message_id: "msg-assistant", session_id: "sess-1", turn_id: "turn-1", role: "assistant", content: "结论", created_at: "2026-04-17T10:00:05Z", evidence_refs: [], artifact_refs: [] },
  ];
  const events = [
    { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "先看页面" } },
    {
      event_id: "evt-2",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-17T10:00:02Z",
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
      event_id: "evt-3",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-17T10:00:03Z",
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
  ];

  const timeline = buildPrimaryTimeline(messages, events, turns, true);
  assert.deepEqual(timeline.map((item) => item.type), [
    "local_user",
    "assistant_process",
    "tool_summary_card",
    "assistant_message",
    "turn_summary_card",
  ]);
  assert.equal(timeline[1].data.message, "先看页面");
  assert.equal(timeline[2].data.tool_name, "web_fetch");
  assert.equal(timeline[2].data.source_url, "https://example.com");
  assert.equal(timeline[4].data.raw_event_count, 3);
});
