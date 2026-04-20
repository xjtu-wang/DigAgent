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
    {
      event_id: "evt-6",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "approval_required",
      created_at: "2026-04-17T10:00:05.500Z",
      data: { approval_id: "apr-1", reason: "需要执行网络请求" },
    },
  ];

  const timeline = buildPrimaryTimeline(messages, events, turns, true);

  assert.deepEqual(timeline.map((item) => item.type), [
    "message",
    "workflow",
    "tool",
    "agent",
    "approval",
    "message",
  ]);
  assert.equal(timeline[1].items[0].data.detail, "先看页面。");
  assert.equal(timeline[2].items[0].data.tool_name, "web_fetch");
  assert.equal(timeline[2].items[1].data.source_host, "example.com");
  assert.equal(timeline[4].items[0].data.approval_id, "apr-1");
  assert.equal(timeline[5].items[0].data.message, "结论");
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

  assert.deepEqual(timeline.map((item) => item.type), ["message"]);
});

test("buildPrimaryTimeline suppresses chunk-only duplicates after final assistant reply", () => {
  const timeline = buildPrimaryTimeline(
    [
      {
        message_id: "msg-user",
        session_id: "sess-1",
        turn_id: "turn-1",
        role: "user",
        content: "你好",
        created_at: "2026-04-17T10:00:00Z",
        evidence_refs: [],
        artifact_refs: [],
      },
      {
        message_id: "msg-assistant",
        session_id: "sess-1",
        turn_id: "turn-1",
        role: "assistant",
        content: "你好，我可以帮你分析问题。",
        created_at: "2026-04-17T10:00:03Z",
        evidence_refs: [],
        artifact_refs: [],
      },
    ],
    [
      { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "你好，" } },
      { event_id: "evt-2", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:02Z", data: { text: "我可以帮你分析问题。" } },
    ],
    [],
    true,
  );

  assert.deepEqual(timeline.map((item) => item.type), ["message", "message"]);
});

test("buildPrimaryTimeline keeps live assistant process while turn is still active", () => {
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
      { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "先整理上下文。" } },
      { event_id: "evt-2", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:02Z", data: { text: "\n\n再" } },
      { event_id: "evt-3", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:02Z", data: { text: "执行下一步。" } },
    ],
    [],
    { showKeySystemCards: true, activeTurnId: "turn-1" },
  );

  assert.deepEqual(timeline.map((item) => item.type), ["message", "workflow"]);
  assert.equal(timeline[1].items[0].data.detail, "先整理上下文。");
  assert.equal(timeline[1].items[1].data.detail, "再执行下一步。");
});

test("buildPrimaryTimeline keeps live assistant process merged across invisible same-second events", () => {
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
      { event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "先整理线索" } },
      {
        event_id: "evt-2",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "langgraph_tasks",
        created_at: "2026-04-17T10:00:01Z",
        data: {
          payload: {
            name: "MemoryMiddleware.before_agent",
            result: { messages: [] },
          },
        },
      },
      { event_id: "evt-3", session_id: "sess-1", turn_id: "turn-1", type: "assistant_chunk", created_at: "2026-04-17T10:00:01Z", data: { text: "，确认入口。" } },
    ],
    [],
    { showKeySystemCards: true, activeTurnId: "turn-1" },
  );

  assert.deepEqual(timeline.map((item) => item.type), ["message", "workflow"]);
  assert.equal(timeline[1].items[0].data.detail, "先整理线索，确认入口。");
});

test("buildPrimaryTimeline keeps tool action ahead of matching observation for same-second events", () => {
  const timeline = buildPrimaryTimeline(
    [],
    [
      {
        event_id: "evt-action",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "langgraph_tasks",
        created_at: "2026-04-17T10:00:02Z",
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
        created_at: "2026-04-17T10:00:02Z",
        data: {
          tool_call_id: "call-1",
          tool_name: "execute",
          summary: "命令执行成功",
          detail: "<no output>",
        },
      },
    ],
    [],
    true,
  );

  assert.deepEqual(timeline.map((item) => item.type), ["tool"]);
  assert.equal(timeline[0].items[0].data.tool_call_id, "call-1");
  assert.equal(timeline[0].items[1].data.tool_call_id, "call-1");
});

test("buildPrimaryTimeline only classifies skill and mcp usage when fields are explicit", () => {
  const timeline = buildPrimaryTimeline(
    [],
    [
      {
        event_id: "evt-skill",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "langgraph_tasks",
        created_at: "2026-04-17T10:00:01Z",
        data: {
          payload: {
            name: "model",
            result: {
              messages: [{
                content: "应用界面加固",
                tool_calls: [{ id: "call-skill", name: "tool_router", args: { skill_name: "harden" } }],
              }],
            },
          },
        },
      },
      {
        event_id: "evt-mcp",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "tool_result",
        created_at: "2026-04-17T10:00:02Z",
        data: {
          tool_call_id: "call-mcp",
          tool_name: "stitch",
          summary: "MCP server 返回结果",
          source: { kind: "mcp", server_id: "stitch" },
        },
      },
      {
        event_id: "evt-generic",
        session_id: "sess-1",
        turn_id: "turn-1",
        type: "tool_result",
        created_at: "2026-04-17T10:00:03Z",
        data: {
          tool_call_id: "call-generic",
          tool_name: "execute",
          summary: "命令执行成功",
        },
      },
    ],
    [],
    true,
  );

  assert.deepEqual(timeline.map((item) => item.type), ["skill", "mcp", "tool"]);
});

test("buildPrimaryTimeline renders non-root assistant messages as agent activity", () => {
  const timeline = buildPrimaryTimeline(
    [{
      message_id: "msg-agent",
      session_id: "sess-1",
      turn_id: "turn-1",
      role: "assistant",
      speaker_profile: "hephaestus-deepworker",
      content: "子 Agent 已完成代码检查。",
      created_at: "2026-04-17T10:00:01Z",
      evidence_refs: [],
      artifact_refs: [],
    }],
    [],
    [],
    true,
  );

  assert.deepEqual(timeline.map((item) => item.type), ["agent"]);
  assert.equal(timeline[0].speakerLabel, "hephaestus-deepworker");
  assert.equal(timeline[0].items[0].data.message, "子 Agent 已完成代码检查。");
});

test("buildPrimaryTimeline keeps approval resolution notices in approval groups", () => {
  const timeline = buildPrimaryTimeline(
    [],
    [{
      event_id: "evt-approval-resolved",
      session_id: "sess-1",
      turn_id: "turn-1",
      type: "approval_resolved",
      created_at: "2026-04-17T10:00:01Z",
      data: {
        approval_id: "apr-1",
        status: "approved",
        summary: "审批已通过，继续执行。",
      },
    }],
    [],
    true,
  );

  assert.deepEqual(timeline.map((item) => item.type), ["approval"]);
  assert.equal(timeline[0].items[0].type, "approval_notice");
  assert.equal(timeline[0].items[0].data.state, "resolved");
});
