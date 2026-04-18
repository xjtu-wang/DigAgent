import test from "node:test";
import assert from "node:assert/strict";
import { buildWorkflowItems, groupSessionsByDate } from "./chat-utils.js";

test("buildWorkflowItems orders nodes by observed workflow events", () => {
  const graph = {
    nodes: [
      { node_id: "report", title: "Write report", kind: "report", status: "pending", description: "report", summary: "", metadata: {} },
      { node_id: "search", title: "Search repo", kind: "tool", status: "completed", description: "search", summary: "search done", metadata: { tool_name: "repo_search" } },
    ],
  };
  const events = [
    { event_id: "evt-2", type: "task_node_completed", created_at: "2026-04-17T10:00:03Z", data: { node_id: "search", title: "Search repo" } },
    { event_id: "evt-1", type: "task_node_started", created_at: "2026-04-17T10:00:01Z", data: { node_id: "search", title: "Search repo" } },
  ];
  const items = buildWorkflowItems(graph, events);
  assert.deepEqual(items.map((item) => item.node_id), ["search", "report"]);
  assert.equal(items[0].startedAt, "2026-04-17T10:00:01Z");
  assert.equal(items[0].completedAt, "2026-04-17T10:00:03Z");
  assert.equal(items[0].toolName, "repo_search");
  assert.equal(items[1].eventCount, 0);
});

test("groupSessionsByDate keeps today and earlier buckets", () => {
  const sessions = [
    { session_id: "today", updated_at: new Date().toISOString() },
    { session_id: "earlier", updated_at: "2026-04-01T10:00:00Z" },
  ];
  const groups = groupSessionsByDate(sessions);
  assert.equal(groups.length >= 1, true);
  assert.equal(groups.some((group) => group.items.some((item) => item.session_id === "today")), true);
});
