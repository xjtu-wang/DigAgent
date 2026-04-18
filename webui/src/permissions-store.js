export const PERMISSION_RULE_VALUES = ["inherit", "allow", "confirm", "deny"];
export const DEFAULT_RISK_TAGS = ["filesystem_write", "shell_exec", "network", "external_exploit", "export_sensitive"];

export function emptyOverrides() {
  return {
    tool_rules: {},
    mcp_server_rules: {},
    risk_tag_rules: {},
    auto_approve: false,
    budget_override: null,
  };
}

function pickRuleMap(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return {};
  }
  const cleaned = {};
  for (const [key, rule] of Object.entries(value)) {
    if (!rule || rule === "inherit") {
      continue;
    }
    if (PERMISSION_RULE_VALUES.includes(rule)) {
      cleaned[String(key)] = rule;
    }
  }
  return cleaned;
}

function pickBudget(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const budget = {};
  const fields = ["max_parallel_tools", "max_parallel_subagents", "max_tool_calls", "max_runtime_seconds"];
  for (const field of fields) {
    if (value[field] == null) {
      continue;
    }
    const numeric = Number(value[field]);
    if (Number.isFinite(numeric) && numeric >= 0) {
      budget[field] = Math.floor(numeric);
    }
  }
  return Object.keys(budget).length ? budget : null;
}

export function normalizePermissionOverrides(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return emptyOverrides();
  }
  return {
    tool_rules: pickRuleMap(value.tool_rules),
    mcp_server_rules: pickRuleMap(value.mcp_server_rules),
    risk_tag_rules: pickRuleMap(value.risk_tag_rules),
    auto_approve: Boolean(value.auto_approve),
    budget_override: pickBudget(value.budget_override),
  };
}

export function countOverrides(overrides) {
  const normalized = normalizePermissionOverrides(overrides);
  return (
    Object.keys(normalized.tool_rules).length
    + Object.keys(normalized.mcp_server_rules).length
    + Object.keys(normalized.risk_tag_rules).length
    + (normalized.auto_approve ? 1 : 0)
    + (normalized.budget_override ? 1 : 0)
  );
}

export function isOverridesEmpty(overrides) {
  return countOverrides(overrides) === 0;
}

export function setRule(overrides, bucket, key, rule) {
  const next = normalizePermissionOverrides(overrides);
  const map = { ...next[bucket] };
  if (!rule || rule === "inherit") {
    delete map[key];
  } else {
    map[key] = rule;
  }
  next[bucket] = map;
  return next;
}

export function setAutoApprove(overrides, enabled) {
  const next = normalizePermissionOverrides(overrides);
  next.auto_approve = Boolean(enabled);
  return next;
}

export function setBudget(overrides, budget) {
  const next = normalizePermissionOverrides(overrides);
  next.budget_override = pickBudget(budget);
  return next;
}
