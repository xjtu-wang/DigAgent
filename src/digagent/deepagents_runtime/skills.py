from __future__ import annotations

from pathlib import Path

from digagent.config import AppSettings, get_settings

from ._paths import ensure_text_file, to_backend_path

PROJECT_SKILLS = {
    "digagent-runtime": """---
name: digagent-runtime
description: DigAgent runtime conventions for .agents-based skills, tools, and memory promotion.
---

# DigAgent Runtime

## Layout

- Project skills live under `/.agents/skills/`.
- Project tools are declared under `/.agents/tools/*/tool.yaml`.
- Long-term memory lives under `/.agents/memory/*.md`.

## Tooling

- Prefer project tools when the capability already exists in `/.agents/tools`.
- `ctf_orchestrator_inventory` inspects the bundled CTF sandbox orchestrator assets.
- `vuln_kb_lookup` searches the local CVE knowledge base.
- `report_export` exports an existing DigAgent report artifact.

## MCP

- Prefer MCP only when built-in deepagents filesystem/shell tools and project tools are not enough.
- Start by listing servers and tools before calling an MCP tool blindly.
""",
    "memory-curation": """---
name: memory-curation
description: Curate durable user and project memory by promoting stable facts from session records into .agents memory files.
---

# Memory Curation

## Promotion Rules

- Temporary notes stay in session records so turns can resume after interruption.
- Promote durable user preferences, recurring repo conventions, and other high-value facts into `/.agents/memory/*.md`.
- Do not store secrets, access tokens, or noisy transient chat history in long-term memory.
""",
}


def project_skill_root(settings: AppSettings | None = None) -> Path:
    resolved = settings or get_settings()
    return resolved.workspace_root / ".agents" / "skills"


def ensure_project_skills(settings: AppSettings | None = None) -> list[Path]:
    root = project_skill_root(settings)
    paths: list[Path] = []
    for name, content in PROJECT_SKILLS.items():
        path = root / name / "SKILL.md"
        ensure_text_file(path, content)
        paths.append(path)
    return paths


def skill_source_paths(settings: AppSettings | None = None) -> list[str]:
    ensure_project_skills(settings)
    root = project_skill_root(settings)
    backend_path = to_backend_path(root, settings)
    return [backend_path] if backend_path else []
