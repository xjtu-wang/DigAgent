from __future__ import annotations

from typing import Any

from digagent.models import AgentProfile, PermissionRule, SessionPermissionOverrides

from .project_tools import load_project_tool_manifests
from .tool_policy import RuntimeToolBinding

ALWAYS_CONFIRM_CORE_TOOLS = frozenset({"edit_file", "write_file"})
DEFAULT_CONFIRM_RISK_TAGS = frozenset({"shell_exec", "external_exploit", "open_world_recon"})
FILESYSTEM_OPERATIONS = ["read", "write"]


def allowed_tool_names(
    profile: AgentProfile,
    bindings: list[RuntimeToolBinding],
    overrides: SessionPermissionOverrides | None,
) -> frozenset[str]:
    allowed: set[str] = set()
    bound_names: set[str] = set()
    for binding in bindings:
        bound_names.add(binding.name)
        if binding.server_name is not None:
            if binding.server_name not in profile.mcp_server_allowlist:
                continue
        elif binding.name not in profile.tool_allowlist:
            continue
        if tool_denied(binding.name, binding.risk_tags, overrides):
            continue
        allowed.add(binding.name)
    for name in profile.tool_allowlist:
        if name in bound_names or tool_denied(name, (), overrides):
            continue
        allowed.add(name)
    return frozenset(allowed)


def filesystem_permissions(profile: AgentProfile) -> list[Any]:
    from deepagents import FilesystemPermission

    patterns = _filesystem_patterns(profile.filesystem_scope)
    rules = [FilesystemPermission(operations=FILESYSTEM_OPERATIONS, paths=patterns)]
    if "/**" not in patterns:
        rules.append(FilesystemPermission(operations=FILESYSTEM_OPERATIONS, paths=["/**"], mode="deny"))
    return rules


def interrupt_on_config(
    overrides: SessionPermissionOverrides | None,
    *,
    auto_approve: bool,
    settings=None,
    bindings: list[RuntimeToolBinding] | None = None,
    allowed_names: frozenset[str] | None = None,
) -> dict[str, bool] | None:
    if auto_approve:
        return None
    resolved_bindings = bindings or _manifest_bindings(settings)
    resolved_allowed = allowed_names or frozenset(default_interrupt_tools(settings))
    config = {name: True for name in ALWAYS_CONFIRM_CORE_TOOLS if name in resolved_allowed}
    for binding in resolved_bindings:
        if binding.name not in resolved_allowed:
            continue
        if tool_denied(binding.name, binding.risk_tags, overrides):
            continue
        if binding_requires_interrupt(binding, overrides):
            config[binding.name] = True
    for tool_name, rule in (overrides.tool_rules.items() if overrides else []):
        if tool_name not in resolved_allowed:
            continue
        if rule == PermissionRule.ALLOW:
            config.pop(tool_name, None)
        elif rule in {PermissionRule.CONFIRM, PermissionRule.DENY}:
            config[tool_name] = True
    return config or None


def default_interrupt_tools(settings=None) -> tuple[str, ...]:
    manifests = load_project_tool_manifests(settings)
    names = [manifest.name for manifest in manifests if manifest.interrupt_on_call]
    return tuple(sorted({*ALWAYS_CONFIRM_CORE_TOOLS, *names}))


def server_allowed(server_name: str | None, overrides: SessionPermissionOverrides | None) -> bool:
    if not server_name or overrides is None:
        return True
    return overrides.mcp_server_rules.get(server_name, PermissionRule.INHERIT) != PermissionRule.DENY


def tool_denied(
    tool_name: str,
    risk_tags: tuple[str, ...],
    overrides: SessionPermissionOverrides | None,
) -> bool:
    if overrides is None:
        return False
    if overrides.tool_rules.get(tool_name, PermissionRule.INHERIT) == PermissionRule.DENY:
        return True
    return any(overrides.risk_tag_rules.get(tag, PermissionRule.INHERIT) == PermissionRule.DENY for tag in risk_tags)


def binding_requires_interrupt(binding: RuntimeToolBinding, overrides: SessionPermissionOverrides | None) -> bool:
    if overrides is not None:
        tool_rule = overrides.tool_rules.get(binding.name, PermissionRule.INHERIT)
        if tool_rule == PermissionRule.ALLOW:
            return False
        if tool_rule == PermissionRule.CONFIRM:
            return True
        if binding.server_name:
            server_rule = overrides.mcp_server_rules.get(binding.server_name, PermissionRule.INHERIT)
            if server_rule == PermissionRule.ALLOW:
                return False
            if server_rule == PermissionRule.CONFIRM:
                return True
        if any(overrides.risk_tag_rules.get(tag, PermissionRule.INHERIT) == PermissionRule.CONFIRM for tag in binding.risk_tags):
            return True
        if any(overrides.risk_tag_rules.get(tag, PermissionRule.INHERIT) == PermissionRule.ALLOW for tag in binding.risk_tags):
            return False
    if binding.interrupt_on_call:
        return True
    return any(tag in DEFAULT_CONFIRM_RISK_TAGS for tag in binding.risk_tags)


def _filesystem_patterns(values: list[str]) -> list[str]:
    if not values:
        return ["/**"]
    patterns: list[str] = []
    for value in values:
        normalized = value.strip() or "/**"
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        patterns.append(normalized)
        if not any(char in normalized for char in "*?[]{}") and not normalized.endswith("/**"):
            patterns.append(normalized.rstrip("/") + "/**")
    deduped: list[str] = []
    for pattern in patterns:
        if pattern not in deduped:
            deduped.append(pattern)
    return deduped


def _manifest_bindings(settings=None) -> list[RuntimeToolBinding]:
    return [
        RuntimeToolBinding(
            tool=type("_Tool", (), {"name": manifest.name})(),
            risk_tags=tuple(manifest.risk_tags),
            interrupt_on_call=manifest.interrupt_on_call,
        )
        for manifest in load_project_tool_manifests(settings)
    ]
