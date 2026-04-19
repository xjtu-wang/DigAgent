import test from "node:test";
import assert from "node:assert/strict";
import { buildConversationItems } from "./conversation-items.js";

test("buildConversationItems expands process events into ordered chat items", () => {
  const messages = [
    {
      message_id: "msg-user",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "user",
      content: "检查页面",
      created_at: "2026-04-19T10:00:00Z",
      evidence_refs: [],
      artifact_refs: [],
    },
    {
      message_id: "msg-assistant",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "assistant",
      content: "已完成检查",
      created_at: "2026-04-19T10:00:07Z",
      evidence_refs: [],
      artifact_refs: [],
    },
  ];
  const events = [
    { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-19T10:00:01Z", data: { text: "先看页面。" } },
    { event_id: "evt-2", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-19T10:00:01.200Z", data: { text: "再确认交互。" } },
    {
      event_id: "evt-3",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-19T10:00:02Z",
      data: {
        payload: {
          name: "model",
          result: {
            messages: [{ content: "抓取登录页", tool_calls: [{ id: "call-1", name: "web_fetch", args: { url: "https://example.com/login" } }] }],
          },
        },
      },
    },
    {
      event_id: "evt-4",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "langgraph_tasks",
      created_at: "2026-04-19T10:00:03Z",
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
                title: "Web Fetch: https://example.com/login",
                summary: "Fetched example login page",
                source: { tool_name: "web_fetch", url: "https://example.com/login" },
              }),
            }],
          },
        },
      },
    },
    {
      event_id: "evt-5",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "participant_handoff",
      created_at: "2026-04-19T10:00:04Z",
      data: { handoff_from: "assistant", handoff_to: "hephaestus-deepworker", summary: "转给执行 agent。" },
    },
    {
      event_id: "evt-6",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "participant_message",
      created_at: "2026-04-19T10:00:05Z",
      data: { participant_profile: "hephaestus-deepworker", message: "页面结构正常。" },
    },
    {
      event_id: "evt-7",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "approval_required",
      created_at: "2026-04-19T10:00:06Z",
      data: { approval_id: "apr-1", reason: "需要继续网络访问" },
    },
  ];

  const items = buildConversationItems(messages, events, true);

  assert.deepEqual(items.map((item) => item.type), [
    "user_message",
    "assistant_process",
    "tool_action",
    "tool_observation",
    "participant_handoff",
    "participant_message",
    "approval_required",
    "assistant_message",
  ]);
  assert.equal(items[1].data.detail, "先看页面。再确认交互。");
  assert.equal(items[2].data.tool_name, "web_fetch");
  assert.equal(items[3].data.source_host, "example.com");
  assert.equal(items[6].data.approval_id, "apr-1");
});

test("buildConversationItems hides approval and notice items when disabled", () => {
  const messages = [
    {
      message_id: "msg-user",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "user",
      content: "继续",
      created_at: "2026-04-19T10:00:00Z",
      evidence_refs: [],
      artifact_refs: [],
    },
  ];
  const events = [
    { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "approval_required", created_at: "2026-04-19T10:00:01Z", data: { approval_id: "apr-1" } },
    { event_id: "evt-2", session_id: "sess-1", turn_id: "turn-1", type: "failed", created_at: "2026-04-19T10:00:02Z", data: { error: "boom" } },
  ];

  assert.deepEqual(buildConversationItems(messages, events, false).map((item) => item.type), ["user_message"]);
});

test("buildConversationItems splits live assistant chunks by paragraph boundaries", () => {
  const items = buildConversationItems(
    [{
      message_id: "msg-user",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "user",
      content: "继续",
      created_at: "2026-04-19T10:00:00Z",
      evidence_refs: [],
      artifact_refs: [],
    }],
    [
      {
        event_id: "evt-1",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "assistant_chunk",
        created_at: "2026-04-19T10:00:01Z",
        data: { text: "先确认入口。" },
      },
      {
        event_id: "evt-2",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "assistant_chunk",
        created_at: "2026-04-19T10:00:01.200Z",
        data: { text: "\n\n再测试上传流程。" },
      },
    ],
    { showKeySystemCards: true, activeTurnId: "turn-1" },
  );

  assert.deepEqual(items.map((item) => item.type), ["user_message", "assistant_process", "assistant_process"]);
  assert.equal(items[1].data.detail, "先确认入口。");
  assert.equal(items[2].data.detail, "再测试上传流程。");
});

test("buildConversationItems does not split live assistant chunks on invisible same-second events", () => {
  const items = buildConversationItems(
    [{
      message_id: "msg-user",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "user",
      content: "继续",
      created_at: "2026-04-19T10:00:00Z",
      evidence_refs: [],
      artifact_refs: [],
    }],
    [
      {
        event_id: "evt-1",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "assistant_chunk",
        created_at: "2026-04-19T10:00:01Z",
        data: { text: "先整理线索" },
      },
      {
        event_id: "evt-2",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "langgraph_tasks",
        created_at: "2026-04-19T10:00:01Z",
        data: {
          payload: {
            name: "MemoryMiddleware.before_agent",
            result: { messages: [] },
          },
        },
      },
      {
        event_id: "evt-3",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "assistant_chunk",
        created_at: "2026-04-19T10:00:01Z",
        data: { text: "，确认入口。" },
      },
    ],
    { showKeySystemCards: true, activeTurnId: "turn-1" },
  );

  assert.deepEqual(items.map((item) => item.type), ["user_message", "assistant_process"]);
  assert.equal(items[1].data.detail, "先整理线索，确认入口。");
});

test("buildConversationItems keeps tool action ahead of matching observation for same-second events", () => {
  const items = buildConversationItems(
    [],
    [
      {
        event_id: "evt-action",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "langgraph_tasks",
        created_at: "2026-04-19T10:00:02Z",
        data: {
          payload: {
            name: "model",
            result: {
              messages: [{
                content: "执行命令",
                tool_calls: [{ id: "call-1", name: "execute", args: { command: "id" } }],
              }],
            },
          },
        },
      },
      {
        event_id: "evt-observation",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "tool_result",
        created_at: "2026-04-19T10:00:02Z",
        data: {
          tool_call_id: "call-1",
          tool_name: "execute",
          summary: "命令执行成功",
          detail: "<no output>",
        },
      },
    ],
    true,
  );

  assert.deepEqual(items.map((item) => item.type), ["tool_action", "tool_observation"]);
  assert.equal(items[0].data.tool_call_id, "call-1");
  assert.equal(items[1].data.tool_call_id, "call-1");
});
