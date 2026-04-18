from __future__ import annotations

from digagent.models import PermissionRule, SessionPermissionOverrides

DEFAULT_INTERRUPT_TOOLS = (
    "edit_file",
    "write_file",
    "execute",
    "mcp_call_tool",
    "run_plugin_command",
)


def interrupt_on_config(overrides: SessionPermissionOverrides | None, *, auto_approve: bool) -> dict[str, bool] | None:
    if auto_approve:
        return None
    config = {name: True for name in DEFAULT_INTERRUPT_TOOLS}
    if overrides is None:
        return config
    for tool_name, rule in overrides.tool_rules.items():
        if rule == PermissionRule.ALLOW:
            config.pop(tool_name, None)
        elif rule == PermissionRule.CONFIRM:
            config[tool_name] = True
        elif rule == PermissionRule.DENY:
            config[tool_name] = True
    return config


def tool_allowed(tool_name: str, overrides: SessionPermissionOverrides | None) -> bool:
    if overrides is None:
        return True
    rule = overrides.tool_rules.get(tool_name, PermissionRule.INHERIT)
    return rule != PermissionRule.DENY
