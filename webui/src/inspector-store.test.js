import test from "node:test";
import assert from "node:assert/strict";
import { buildInspectorActivityEvents, buildInspectorGraph, buildTurnInspectorStats } from "./inspector-store.js";

const baseTurn = {
  turn_id: "turn_demo",
  session_id: "sess_demo",
  status: "completed",
  goal: "请分析这个题目",
  final_response: "1. 先确认入口\n2. 再验证漏洞\n3. 输出结论",
  created_at: "2026-04-18T12:00:00Z",
  finished_at: "2026-04-18T12:00:05Z",
  evidence_ids: [],
  artifact_ids: [],
  approval_ids: [],
  budget_usage: { tool_calls_used: 0, runtime_seconds_used: 0, active_subagents: 0, active_tools: 0 },
  budget: { max_tool_calls: 50, max_runtime_seconds: 1800, max_parallel_subagents: 3, max_parallel_tools: 2 },
};

const messages = [
  { message_id: "msg_user", role: "user", session_id: "sess_demo", turn_id: "turn_demo", content: "请分析这个题目", created_at: "2026-04-18T12:00:00Z" },
  { message_id: "msg_assistant", role: "assistant", session_id: "sess_demo", turn_id: "turn_demo", content: "1. 先确认入口\n2. 再验证漏洞\n3. 输出结论", created_at: "2026-04-18T12:00:05Z" },
];

test("buildInspectorGraph reconstructs durable workflow nodes when task graph is missing", () => {
  const graph = buildInspectorGraph(baseTurn, messages);
  assert.equal(graph.source, "durable_trace");
  assert.equal(graph.nodes[0].title, "收到目标");
  assert.equal(graph.nodes[1].title, "答复步骤 1");
  assert.equal(graph.nodes.at(-1).title, "最终结果");
});

test("buildInspectorActivityEvents merges durable execution milestones", () => {
  const events = buildInspectorActivityEvents([], [baseTurn], messages);
  assert.deepEqual(events.map((item) => item.type), ["turn_terminal_recorded", "assistant_response_recorded", "user_task_recorded", "turn_recorded"]);
});

test("buildInspectorActivityEvents keeps same-timestamp events in raw sequence order", () => {
  const events = buildInspectorActivityEvents([
    { event_id: "evt-2", turn_id: "turn_demo", type: "approval_required", created_at: "2026-04-18T12:00:02Z", turn_event_index: 2, data: { approval_id: "apr-1" } },
    { event_id: "evt-1", turn_id: "turn_demo", type: "tool_result", created_at: "2026-04-18T12:00:02Z", turn_event_index: 1, data: { tool_name: "read_file" } },
  ], [baseTurn], messages, "turn_demo");
  assert.ok(events.findIndex((item) => item.event_id === "evt-2") < events.findIndex((item) => item.event_id === "evt-1"));
});

test("buildTurnInspectorStats derives truthful metrics from turn records", () => {
  const graph = buildInspectorGraph(baseTurn, messages);
  const activity = buildInspectorActivityEvents([], [baseTurn], messages);
  const stats = buildTurnInspectorStats(baseTurn, messages, activity, graph);
  assert.equal(stats.durationLabel, "5.0s");
  assert.equal(stats.responseChars > 0, true);
  assert.equal(stats.nodeCount >= 3, true);
  assert.equal(stats.hasRecordedBudgetUsage, false);
});
