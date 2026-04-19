from __future__ import annotations

from langchain_core.tools import BaseTool

from digagent.config import AppSettings, get_settings
from digagent.models import SessionPermissionOverrides

from .mcp import McpRuntime
from .permissions import tool_allowed
from .project_tools import build_project_tools


def build_custom_tools(
    settings: AppSettings | None = None,
    *,
    overrides: SessionPermissionOverrides | None = None,
    mcp_runtime: McpRuntime | None = None,
) -> list[BaseTool]:
    resolved = settings or get_settings()
    tools = build_project_tools(resolved, mcp_runtime=mcp_runtime)
    return [item for item in tools if tool_allowed(item.name, overrides)]
