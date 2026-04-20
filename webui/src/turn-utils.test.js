import test from "node:test";
import assert from "node:assert/strict";
import { buildTurnTimelineEntries, normalizeTurnEvent, normalizeTurns, turnRecentActionSummary, turnResultSummary, turnStatusLabel } from "./turn-utils.js";

test("normalizeTurns sorts newest turn first and preserves arrays", () => {
  const turns = normalizeTurns([
    { turn_id: "turn-1", created_at: "2026-04-17T10:00:00Z" },
    { turn_id: "turn-2", created_at: "2026-04-17T10:00:05Z", approval_ids: ["apr-1"] },
  ]);
  assert.deepEqual(turns.map((item) => item.turn_id), ["turn-2", "turn-1"]);
  assert.deepEqual(turns[0].approval_ids, ["apr-1"]);
  assert.deepEqual(turns[0].pending_approvals, []);
});

test("normalizeTurnEvent hoists turn_id from event data", () => {
  const event = normalizeTurnEvent({ event_id: "evt-1", type: "tool_result", data: { turn_id: "turn-1", summary: "done" } });
  assert.equal(event.turn_id, "turn-1");
});

test("turnResultSummary and turnRecentActionSummary prefer durable turn state", () => {
  const turn = { status: "awaiting_approval", awaiting_reason: "需要执行 shell 命令" };
  const events = [{ event_id: "evt-1", type: "tool_result", created_at: "2026-04-17T10:00:05Z", data: { summary: "准备执行 shell 命令" } }];
  assert.equal(turnResultSummary(turn, null, events), "需要执行 shell 命令");
  assert.equal(turnRecentActionSummary(turn, events), "准备执行 shell 命令");
});

test("buildTurnTimelineEntries produces a summarized execution card", () => {
  const entries = buildTurnTimelineEntries(
    [{ turn_id: "turn-1", session_id: "sess-1", status: "completed", goal: "检查仓库", created_at: "2026-04-17T10:00:00Z", evidence_ids: ["ev-1"], artifact_ids: [], approval_ids: [], pending_approvals: [] }],
    [{ message_id: "msg-1", session_id: "sess-1", turn_id: "turn-1", role: "assistant", content: "已经检查完成", created_at: "2026-04-17T10:00:03Z" }],
    [{ event_id: "evt-1", session_id: "sess-1", turn_id: "turn-1", type: "tool_result", created_at: "2026-04-17T10:00:02Z", data: { summary: "扫描了 12 个文件" } }],
  );
  assert.equal(entries[0].type, "turn_card");
  assert.equal(entries[0].data.goal, "检查仓库");
  assert.equal(entries[0].data.action_summary, "扫描了 12 个文件");
  assert.equal(entries[0].data.evidence_count, 1);
  assert.equal(entries[0].data.status_label, "已完成");
});

test("turnStatusLabel exposes user-facing labels", () => {
  assert.equal(turnStatusLabel("awaiting_approval"), "等待确认");
  assert.equal(turnStatusLabel("timed_out"), "执行超时");
});
