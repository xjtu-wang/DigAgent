import test from "node:test";
import assert from "node:assert/strict";
import {
  composerRuntimeChips,
  inspectorTabLabel,
  permissionRuleLabel,
  settingsSummaryBadges,
  statusLabel,
  timelineDensityLabel,
} from "./ui-copy.js";

test("statusLabel maps known runtime states to user-facing copy", () => {
  assert.equal(statusLabel("awaiting_approval"), "等待确认");
  assert.equal(statusLabel("awaiting_user_input"), "等待补充信息");
  assert.equal(statusLabel("running"), "进行中");
});

test("statusLabel keeps unknown states visible for debugging", () => {
  assert.equal(statusLabel("mystery_state"), "mystery_state");
});

test("inspector and density labels use user-facing wording", () => {
  assert.equal(inspectorTabLabel("workflow"), "执行流程");
  assert.equal(inspectorTabLabel("session"), "会话设置");
  assert.equal(timelineDensityLabel("comfortable"), "宽松");
  assert.equal(timelineDensityLabel("compact"), "紧凑");
});

test("permission rules use localized labels", () => {
  assert.equal(permissionRuleLabel("inherit"), "沿用");
  assert.equal(permissionRuleLabel("confirm"), "询问");
});

test("settings summary badges expose runtime status without developer jargon", () => {
  const badges = settingsSummaryBadges({
    can_use_model: true,
    fake_model: false,
    has_nvd_api_key: false,
    approval_timeout_sec: 90,
  });
  assert.deepEqual(badges, ["模型可用", "真实模型", "NVD 未配置", "审批超时 90 秒"]);
});

test("composerRuntimeChips adds readable context chips", () => {
  assert.deepEqual(
    composerRuntimeChips(
      { profile: "default", repoPath: "/repo", domain: "example.com", autoApprove: true },
      { auto_approve: true },
    ),
    ["执行配置 default", "仓库 /repo", "域名 example.com", "本页自动确认", "会话自动确认"],
  );
});
