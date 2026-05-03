from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from digagent.config import AppSettings, get_settings
from digagent.models import Scope

WORKSPACES_DIR = "workspaces"
SESSION_WORKSPACE = "session"
MAX_SEEDED_FILE_BYTES = 1_000_000
EXCLUDED_SEED_NAMES = frozenset({".git", ".venv", "data", "webui", "node_modules", ".codex-tasks"})
EXCLUDED_SEED_SUFFIXES = frozenset({".zip", ".sqlite", ".sqlite-shm", ".sqlite-wal"})


@dataclass(frozen=True)
class RuntimeWorkspace:
    session_id: str
    profile_name: str
    workspace_dir: Path
    attachments_dir: Path
    backend_path: str
    attachment_paths: tuple[str, ...]
    scope: Scope


def ensure_runtime_workspace(
    *,
    session_id: str,
    profile_name: str,
    scope: Scope,
    settings: AppSettings | None = None,
) -> RuntimeWorkspace:
    resolved = settings or get_settings()
    workspace_dir = agent_workspace_dir(resolved, session_id, profile_name)
    attachments_dir = workspace_dir / "attachments"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir.mkdir(parents=True, exist_ok=True)
    _mirror_agents_dir(resolved, workspace_dir)
    _seed_workspace_inputs(resolved, workspace_dir)
    _materialize_scope_paths(resolved, workspace_dir, scope)
    attachment_paths = tuple(_attachment_backend_paths(attachments_dir))
    return RuntimeWorkspace(
        session_id=session_id,
        profile_name=profile_name,
        workspace_dir=workspace_dir,
        attachments_dir=attachments_dir,
        backend_path="/",
        attachment_paths=attachment_paths,
        scope=scope,
    )


def agent_workspace_dir(settings: AppSettings, session_id: str, profile_name: str) -> Path:
    safe_profile = _safe_segment(profile_name)
    return settings.data_dir / WORKSPACES_DIR / session_id / "agents" / safe_profile


def turn_attachments_dir(settings: AppSettings, session_id: str, turn_id: str = SESSION_WORKSPACE) -> Path:
    return settings.data_dir / WORKSPACES_DIR / session_id / "turns" / _safe_segment(turn_id) / "attachments"


def workspace_prompt_context(workspace: RuntimeWorkspace) -> str:
    lines = [
        "",
        "## DigAgent Workspace Context",
        "",
        f"- Active workspace root: `{workspace.backend_path}`",
        f"- Session id: `{workspace.session_id}`",
        f"- Agent profile: `{workspace.profile_name}`",
    ]
    lines.extend(_scope_lines(workspace.scope))
    lines.extend(_attachment_lines(workspace.attachment_paths))
    return "\n".join(lines).strip()


def _mirror_agents_dir(settings: AppSettings, workspace_dir: Path) -> None:
    source = settings.workspace_root / ".agents"
    target = workspace_dir / ".agents"
    if not source.exists():
        return
    shutil.copytree(source, target, dirs_exist_ok=True)


def _seed_workspace_inputs(settings: AppSettings, workspace_dir: Path) -> None:
    for source in sorted(settings.workspace_root.iterdir()):
        if not _should_seed_path(source):
            continue
        target = workspace_dir / source.name
        if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
            continue
        shutil.copy2(source, target)


def _materialize_scope_paths(settings: AppSettings, workspace_dir: Path, scope: Scope) -> None:
    for value in scope.repo_paths:
        source = _resolve_scope_path(settings, value)
        relative = source.relative_to(settings.workspace_root.resolve())
        target = workspace_dir / relative
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _resolve_scope_path(settings: AppSettings, value: str) -> Path:
    raw_path = Path(str(value).lstrip("/"))
    candidate = raw_path if raw_path.is_absolute() else settings.workspace_root / raw_path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(settings.workspace_root.resolve())
    except ValueError as exc:
        raise ValueError(f"Scoped repo path is outside workspace root: {value}") from exc
    if not resolved.exists():
        raise FileNotFoundError(f"Scoped repo path does not exist: {value}")
    return resolved


def _should_seed_path(path: Path) -> bool:
    if path.name in EXCLUDED_SEED_NAMES:
        return False
    if path.suffix in EXCLUDED_SEED_SUFFIXES:
        return False
    if not path.is_file():
        return False
    return path.stat().st_size <= MAX_SEEDED_FILE_BYTES


def _attachment_backend_paths(attachments_dir: Path) -> list[str]:
    if not attachments_dir.exists():
        return []
    paths: list[str] = []
    for path in sorted(attachments_dir.iterdir()):
        if path.is_file():
            paths.append(f"/attachments/{path.name}")
    return paths


def _scope_lines(scope: Scope) -> list[str]:
    lines: list[str] = []
    if scope.repo_paths:
        lines.append("- Scoped repo paths: " + ", ".join(f"`{item}`" for item in scope.repo_paths))
    if scope.allowed_domains:
        lines.append("- Scoped domains: " + ", ".join(f"`{item}`" for item in scope.allowed_domains))
    if scope.artifacts:
        lines.append("- Scoped artifacts: " + ", ".join(f"`{item}`" for item in scope.artifacts))
    return lines


def _attachment_lines(paths: tuple[str, ...]) -> list[str]:
    if not paths:
        return ["- Attachments: none"]
    return ["- Attachments: " + ", ".join(f"`{item}`" for item in paths)]


def _safe_segment(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)
    return safe or "default"
