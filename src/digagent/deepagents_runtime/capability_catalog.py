from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from digagent.config import AppSettings, get_settings
from digagent.mcp_models import McpServerManifest
from digagent.models import SkillManifest, ToolManifest

from ._paths import to_backend_path

SKILL_ROOT = Path(".agents/skills")
TOOL_ROOT = Path(".agents/tools")
MCP_ROOT = Path(".agents/mcp")


def load_skill_manifests(settings: AppSettings | None = None) -> list[SkillManifest]:
    resolved = settings or get_settings()
    root = resolved.workspace_root / SKILL_ROOT
    if not root.exists():
        return []
    manifests: list[SkillManifest] = []
    for path in sorted(root.rglob("SKILL.md")):
        manifests.append(_read_skill_manifest(path, resolved))
    return manifests


def load_tool_manifests(settings: AppSettings | None = None) -> list[ToolManifest]:
    resolved = settings or get_settings()
    root = resolved.workspace_root / TOOL_ROOT
    if not root.exists():
        return []
    manifests: list[ToolManifest] = []
    for path in sorted(root.glob("*/tool.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifest = ToolManifest.model_validate(payload)
        manifests.append(manifest.model_copy(update={"path": to_backend_path(path.parent, resolved) or str(path.parent)}))
    return manifests


def load_mcp_manifests(settings: AppSettings | None = None) -> list[McpServerManifest]:
    resolved = settings or get_settings()
    root = resolved.mcp_servers_dir or (resolved.workspace_root / MCP_ROOT)
    if not root.exists():
        return []
    manifests: list[McpServerManifest] = []
    for path in sorted(root.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        manifests.append(McpServerManifest.model_validate(payload))
    return manifests


def build_capability_catalog(settings: AppSettings | None = None) -> dict[str, list[dict[str, Any]]]:
    resolved = settings or get_settings()
    return {
        "skills": [_skill_entry(item, resolved) for item in load_skill_manifests(resolved)],
        "tools": [_tool_entry(item) for item in load_tool_manifests(resolved)],
        "mcp_servers": [_mcp_entry(item, resolved) for item in load_mcp_manifests(resolved)],
    }


def skill_source_paths(settings: AppSettings | None = None) -> list[str]:
    resolved = settings or get_settings()
    root = resolved.workspace_root / SKILL_ROOT
    backend_path = to_backend_path(root, resolved)
    return [backend_path] if backend_path and root.exists() else []


def _read_skill_manifest(path: Path, settings: AppSettings) -> SkillManifest:
    markdown = path.read_text(encoding="utf-8")
    metadata, content = _split_frontmatter(markdown)
    references = _relative_files(path.parent / "references", settings)
    return SkillManifest(
        name=str(metadata.get("name") or path.parent.name),
        description=str(metadata.get("description") or _summary_line(content) or path.parent.name),
        path=to_backend_path(path.parent, settings) or str(path.parent),
        version=_optional_text(metadata.get("version")),
        entrypoints=_string_list(metadata.get("entrypoints")),
        inputs=_string_list(metadata.get("inputs")),
        recommended_tools=_string_list(metadata.get("recommended_tools")),
        references=references,
        markdown=markdown,
    )


def _split_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        return {}, markdown
    _, _, remainder = markdown.partition("---\n")
    frontmatter, separator, content = remainder.partition("\n---\n")
    if not separator:
        return {}, markdown
    payload = yaml.safe_load(frontmatter) or {}
    return payload if isinstance(payload, dict) else {}, content


def _summary_line(content: str) -> str:
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        return line
    return ""


def _relative_files(root: Path, settings: AppSettings) -> list[str]:
    if not root.exists():
        return []
    items: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        items.append(to_backend_path(path, settings) or str(path))
    return items


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _optional_text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _skill_entry(manifest: SkillManifest, settings: AppSettings) -> dict[str, Any]:
    source_path = manifest.path
    return {
        "name": manifest.name,
        "description": manifest.description,
        "path": source_path,
        "origin": "project",
        "entrypoints": list(manifest.entrypoints),
        "recommended_tools": list(manifest.recommended_tools),
        "references": list(manifest.references),
        "issues": [],
        "source_path": source_path,
        "backend_root": to_backend_path(settings.workspace_root / SKILL_ROOT, settings),
    }


def _tool_entry(manifest: ToolManifest) -> dict[str, Any]:
    return {
        **manifest.model_dump(mode="json"),
        "origin": "project",
        "source_path": manifest.path,
        "issues": [],
    }


def _mcp_entry(manifest: McpServerManifest, settings: AppSettings) -> dict[str, Any]:
    root = settings.mcp_servers_dir or (settings.workspace_root / MCP_ROOT)
    source_path = to_backend_path(root / f"{manifest.server_id}.yaml", settings) or str(root / f"{manifest.server_id}.yaml")
    return {
        "server_id": manifest.server_id,
        "name": manifest.name,
        "description": manifest.description,
        "enabled": manifest.enabled,
        "transport": manifest.transport.type,
        "origin": "project",
        "source_path": source_path,
        "default_risk_tags": list(manifest.default_risk_tags),
        "related_skills": list(manifest.related_skills),
        "declared_tools": [tool.model_dump(mode="json") for tool in manifest.visible_advertised_tools()],
        "issues": [],
    }
