import test from "node:test";
import assert from "node:assert/strict";
import {
  countOverrides,
  emptyOverrides,
  isOverridesEmpty,
  normalizePermissionOverrides,
  setAutoApprove,
  setBudget,
  setRule,
} from "./permissions-store.js";

test("emptyOverrides is fully empty", () => {
  const overrides = emptyOverrides();
  assert.equal(isOverridesEmpty(overrides), true);
  assert.equal(countOverrides(overrides), 0);
});

test("normalizePermissionOverrides strips inherit rules and invalid values", () => {
  const overrides = normalizePermissionOverrides({
    tool_rules: { web_fetch: "deny", shell_exec: "inherit", junk: "banana" },
    mcp_server_rules: { "kali-local": "allow" },
    risk_tag_rules: null,
    auto_approve: true,
    budget_override: { max_tool_calls: 10, max_runtime_seconds: "120" },
  });
  assert.deepEqual(overrides.tool_rules, { web_fetch: "deny" });
  assert.deepEqual(overrides.mcp_server_rules, { "kali-local": "allow" });
  assert.deepEqual(overrides.risk_tag_rules, {});
  assert.equal(overrides.auto_approve, true);
  assert.deepEqual(overrides.budget_override, { max_tool_calls: 10, max_runtime_seconds: 120 });
});

test("setRule inherit removes the entry, non-inherit overwrites", () => {
  const base = setRule(emptyOverrides(), "tool_rules", "web_fetch", "deny");
  assert.deepEqual(base.tool_rules, { web_fetch: "deny" });
  const flipped = setRule(base, "tool_rules", "web_fetch", "allow");
  assert.deepEqual(flipped.tool_rules, { web_fetch: "allow" });
  const cleared = setRule(flipped, "tool_rules", "web_fetch", "inherit");
  assert.deepEqual(cleared.tool_rules, {});
});

test("countOverrides counts every rule and flag", () => {
  let overrides = emptyOverrides();
  overrides = setRule(overrides, "tool_rules", "shell_exec", "confirm");
  overrides = setRule(overrides, "risk_tag_rules", "network", "allow");
  overrides = setAutoApprove(overrides, true);
  overrides = setBudget(overrides, { max_tool_calls: 5 });
  assert.equal(countOverrides(overrides), 4);
});

test("setBudget(null) clears the override", () => {
  const withBudget = setBudget(emptyOverrides(), { max_tool_calls: 3 });
  const cleared = setBudget(withBudget, null);
  assert.equal(cleared.budget_override, null);
});
