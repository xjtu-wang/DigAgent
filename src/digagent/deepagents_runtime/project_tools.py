from __future__ import annotations

import importlib.util
import inspect
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from langchain_core.tools import StructuredTool
from langchain_core.runnables import RunnableConfig
from pydantic import Field, create_model

from digagent.config import AppSettings, get_settings
from digagent.cve_service import CveService
from digagent.models import ToolManifest
from digagent.report.exporter import ReportExporter
from digagent.storage import FileStorage
from digagent.toolsets.network import NetworkToolset

from .capability_catalog import load_tool_manifests
from .tool_policy import RuntimeToolBinding


@dataclass(frozen=True)
class ProjectToolContext:
    settings: AppSettings
    cve_service: CveService
    storage: FileStorage
    network: NetworkToolset
    report_exporter: ReportExporter
    allowed_domains: tuple[str, ...] = ()

    def ensure_url_allowed(self, url: str) -> None:
        if not self.allowed_domains:
            return
        host = (urlparse(url).hostname or "").lower()
        if not host or not any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains):
            raise PermissionError(f"URL host is outside network scope: {url}")

    def ensure_search_query_allowed(self, query: str) -> None:
        if not self.allowed_domains:
            return
        lowered = query.lower()
        if any(f"site:{domain}" in lowered for domain in self.allowed_domains):
            return
        allowed = ", ".join(self.allowed_domains)
        raise PermissionError(f"web_search is restricted to: {allowed}; include an allowed site: filter explicitly.")

    def command_cwd(self, manifest: ToolManifest) -> str:
        if not manifest.working_dir:
            return str(self.settings.workspace_root)
        raw_path = Path(manifest.working_dir)
        path = raw_path if raw_path.is_absolute() else self.settings.workspace_root / raw_path
        return str(path.resolve())

    def command_env(self, manifest: ToolManifest) -> dict[str, str]:
        if manifest.env_policy == "empty":
            return {}
        return dict(os.environ)

    def run_shell(self, manifest: ToolManifest, command: str, timeout: int | None = None) -> dict[str, Any]:
        effective_timeout = timeout or manifest.timeout_sec or self.settings.shell_timeout_sec
        completed = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=effective_timeout,
            cwd=self.command_cwd(manifest),
            env=self.command_env(manifest),
        )
        output = (completed.stdout or "") + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
        limit = self.settings.shell_output_limit
        return {
            "command": command,
            "exit_code": completed.returncode,
            "output": output[:limit],
            "truncated": len(output) > limit,
        }


def project_tools_root(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".agents" / "tools"


def load_project_tool_manifests(settings: AppSettings | None = None) -> list[ToolManifest]:
    return load_tool_manifests(settings)


def project_tool_catalog(settings: AppSettings | None = None) -> list[dict[str, Any]]:
    return [manifest.model_dump(mode="json") for manifest in load_project_tool_manifests(settings)]


def build_project_tools(
    settings: AppSettings | None = None,
    *,
    allowed_domains: tuple[str, ...] = (),
) -> list[RuntimeToolBinding]:
    resolved = settings or get_settings()
    context = ProjectToolContext(
        settings=resolved,
        cve_service=CveService(resolved),
        storage=FileStorage(resolved),
        network=NetworkToolset(resolved),
        report_exporter=ReportExporter(resolved),
        allowed_domains=tuple(domain.lower() for domain in allowed_domains if domain),
    )
    return [_build_project_tool(manifest, context) for manifest in load_project_tool_manifests(resolved)]


def _build_project_tool(manifest: ToolManifest, context: ProjectToolContext) -> RuntimeToolBinding:
    tool_dir = _tool_dir(manifest, context.settings)
    tool_function = _load_tool_function(tool_dir / "script.py", manifest.function)
    args_schema = _build_args_schema(manifest)
    if inspect.iscoroutinefunction(tool_function):
        async def _arun(config: RunnableConfig, **kwargs: Any) -> Any:
            kwargs["config"] = config
            return await _invoke_tool(tool_function, manifest, context, kwargs)

        tool = StructuredTool.from_function(
            coroutine=_arun,
            name=manifest.name,
            description=manifest.description,
            args_schema=args_schema,
        )
    else:
        def _run(config: RunnableConfig, **kwargs: Any) -> Any:
            kwargs["config"] = config
            return _invoke_sync_tool(tool_function, manifest, context, kwargs)

        tool = StructuredTool.from_function(
            func=_run,
            name=manifest.name,
            description=manifest.description,
            args_schema=args_schema,
        )
    return RuntimeToolBinding(
        tool=tool,
        risk_tags=tuple(manifest.risk_tags),
        interrupt_on_call=manifest.interrupt_on_call,
    )


def _load_tool_function(script_path: Path, symbol: str):
    spec = importlib.util.spec_from_file_location(f"digagent_project_tool_{script_path.parent.name}", script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load tool module: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        return getattr(module, symbol)
    except AttributeError as exc:
        raise AttributeError(f"Tool function '{symbol}' not found in {script_path}") from exc


def _tool_dir(manifest: ToolManifest, settings: AppSettings) -> Path:
    if manifest.path and manifest.path.startswith("/"):
        return settings.workspace_root / manifest.path.lstrip("/")
    return project_tools_root(settings) / manifest.name


async def _invoke_tool(tool_function, manifest: ToolManifest, context: ProjectToolContext, kwargs: dict[str, Any]) -> Any:
    call_kwargs = _call_kwargs(tool_function, manifest, context, kwargs)
    return await tool_function(**call_kwargs)


def _invoke_sync_tool(tool_function, manifest: ToolManifest, context: ProjectToolContext, kwargs: dict[str, Any]) -> Any:
    call_kwargs = _call_kwargs(tool_function, manifest, context, kwargs)
    result = tool_function(**call_kwargs)
    if inspect.isawaitable(result):
        raise TypeError(f"Tool '{manifest.name}' returned an awaitable from a sync entrypoint.")
    return result


def _call_kwargs(tool_function, manifest: ToolManifest, context: ProjectToolContext, kwargs: dict[str, Any]) -> dict[str, Any]:
    call_kwargs = dict(kwargs)
    parameters = inspect.signature(tool_function).parameters
    if "tool_context" in parameters:
        call_kwargs["tool_context"] = context
    if "manifest" in parameters:
        call_kwargs["manifest"] = manifest
    return call_kwargs


def _build_args_schema(manifest: ToolManifest):
    schema = manifest.args_schema or {"type": "object", "properties": {}}
    properties = dict(schema.get("properties") or {})
    required = set(schema.get("required") or [])
    fields: dict[str, tuple[Any, Any]] = {}
    for field_name, field_schema in properties.items():
        annotation = _annotation_for_schema(field_schema)
        default = ... if field_name in required else field_schema.get("default", None)
        if default is None and field_name not in required:
            annotation = annotation | None
        fields[field_name] = (annotation, Field(default=default, description=field_schema.get("description")))
    return create_model(f"{manifest.name.title().replace('_', '')}Args", **fields)


def _annotation_for_schema(schema: dict[str, Any]) -> Any:
    values = schema.get("enum")
    if isinstance(values, list) and values:
        return Literal.__getitem__(tuple(values))
    schema_type = schema.get("type")
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        item_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return list[_annotation_for_schema(item_schema)]
    if schema_type == "object":
        return dict[str, Any]
    return Any
