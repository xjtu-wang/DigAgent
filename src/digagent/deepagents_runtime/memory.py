from __future__ import annotations

from pathlib import Path

from digagent.config import AppSettings, get_settings

from ._paths import ensure_text_file, to_backend_path

PROJECT_MEMORY_CONTENT = """# DigAgent Project Memory

- This file is loaded through deepagents `memory=[...]`.
- Keep durable project conventions and user-approved preferences here.
- Do not store secrets, tokens, or transient chat noise here.
"""

SESSION_MEMORY_TEMPLATE = "session-{session_id}.md"
TURN_MEMORY_TEMPLATE = "turn-{turn_id}.md"


def project_agents_path(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".deepagents" / "AGENTS.md"


def session_memory_path(session_id: str, settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".deepagents" / "memories" / SESSION_MEMORY_TEMPLATE.format(session_id=session_id)


def turn_memory_path(turn_id: str, settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".deepagents" / "memories" / TURN_MEMORY_TEMPLATE.format(turn_id=turn_id)


def ensure_project_memory(settings: AppSettings | None = None) -> Path:
    path = project_agents_path(settings)
    ensure_text_file(path, PROJECT_MEMORY_CONTENT)
    return path


def memory_source_paths(
    settings: AppSettings | None = None,
    *,
    session_id: str | None = None,
    turn_id: str | None = None,
) -> list[str]:
    resolved = settings or get_settings()
    ensure_project_memory(resolved)
    candidates = [resolved.workspace_root / "AGENTS.md", project_agents_path(resolved)]
    legacy_path = resolved.data_dir / "memory" / "MEMORY.md"
    if legacy_path.exists():
        candidates.append(legacy_path)
    if session_id:
        candidates.append(session_memory_path(session_id, resolved))
    if turn_id:
        candidates.append(turn_memory_path(turn_id, resolved))
    return [path for item in candidates if (path := to_backend_path(item, resolved))]
