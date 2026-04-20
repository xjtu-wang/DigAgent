from __future__ import annotations

from pathlib import Path

from digagent.config import AppSettings, get_settings

from .capability_catalog import skill_source_paths as catalog_skill_source_paths
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
- Long-term memory summaries live under `/.agents/memory/*.md`.
- Detailed long-term memory archives live under `/.agents/memory/archive/*.md`.

## Tooling

- Prefer project tools when the capability already exists in `/.agents/tools`.
- `ctf_orchestrator_inventory` inspects the bundled CTF sandbox orchestrator assets.
- `vuln_kb_lookup` searches the local CVE knowledge base.
- `report_export` exports either an existing DigAgent report or ad hoc markdown into a downloadable artifact.

## MCP

- Prefer MCP only when built-in deepagents filesystem/shell tools and project tools are not enough.
- Start by listing servers and tools before calling an MCP tool blindly.
""",
    "memory-curation": """---
name: memory-curation
description: Manage OpenClaw-style short-term and long-term memory, keeping durable knowledge in .agents/memory/.
---

# Memory Curation

## Memory Layers

- Temporary notes stay in session records so turns can resume after interruption.
- Long-term memory lives under `/.agents/memory/`.
- Keep always-loaded summaries in `/.agents/memory/active.md`.
- Store detailed long-term knowledge in `/.agents/memory/archive/*.md`.
- Do not store secrets, access tokens, or noisy transient chat history in long-term memory.
""",
    "report-delivery": """---
name: report-delivery
description: Guide DigAgent to export markdown or PDF deliverables when the user asks for downloads or the response is too large for chat.
recommended_tools:
  - report_export
---

# Report Delivery

- Prefer `markdown` by default when the user did not specify a format.
- Use `pdf` when the user explicitly asks for it or the task clearly calls for a formal report artifact.
- Export an existing report when one already exists; otherwise export finalized markdown directly.
- Always return the download link from the tool output.
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
    return catalog_skill_source_paths(settings)
