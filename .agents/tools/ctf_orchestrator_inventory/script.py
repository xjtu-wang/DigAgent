from __future__ import annotations

from pathlib import Path


def _relative_files(root: Path, relative: str) -> list[str]:
    base = root / relative
    if not base.exists():
        return []
    return [
        path.relative_to(root).as_posix()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    ]


def run(*, tool_context) -> dict[str, object]:
    skill_root = tool_context.settings.workspace_root / ".agents" / "skills" / "ctf-sandbox-orchestrator"
    parent = skill_root.parent
    bundled_skills = sorted(path.name for path in parent.glob("competition-*") if path.is_dir())
    if skill_root.exists():
        bundled_skills.insert(0, skill_root.name)
    return {
        "name": "ctf-sandbox-orchestrator",
        "root": str(skill_root),
        "skill_count": len(bundled_skills),
        "bundled_skills": bundled_skills,
        "references": _relative_files(skill_root, "references"),
        "agent_configs": _relative_files(skill_root, "agents"),
    }
