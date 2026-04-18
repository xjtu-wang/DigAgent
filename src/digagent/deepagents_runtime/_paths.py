from __future__ import annotations

from pathlib import Path

from digagent.config import AppSettings, get_settings


def ensure_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    path.write_text(content, encoding="utf-8")


def to_backend_path(path: Path, settings: AppSettings | None = None) -> str | None:
    resolved = settings or get_settings()
    try:
        relative = path.resolve().relative_to(resolved.workspace_root.resolve())
    except ValueError:
        return None
    return "/" + relative.as_posix()
