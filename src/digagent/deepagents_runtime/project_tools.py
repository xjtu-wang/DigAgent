from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_core.tools import BaseTool, StructuredTool

from digagent.config import AppSettings, get_settings
from digagent.cve import CveKnowledgeBase
from digagent.models import ToolManifest
from digagent.plugins import PluginCatalog
from digagent.storage import FileStorage
from digagent.toolsets.network import NetworkToolset

from ._paths import to_backend_path
from .mcp import McpRuntime, create_mcp_runtime


@dataclass(frozen=True)
class ProjectToolContext:
    settings: AppSettings
    plugins: PluginCatalog
    knowledge_base: CveKnowledgeBase
    storage: FileStorage
    network: NetworkToolset
    mcp: McpRuntime


def project_tools_root(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".agents" / "tools"


def load_project_tool_manifests(settings: AppSettings | None = None) -> list[ToolManifest]:
    resolved = settings or get_settings()
    root = project_tools_root(resolved)
    if not root.exists():
        return []
    manifests: list[ToolManifest] = []
    for path in sorted(root.glob("*/tool.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifest = ToolManifest.model_validate(payload)
        manifests.append(
            manifest.model_copy(
                update={"path": to_backend_path(path.parent, resolved) or str(path.parent)},
            )
        )
    return manifests


def project_tool_catalog(settings: AppSettings | None = None) -> list[dict[str, Any]]:
    return [manifest.model_dump(mode="json") for manifest in load_project_tool_manifests(settings)]


def build_project_tools(
    settings: AppSettings | None = None,
    *,
    mcp_runtime: McpRuntime | None = None,
) -> list[BaseTool]:
    resolved = settings or get_settings()
    context = ProjectToolContext(
        settings=resolved,
        plugins=PluginCatalog(resolved),
        knowledge_base=CveKnowledgeBase(resolved),
        storage=FileStorage(resolved),
        network=NetworkToolset(resolved),
        mcp=mcp_runtime or create_mcp_runtime(resolved),
    )
    return [_build_project_tool(manifest, context) for manifest in load_project_tool_manifests(resolved)]


def _build_project_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    if manifest.entry == "plugin_command":
        return _plugin_command_tool(manifest, context)
    if manifest.entry == "report_export":
        return _report_export_tool(manifest, context)
    if manifest.entry == "vuln_kb_lookup":
        return _vuln_lookup_tool(manifest, context)
    if manifest.entry == "web_search":
        return _web_search_tool(manifest, context)
    if manifest.entry == "web_fetch":
        return _web_fetch_tool(manifest, context)
    if manifest.entry == "mcp_list_servers":
        return _mcp_list_servers_tool(manifest, context)
    if manifest.entry == "mcp_list_tools":
        return _mcp_list_tools_tool(manifest, context)
    if manifest.entry == "mcp_list_resources":
        return _mcp_list_resources_tool(manifest, context)
    if manifest.entry == "mcp_read_resource":
        return _mcp_read_resource_tool(manifest, context)
    if manifest.entry == "mcp_call_tool":
        return _mcp_call_tool(manifest, context)
    raise ValueError(f"Unsupported project tool entry '{manifest.entry}' for {manifest.name}")


def _plugin_command_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    plugin_id = str(manifest.metadata.get("plugin_id") or "").strip()
    command_name = str(manifest.metadata.get("command_name") or manifest.name).strip()
    plugin = context.plugins.load(plugin_id)
    command = next((item for item in plugin.commands if item.name == command_name), None)
    if command is None or command.script_path is None:
        raise KeyError(f"Unknown plugin command mapping for {manifest.name}")

    def run(argv: list[str] | None = None) -> dict[str, Any]:
        completed = subprocess.run(
            [command.script_path, *(argv or [])],
            text=True,
            capture_output=True,
            timeout=manifest.timeout_sec or context.settings.shell_timeout_sec,
            cwd=_resolve_working_dir(manifest, context.settings),
            env=_environment(manifest),
        )
        output = (completed.stdout or "") + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
        return {
            "command_name": command.name,
            "plugin_id": plugin.plugin_id,
            "exit_code": completed.returncode,
            "output": output[: context.settings.shell_output_limit],
        }

    return StructuredTool.from_function(func=run, name=manifest.name, description=manifest.description)


def _report_export_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    def export(report_id: str, format: str = "markdown", include_content: bool = False) -> dict[str, Any]:
        report = context.storage.load_report(report_id)
        if format == "markdown":
            path = context.storage.report_markdown_path(report_id)
            payload = {
                "report_id": report_id,
                "format": format,
                "path": str(path),
                "title": report.title,
                "kind": report.kind,
            }
            if include_content:
                payload["content"] = path.read_text(encoding="utf-8")
            return payload
        if format == "pdf":
            path = context.storage.report_pdf_path(report_id)
            return {
                "report_id": report_id,
                "format": format,
                "path": str(path),
                "title": report.title,
                "kind": report.kind,
            }
        raise ValueError("Unsupported format")

    return StructuredTool.from_function(func=export, name=manifest.name, description=manifest.description)


def _vuln_lookup_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    def lookup(
        query: str = "",
        cve_id: str = "",
        cwe: str = "",
        product: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        matches = context.knowledge_base.search(
            query=query,
            cve_id=cve_id or None,
            cwe=cwe or None,
            product=product or None,
            limit=limit,
        )
        return [item.model_dump(mode="json") for item in matches]

    return StructuredTool.from_function(func=lookup, name=manifest.name, description=manifest.description)


def _web_search_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    async def run(query: str, limit: int = 5) -> dict[str, Any]:
        title, summary, raw, facts, source, _, _ = await context.network.web_search({"query": query, "limit": limit})
        return _network_payload(title, summary, raw, facts, source)

    return StructuredTool.from_function(coroutine=run, name=manifest.name, description=manifest.description)


def _web_fetch_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    async def run(url: str, method: str = "GET") -> dict[str, Any]:
        title, summary, raw, facts, source, _, _ = await context.network.web_fetch({"url": url, "method": method})
        return _network_payload(title, summary, raw, facts, source)

    return StructuredTool.from_function(coroutine=run, name=manifest.name, description=manifest.description)


def _mcp_list_servers_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    def run() -> list[str]:
        return context.mcp.list_servers()

    return StructuredTool.from_function(func=run, name=manifest.name, description=manifest.description)


def _mcp_list_tools_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    def run(server_name: str) -> list[dict[str, Any]]:
        return context.mcp.list_tools(server_name)

    return StructuredTool.from_function(func=run, name=manifest.name, description=manifest.description)


def _mcp_list_resources_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    def run(server_name: str) -> dict[str, Any]:
        return context.mcp.list_resources(server_name)

    return StructuredTool.from_function(func=run, name=manifest.name, description=manifest.description)


def _mcp_read_resource_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    def run(server_name: str, uri: str) -> dict[str, Any]:
        return context.mcp.read_resource(server_name, uri)

    return StructuredTool.from_function(func=run, name=manifest.name, description=manifest.description)


def _mcp_call_tool(manifest: ToolManifest, context: ProjectToolContext) -> BaseTool:
    def run(server_name: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        return context.mcp.call_tool(server_name, tool_name, arguments or {})

    return StructuredTool.from_function(func=run, name=manifest.name, description=manifest.description)


def _network_payload(
    title: str,
    summary: str,
    raw_output: str,
    facts: list[dict[str, Any]],
    source: dict[str, Any],
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "raw_output": raw_output,
        "facts": facts,
        "source": source,
    }


def _resolve_working_dir(manifest: ToolManifest, settings: AppSettings) -> str | None:
    if not manifest.working_dir:
        return None
    candidate = Path(manifest.working_dir)
    path = candidate if candidate.is_absolute() else settings.workspace_root / candidate
    return str(path.resolve())


def _environment(manifest: ToolManifest) -> dict[str, str] | None:
    if manifest.env_policy == "empty":
        return {}
    return None
