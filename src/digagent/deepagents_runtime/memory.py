from __future__ import annotations

from pathlib import Path

from digagent.config import AppSettings, get_settings

from ._paths import ensure_text_file, to_backend_path

PROJECT_MEMORY_FILES = {
    "project.md": """# DigAgent Project Memory

- DigAgent packages project-facing runtime capabilities through `/.agents/skills`, `/.agents/tools`, and `/.agents/memory`.
- Temporary memory stays with session records for interruption recovery and should only be promoted here when it becomes durable.
- Project-specific capabilities should prefer manifest-backed tools instead of ad hoc shell glue.
"""
}


def project_memory_root(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".agents" / "memory"


def ensure_project_memory(settings: AppSettings | None = None) -> list[Path]:
    root = project_memory_root(settings)
    paths: list[Path] = []
    for name, content in PROJECT_MEMORY_FILES.items():
        path = root / name
        ensure_text_file(path, content)
        paths.append(path)
    return paths


def memory_source_paths(
    settings: AppSettings | None = None,
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> list[str]:
    resolved = settings or get_settings()
    ensure_project_memory(resolved)
    candidates = sorted(project_memory_root(resolved).glob("*.md"))
    return [path for item in candidates if (path := to_backend_path(item, resolved))]
