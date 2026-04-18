from __future__ import annotations

import subprocess
from typing import Any

from langchain_core.tools import BaseTool, tool

from digagent.config import AppSettings, get_settings
from digagent.cve import CveKnowledgeBase
from digagent.models import SessionPermissionOverrides
from digagent.plugins import PluginCatalog
from digagent.toolsets.network import NetworkToolset

from .mcp import McpRuntime, create_mcp_runtime
from .permissions import tool_allowed


def build_custom_tools(
    settings: AppSettings | None = None,
    *,
    overrides: SessionPermissionOverrides | None = None,
    mcp_runtime: McpRuntime | None = None,
) -> list[BaseTool]:
    resolved = settings or get_settings()
    network = NetworkToolset(resolved)
    knowledge_base = CveKnowledgeBase(resolved)
    plugins = PluginCatalog(resolved)
    mcp = mcp_runtime or create_mcp_runtime(resolved)
    tools = [
        _web_search_tool(network),
        _web_fetch_tool(network),
        _vuln_lookup_tool(knowledge_base),
        _plugin_tool(resolved, plugins),
        _mcp_list_servers_tool(mcp),
        _mcp_list_tools_tool(mcp),
        _mcp_list_resources_tool(mcp),
        _mcp_read_resource_tool(mcp),
        _mcp_call_tool(mcp),
    ]
    return [item for item in tools if tool_allowed(item.name, overrides)]


def _web_search_tool(network: NetworkToolset) -> BaseTool:
    @tool("web_search")
    async def web_search(query: str, limit: int = 5) -> dict[str, Any]:
        """Search the web for candidate URLs."""
        title, summary, raw, facts, source, _, _ = await network.web_search({"query": query, "limit": limit})
        return {"title": title, "summary": summary, "raw_output": raw, "facts": facts, "source": source}

    return web_search


def _web_fetch_tool(network: NetworkToolset) -> BaseTool:
    @tool("web_fetch")
    async def web_fetch(url: str, method: str = "GET") -> dict[str, Any]:
        """Fetch a concrete URL and extract structured information."""
        title, summary, raw, facts, source, _, _ = await network.web_fetch({"url": url, "method": method})
        return {"title": title, "summary": summary, "raw_output": raw, "facts": facts, "source": source}

    return web_fetch


def _vuln_lookup_tool(knowledge_base: CveKnowledgeBase) -> BaseTool:
    @tool("vuln_kb_lookup")
    def vuln_kb_lookup(
        query: str = "",
        cve_id: str = "",
        cwe: str = "",
        product: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search the local CVE knowledge base."""
        matches = knowledge_base.search(
            query=query,
            cve_id=cve_id or None,
            cwe=cwe or None,
            product=product or None,
            limit=limit,
        )
        return [item.model_dump(mode="json") for item in matches]

    return vuln_kb_lookup


def _plugin_tool(settings: AppSettings, plugins: PluginCatalog) -> BaseTool:
    @tool("run_plugin_command")
    def run_plugin_command(command_name: str, argv: list[str] | None = None) -> dict[str, Any]:
        """Run a configured DigAgent plugin command by name."""
        manifest = next((item for item in plugins.command_manifests() if item.name == command_name), None)
        if manifest is None:
            raise KeyError(f"Unknown plugin command: {command_name}")
        if manifest.script_path is None:
            raise RuntimeError(f"Plugin command '{command_name}' has no script_path")
        completed = subprocess.run(
            [manifest.script_path, *(argv or [])],
            text=True,
            capture_output=True,
            timeout=settings.shell_timeout_sec,
        )
        output = (completed.stdout or "") + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
        return {
            "command_name": command_name,
            "plugin_id": manifest.plugin_id,
            "exit_code": completed.returncode,
            "output": output[: settings.shell_output_limit],
        }

    return run_plugin_command


def _mcp_list_servers_tool(mcp: McpRuntime) -> BaseTool:
    @tool("mcp_list_servers")
    def mcp_list_servers() -> list[str]:
        """List configured MCP servers."""
        return mcp.list_servers()

    return mcp_list_servers


def _mcp_list_tools_tool(mcp: McpRuntime) -> BaseTool:
    @tool("mcp_list_tools")
    def mcp_list_tools(server_name: str) -> list[dict[str, Any]]:
        """List tools from a configured MCP server."""
        return mcp.list_tools(server_name)

    return mcp_list_tools


def _mcp_list_resources_tool(mcp: McpRuntime) -> BaseTool:
    @tool("mcp_list_resources")
    def mcp_list_resources(server_name: str) -> dict[str, Any]:
        """List resources from a configured MCP server."""
        return mcp.list_resources(server_name)

    return mcp_list_resources


def _mcp_read_resource_tool(mcp: McpRuntime) -> BaseTool:
    @tool("mcp_read_resource")
    def mcp_read_resource(server_name: str, uri: str) -> dict[str, Any]:
        """Read a resource from a configured MCP server."""
        return mcp.read_resource(server_name, uri)

    return mcp_read_resource


def _mcp_call_tool(mcp: McpRuntime) -> BaseTool:
    @tool("mcp_call_tool")
    def mcp_call_tool(server_name: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a tool from a configured MCP server."""
        return mcp.call_tool(server_name, tool_name, arguments or {})

    return mcp_call_tool
