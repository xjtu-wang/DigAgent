from __future__ import annotations

import shutil
from pathlib import Path

from digagent.config import AppSettings
from digagent.mcp_models import McpServerManifest


def manifest_issues(manifest: McpServerManifest, settings: AppSettings | None = None) -> list[str]:
    issues = [f"missing_required_env:{name}" for name in manifest.missing_required_env()]
    if not _command_exists(manifest.transport.command, settings):
        issues.append(f"missing_command:{manifest.transport.command}")
    return issues


def manifest_available(manifest: McpServerManifest, settings: AppSettings | None = None) -> bool:
    return manifest.enabled and not manifest_issues(manifest, settings)


def _command_exists(command: str, settings: AppSettings | None = None) -> bool:
    if Path(command).is_absolute():
        return Path(command).exists()
    if "/" in command:
        resolved = (settings.workspace_root if settings else Path.cwd()) / command
        return resolved.exists()
    return shutil.which(command) is not None
