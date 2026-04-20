from __future__ import annotations

from pathlib import Path

from digagent.config import AppSettings, get_settings
from digagent.mcp_models import McpServerManifest
from digagent.models import SessionPermissionOverrides

from .capability_catalog import load_mcp_manifests
from .permissions import server_allowed
from .tool_policy import RuntimeToolBinding


def project_mcp_root(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.mcp_servers_dir or (resolved.workspace_root / ".agents" / "mcp")


def load_mcp_server_manifests(settings: AppSettings | None = None) -> list[McpServerManifest]:
    return load_mcp_manifests(settings)


def list_mcp_server_names(settings: AppSettings | None = None) -> list[str]:
    return [manifest.server_id for manifest in load_mcp_server_manifests(settings)]


async def build_mcp_tools(
    *,
    settings: AppSettings | None = None,
    server_allowlist: list[str],
    tool_allowlist: frozenset[str],
    overrides: SessionPermissionOverrides | None,
) -> list[RuntimeToolBinding]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    resolved = settings or get_settings()
    manifests = {
        manifest.server_id: manifest
        for manifest in load_mcp_server_manifests(resolved)
        if manifest.enabled and manifest.server_id in server_allowlist and server_allowed(manifest.server_id, overrides)
    }
    if not manifests or not tool_allowlist:
        return []
    client = MultiServerMCPClient({name: _connection_config(manifest) for name, manifest in manifests.items()}, tool_name_prefix=True)
    tools = await client.get_tools()
    bindings: list[RuntimeToolBinding] = []
    for tool in tools:
        server_name, raw_name = _resolve_mcp_tool_name(tool.name, manifests)
        if tool.name not in tool_allowlist:
            continue
        manifest = manifests[server_name]
        bindings.append(
            RuntimeToolBinding(
                tool=tool,
                risk_tags=tuple(manifest.tool_risk_tags(raw_name)),
                source="mcp",
                server_name=server_name,
            )
        )
    return bindings


def _connection_config(manifest: McpServerManifest) -> dict[str, object]:
    transport = manifest.transport
    payload: dict[str, object] = {
        "transport": transport.type,
        "command": transport.command,
        "args": list(transport.args),
    }
    if transport.cwd:
        payload["cwd"] = transport.cwd
    if transport.env:
        payload["env"] = dict(transport.env)
    return payload


def _resolve_mcp_tool_name(tool_name: str, manifests: dict[str, McpServerManifest]) -> tuple[str, str]:
    for server_name in manifests:
        prefix = f"{server_name}_"
        if tool_name.startswith(prefix):
            return server_name, tool_name[len(prefix) :]
    if "_" in tool_name:
        server_name, raw_name = tool_name.split("_", 1)
        return server_name, raw_name
    raise KeyError(f"Unable to map MCP tool '{tool_name}' to a configured server.")
