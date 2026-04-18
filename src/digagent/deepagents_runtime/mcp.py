from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from digagent.config import AppSettings, get_settings
from digagent.mcp_client import McpStdioClient
from digagent.mcp_models import McpServerManifest, McpServerTransport


def project_mcp_path(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".mcp.json"


def ensure_project_mcp_config(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    path = project_mcp_path(resolved)
    if path.exists():
        return path
    payload = {"mcpServers": _legacy_enabled_servers(resolved)}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def merged_mcp_servers(settings: AppSettings | None = None) -> dict[str, dict[str, Any]]:
    resolved = settings or get_settings()
    ensure_project_mcp_config(resolved)
    servers: dict[str, dict[str, Any]] = {}
    for path in (Path.home() / ".mcp.json", project_mcp_path(resolved)):
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        current = payload.get("mcpServers", {})
        if isinstance(current, dict):
            servers.update({str(name): dict(value) for name, value in current.items() if isinstance(value, dict)})
    if servers:
        return servers
    return _legacy_enabled_servers(resolved)


def list_mcp_server_names(settings: AppSettings | None = None) -> list[str]:
    return sorted(merged_mcp_servers(settings))


def create_mcp_runtime(settings: AppSettings | None = None) -> "McpRuntime":
    return McpRuntime(settings or get_settings())


class McpRuntime:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._clients: dict[str, McpStdioClient] = {}

    def list_servers(self) -> list[str]:
        return list_mcp_server_names(self.settings)

    def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        return self._client(server_name).list_tools()

    def list_resources(self, server_name: str) -> dict[str, Any]:
        return self._client(server_name).request("resources/list", {})

    def read_resource(self, server_name: str, uri: str) -> dict[str, Any]:
        return self._client(server_name).request("resources/read", {"uri": uri})

    def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._client(server_name).call_tool(tool_name, arguments)

    def close(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients.clear()

    def _client(self, server_name: str) -> McpStdioClient:
        client = self._clients.get(server_name)
        if client is not None:
            return client
        client = McpStdioClient(self.settings, manifest_for_server(server_name, self.settings))
        self._clients[server_name] = client
        return client


def manifest_for_server(server_name: str, settings: AppSettings | None = None) -> McpServerManifest:
    resolved = settings or get_settings()
    payload = merged_mcp_servers(resolved).get(server_name)
    if payload is None:
        raise KeyError(f"Unknown MCP server: {server_name}")
    legacy = _legacy_metadata(resolved).get(server_name, {})
    transport = McpServerTransport(
        command=str(payload["command"]),
        args=[str(item) for item in payload.get("args", [])],
        cwd=str(payload.get("cwd") or legacy.get("cwd") or "") or None,
        env={str(key): str(value) for key, value in dict(payload.get("env") or {}).items()},
    )
    return McpServerManifest(
        server_id=server_name,
        name=str(legacy.get("name") or server_name),
        description=str(legacy.get("description") or f"MCP server {server_name}"),
        enabled=True,
        transport=transport,
        related_skills=[str(item) for item in legacy.get("related_skills", [])],
        default_risk_tags=[str(item) for item in legacy.get("default_risk_tags", [])],
        tool_risk_overrides={str(key): [str(item) for item in value] for key, value in dict(legacy.get("tool_risk_overrides", {})).items()},
    )


def _legacy_enabled_servers(settings: AppSettings) -> dict[str, dict[str, Any]]:
    servers: dict[str, dict[str, Any]] = {}
    for path in _legacy_manifest_paths(settings):
        payload = _load_yaml(path)
        if not payload.get("enabled"):
            continue
        transport = dict(payload.get("transport") or {})
        if transport.get("type") != "stdio":
            continue
        server_id = str(payload["server_id"])
        servers[server_id] = {
            "command": str(transport["command"]),
            "args": [str(item) for item in transport.get("args", [])],
            "env": {str(key): str(value) for key, value in dict(transport.get("env") or {}).items()},
            "cwd": str(transport.get("cwd") or "") or None,
        }
    return servers


def _legacy_metadata(settings: AppSettings) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for path in _legacy_manifest_paths(settings):
        payload = _load_yaml(path)
        metadata[str(payload["server_id"])] = payload
    return metadata


def _legacy_manifest_paths(settings: AppSettings) -> list[Path]:
    root = settings.config_dir / "mcp" / "servers"
    if not root.exists():
        return []
    return sorted(root.glob("*.yaml"))


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
