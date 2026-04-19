import test from "node:test";
import assert from "node:assert/strict";
import { buildTurnFlowBlocks } from "./components/chat-flow-model.js";

test("buildTurnFlowBlocks maps turn card content into chat-style blocks", () => {
  const item = {
    type: "turn_card",
    data: {
      workflow: {
        items: [
          {
            event_id: "wf-1",
            type: "assistant_chunk",
            title: "执行过程",
            summary: "先看页面结构",
            detail: "先看页面结构\n再确认提交参数",
            chips: ["2 段"],
            created_at: "2026-04-19T10:00:01Z",
          },
          {
            event_id: "wf-2",
            type: "task_node_started",
            title: "步骤开始",
            summary: "开始抓取页面",
            chips: ["node-a"],
            created_at: "2026-04-19T10:00:02Z",
          },
        ],
      },
      tools: {
        items: [
          {
            tool_call_id: "call-1",
            tool_name: "web_fetch",
            title: "Web Fetch: https://example.com/login",
            summary: "Fetched example login page",
            request_message: "抓取登录页",
            call_args: { url: "https://example.com/login" },
            body_excerpt: "<html>login</html>",
            chips: ["success", "example.com", "1 条事实"],
            created_at: "2026-04-19T10:00:03Z",
          },
        ],
      },
      activity: {
        items: [
          {
            event_id: "act-1",
            type: "subagent",
            title: "子 Agent",
            summary: "把页面枚举任务交给辅助参与者",
            chips: ["worker"],
            created_at: "2026-04-19T10:00:04Z",
          },
          {
            event_id: "act-2",
            type: "approval_required",
            title: "等待审批",
            summary: "需要网络访问",
            chips: ["apr-1"],
            created_at: "2026-04-19T10:00:05Z",
          },
          {
            event_id: "act-3",
            type: "report_ready",
            title: "报告生成",
            summary: "生成了阶段报告",
            chips: ["rpt-1"],
            created_at: "2026-04-19T10:00:06Z",
          },
        ],
      },
    },
  };

  const blocks = buildTurnFlowBlocks(item);
  assert.deepEqual(blocks.map((block) => block.type), [
    "assistant_thought",
    "participant_message",
    "tool_action",
    "tool_observation",
    "participant_handoff",
    "participant_message",
  ]);
  assert.equal(blocks[0].detail.includes("再确认提交参数"), true);
  assert.equal(blocks[2].summary, "请求 https://example.com/login");
  assert.match(blocks[2].detail, /"url": "https:\/\/example.com\/login"/);
  assert.equal(blocks[3].detail, "<html>login</html>");
  assert.equal(blocks.some((block) => block.summary === "需要网络访问"), false);
});
