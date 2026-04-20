from __future__ import annotations

from digagent.config import AppSettings, get_settings
from digagent.models import AgentProfile, SessionPermissionOverrides

from .mcp import build_mcp_tools
from .permissions import allowed_tool_names
from .project_tools import build_project_tools
from .tool_policy import RuntimeToolBinding


def build_custom_tools(
    settings: AppSettings | None = None,
    *,
    allowed_domains: tuple[str, ...] = (),
) -> list:
    resolved = settings or get_settings()
    bindings = build_project_tools(resolved, allowed_domains=allowed_domains)
    return [binding.tool for binding in bindings]


async def build_agent_tools(
    profile: AgentProfile,
    *,
    settings: AppSettings | None = None,
    overrides: SessionPermissionOverrides | None = None,
) -> tuple[list[RuntimeToolBinding], frozenset[str]]:
    resolved = settings or get_settings()
    project_bindings = build_project_tools(resolved, allowed_domains=tuple(profile.network_scope))
    candidate_names = allowed_tool_names(profile, project_bindings, overrides)
    custom_bindings = [binding for binding in project_bindings if binding.name in candidate_names]
    mcp_bindings = await build_mcp_tools(
        settings=resolved,
        server_allowlist=profile.mcp_server_allowlist,
        overrides=overrides,
    )
    all_bindings = [*custom_bindings, *mcp_bindings]
    return all_bindings, allowed_tool_names(profile, all_bindings, overrides)
