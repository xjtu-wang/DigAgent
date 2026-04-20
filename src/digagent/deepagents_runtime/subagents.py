from __future__ import annotations

from deepagents import SubAgent
from langchain_openai import ChatOpenAI

from digagent.config import AppSettings, get_settings, load_profiles
from digagent.models import SessionPermissionOverrides

from .mcp_prompt import append_mcp_prompt_context
from .permissions import filesystem_permissions, interrupt_on_config
from .tool_policy import ToolAllowlistMiddleware
from .tools import build_agent_tools


def configured_agent_profiles(settings: AppSettings | None = None) -> tuple[str, ...]:
    resolved = settings or get_settings()
    return tuple(sorted(load_profiles(resolved)))


async def build_subagents(
    *,
    settings: AppSettings | None = None,
    root_profile_name: str,
    skill_sources: list[str],
    overrides: SessionPermissionOverrides | None,
    auto_approve: bool,
) -> list[SubAgent]:
    resolved = settings or get_settings()
    profiles = load_profiles(resolved)
    root_profile = profiles[root_profile_name]
    specs: list[SubAgent] = []
    for name in root_profile.subagents:
        profile = profiles[name]
        bindings, allowed_names = await build_agent_tools(profile, settings=resolved, overrides=overrides)
        system_prompt = append_mcp_prompt_context(
            profile.system_prompt,
            profile=profile,
            bindings=bindings,
            settings=resolved,
        )
        spec: SubAgent = {
            "name": name,
            "description": profile.description,
            "system_prompt": system_prompt,
            "tools": [binding.tool for binding in bindings],
            "permissions": filesystem_permissions(profile),
            "middleware": [ToolAllowlistMiddleware(allowed=allowed_names)],
        }
        if skill_sources:
            spec["skills"] = skill_sources
        interrupt_on = interrupt_on_config(
            overrides,
            auto_approve=auto_approve,
            settings=resolved,
            bindings=bindings,
            allowed_names=allowed_names,
        )
        if interrupt_on is not None:
            spec["interrupt_on"] = interrupt_on
        if profile.model:
            spec["model"] = ChatOpenAI(
                model=profile.model,
                api_key=resolved.openai_api_key,
                base_url=resolved.base_url,
                temperature=0,
            )
        specs.append(spec)
    return specs
