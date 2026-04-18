from __future__ import annotations

from pathlib import Path

from digagent.config import AppSettings, get_settings

from ._paths import ensure_text_file, to_backend_path

PROJECT_SKILL_NAME = "digagent-runtime"

PROJECT_SKILL_CONTENT = """---
name: digagent-runtime
description: DigAgent runtime conventions, including how to maintain long-term memory and how MCP/tools are wired in this project.
---

# DigAgent Runtime

## Long-Term Memory

- Long-term memory lives in `/.deepagents/AGENTS.md`.
- Session-scoped notes live in `/.deepagents/memories/`.
- When the user asks you to remember a durable project rule or preference, update those files with `edit_file` immediately.

## MCP

- Prefer MCP only when built-in deepagents filesystem and shell tools are not enough.
- Start by listing servers and tools before calling an MCP tool blindly.

## Custom Tools

- `web_search` is for finding candidate URLs.
- `web_fetch` is for fetching a concrete URL.
- `vuln_kb_lookup` is for the local CVE knowledge base.
- `run_plugin_command` is for project plugin commands that are not covered by deepagents built-ins.
"""


def project_skill_root(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".deepagents" / "skills"


def project_skill_file(settings: AppSettings | None = None) -> Path:
    return project_skill_root(settings) / PROJECT_SKILL_NAME / "SKILL.md"


def ensure_project_skill(settings: AppSettings | None = None) -> Path:
    path = project_skill_file(settings)
    ensure_text_file(path, PROJECT_SKILL_CONTENT)
    return path


def skill_source_paths(settings: AppSettings | None = None) -> list[str]:
    ensure_project_skill(settings)
    root = project_skill_root(settings)
    backend_path = to_backend_path(root, settings)
    return [backend_path] if backend_path else []
