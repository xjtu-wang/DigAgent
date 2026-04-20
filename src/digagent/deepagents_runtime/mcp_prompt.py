from __future__ import annotations

from digagent.config import AppSettings, get_settings
from digagent.models import AgentProfile

from .mcp import load_mcp_server_manifests
from .mcp_support import manifest_available, manifest_issues
from .tool_policy import RuntimeToolBinding


def append_mcp_prompt_context(
    base_prompt: str,
    *,
    profile: AgentProfile,
    bindings: list[RuntimeToolBinding],
    settings: AppSettings | None = None,
) -> str:
    if not profile.mcp_server_allowlist:
        return base_prompt
    resolved = settings or get_settings()
    manifests = {manifest.server_id: manifest for manifest in load_mcp_server_manifests(resolved)}
    tools_by_server: dict[str, list[str]] = {}
    for binding in bindings:
        if binding.server_name is None:
            continue
        tools_by_server.setdefault(binding.server_name, []).append(binding.name)
    lines = [
        "MCP 附录：",
        "- 只把下面列出的 `server_id` 当作 MCP 服务标识，不要把 skill 名、agent 名或 profile 名当作 `server_id`。",
        "- 调用 MCP 时优先使用当前实际可见的前缀化工具名。",
    ]
    for server_id in profile.mcp_server_allowlist:
        manifest = manifests.get(server_id)
        if manifest is None:
            lines.append(f"- {server_id}: unavailable; issues: missing_manifest; tools: none")
            continue
        issues = manifest_issues(manifest, resolved)
        status = "available" if manifest_available(manifest, resolved) else "unavailable"
        tools = ", ".join(sorted(tools_by_server.get(server_id, []))) or "none"
        issue_text = ", ".join(issues) if issues else "none"
        lines.append(f"- {server_id}: {status}; issues: {issue_text}; tools: {tools}")
    return base_prompt.strip() + "\n\n" + "\n".join(lines)
