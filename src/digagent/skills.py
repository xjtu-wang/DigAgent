from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from digagent.config import AppSettings, get_settings
from digagent.models import SkillManifest


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter")
    _, rest = text.split("---\n", 1)
    frontmatter_text, markdown = rest.split("\n---\n", 1)
    metadata = yaml.safe_load(frontmatter_text) or {}
    return metadata, markdown.strip()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        parts = re.split(r"[\s,]+", value.strip())
        return [part for part in parts if part]
    return [str(value)]


class SkillCatalog:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.skills_dir = self.settings.data_dir / "skills"

    def load_all(self) -> dict[str, SkillManifest]:
        manifests: dict[str, SkillManifest] = {}
        for skill_md in sorted(self.skills_dir.glob("*/SKILL.md")):
            manifest = self.load(skill_md.parent.name)
            manifests[manifest.name] = manifest
        return manifests

    def load(self, skill_name: str) -> SkillManifest:
        skill_dir = self.skills_dir / skill_name
        skill_md = skill_dir / "SKILL.md"
        text = skill_md.read_text(encoding="utf-8")
        metadata, markdown = _split_frontmatter(text)
        references = [
            path.relative_to(skill_dir).as_posix()
            for path in sorted((skill_dir / "references").rglob("*"))
            if path.is_file()
        ]
        agent_config_path = skill_dir / "agents" / "openai.yaml"
        agent_payload = yaml.safe_load(agent_config_path.read_text(encoding="utf-8")) if agent_config_path.exists() else {}
        interface = agent_payload.get("interface") or {}
        policy = agent_payload.get("policy") or {}
        allow_implicit_invocation = bool(policy.get("allow_implicit_invocation", False))
        return SkillManifest(
            name=str(metadata["name"]),
            description=str(metadata["description"]),
            path=str(skill_md),
            version=str(metadata.get("version")) if metadata.get("version") is not None else None,
            entrypoints=_as_list(metadata.get("entrypoints")),
            inputs=_as_list(metadata.get("inputs")),
            recommended_tools=_as_list(metadata.get("recommended_tools")),
            risk_level=str(metadata.get("risk_level")) if metadata.get("risk_level") is not None else None,
            references=references,
            agent_config_path=str(agent_config_path) if agent_config_path.exists() else None,
            agent_display_name=str(interface.get("display_name")) if interface.get("display_name") is not None else None,
            short_description=str(interface.get("short_description")) if interface.get("short_description") is not None else None,
            agent_policy=policy,
            allow_implicit_invocation=allow_implicit_invocation,
            downstream_only=skill_name.startswith("competition-") and not allow_implicit_invocation,
            markdown=markdown,
        )
