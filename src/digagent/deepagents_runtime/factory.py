from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from digagent.config import AppSettings, get_settings, resolve_profile
from digagent.models import SessionPermissionOverrides

from .memory import memory_source_paths
from .mcp_prompt import append_mcp_prompt_context
from .permissions import filesystem_permissions, interrupt_on_config
from .skills import skill_source_paths
from .subagents import build_subagents
from .tool_policy import ToolAllowlistMiddleware
from .tools import build_agent_tools


@dataclass
class BuiltRuntime:
    agent: object
    backend: FilesystemBackend
    checkpointer: Any
    checkpoint_context: Any | None
    checkpoint_path: str
    mcp_runtime: Any | None
    skill_sources: list[str]
    memory_sources: list[str]
    tool_names: list[str]


def checkpoint_db_path(settings: AppSettings) -> Path:
    path = settings.data_dir / "langgraph-checkpoints.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


async def build_runtime(
    *,
    session_id: str,
    profile_name: str,
    auto_approve: bool,
    overrides: SessionPermissionOverrides | None = None,
    settings: AppSettings | None = None,
) -> BuiltRuntime:
    resolved = settings or get_settings()
    profile = resolve_profile(profile_name, resolved)
    skill_sources = skill_source_paths(resolved)
    memory_sources = memory_source_paths(resolved, session_id=session_id)
    tool_bindings, allowed_names = await build_agent_tools(profile, settings=resolved, overrides=overrides)
    system_prompt = append_mcp_prompt_context(
        profile.system_prompt,
        profile=profile,
        bindings=tool_bindings,
        settings=resolved,
    )
    model = ChatOpenAI(
        model=profile.model or resolved.model,
        api_key=resolved.openai_api_key,
        base_url=resolved.base_url,
        temperature=0,
    )
    backend = FilesystemBackend(
        root_dir=resolved.workspace_root,
        virtual_mode=True,
    )
    checkpoint_path = checkpoint_db_path(resolved)
    checkpoint_context = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    checkpointer = await checkpoint_context.__aenter__()
    agent = create_deep_agent(
        model=model,
        tools=[binding.tool for binding in tool_bindings],
        system_prompt=system_prompt,
        skills=skill_sources or None,
        memory=memory_sources or None,
        permissions=filesystem_permissions(profile),
        subagents=await build_subagents(
            settings=resolved,
            root_profile_name=profile_name,
            skill_sources=skill_sources,
            overrides=overrides,
            auto_approve=auto_approve,
        ),
        backend=backend,
        interrupt_on=interrupt_on_config(
            overrides,
            auto_approve=auto_approve,
            settings=resolved,
            bindings=tool_bindings,
            allowed_names=allowed_names,
        ),
        middleware=[ToolAllowlistMiddleware(allowed=allowed_names)],
        checkpointer=checkpointer,
        name="digagent",
    )
    return BuiltRuntime(
        agent=agent,
        backend=backend,
        checkpointer=checkpointer,
        checkpoint_context=checkpoint_context,
        checkpoint_path=str(checkpoint_path),
        mcp_runtime=None,
        skill_sources=skill_sources,
        memory_sources=memory_sources,
        tool_names=sorted(allowed_names),
    )
