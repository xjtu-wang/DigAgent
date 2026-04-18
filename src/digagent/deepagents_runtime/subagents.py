from __future__ import annotations

from typing import Any

from deepagents import SubAgent
from langchain_openai import ChatOpenAI

from digagent.config import AppSettings, get_settings, load_profiles

DEFAULT_SUBAGENT_PROFILES = (
    "hephaestus-deepworker",
    "memory-curator",
    "report-writer",
)


def build_subagents(
    tools: list[Any],
    skill_sources: list[str],
    settings: AppSettings | None = None,
    *,
    root_profile_name: str,
) -> list[SubAgent]:
    resolved = settings or get_settings()
    profiles = load_profiles(resolved)
    specs: list[SubAgent] = []
    for name in DEFAULT_SUBAGENT_PROFILES:
        if name == root_profile_name or name not in profiles:
            continue
        profile = profiles[name]
        spec: SubAgent = {
            "name": name,
            "description": profile.description,
            "system_prompt": profile.system_prompt,
            "tools": tools,
            "skills": skill_sources,
        }
        if profile.model:
            spec["model"] = ChatOpenAI(
                model=profile.model,
                api_key=resolved.openai_api_key,
                base_url=resolved.base_url,
                temperature=0,
            )
        specs.append(spec)
    return specs
