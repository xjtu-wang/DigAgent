from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from digagent.config import AppSettings

PROMPT_FILE_GLOB = "*.md"
SHARED_PROMPT_DIRNAME = "_shared"


def load_prompt_text(prompt_ref: str | Path, settings: AppSettings | None = None) -> str:
    settings = settings or _load_default_settings()
    return _load_prompt_path(_resolve_prompt_path(prompt_ref, settings))


def load_runtime_prompt(template_name: str, settings: AppSettings | None = None) -> str:
    settings = settings or _load_default_settings()
    prompt_dir = settings.config_dir / "prompts" / "runtime" / template_name
    return _load_prompt_path(prompt_dir)


def _load_default_settings() -> AppSettings:
    from digagent.config import get_settings

    return get_settings()


def _resolve_prompt_path(prompt_ref: str | Path, settings: AppSettings) -> Path:
    prompt_path = Path(prompt_ref)
    if prompt_path.is_absolute():
        return prompt_path
    return settings.workspace_root / prompt_path


def _load_prompt_path(prompt_path: Path) -> str:
    if prompt_path.is_file():
        return _read_prompt_file(prompt_path)
    if prompt_path.is_dir():
        return _read_prompt_directory(prompt_path)
    raise FileNotFoundError(f"Prompt path does not exist: {prompt_path}")


def _read_prompt_directory(prompt_dir: Path) -> str:
    sections: list[str] = []
    shared_dir = prompt_dir.parent / SHARED_PROMPT_DIRNAME
    if prompt_dir.name != SHARED_PROMPT_DIRNAME and shared_dir.is_dir():
        sections.extend(_read_prompt_files(shared_dir))
    sections.extend(_read_prompt_files(prompt_dir))
    if not sections:
        raise FileNotFoundError(f"Prompt directory does not contain any markdown fragments: {prompt_dir}")
    return "\n\n".join(sections).strip()


def _read_prompt_files(prompt_dir: Path) -> list[str]:
    files = sorted(path for path in prompt_dir.glob(PROMPT_FILE_GLOB) if path.is_file())
    return [_read_prompt_file(path) for path in files]


def _read_prompt_file(prompt_path: Path) -> str:
    text = prompt_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Prompt fragment is empty: {prompt_path}")
    return text
