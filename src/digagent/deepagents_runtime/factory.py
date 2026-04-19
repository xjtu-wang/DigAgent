from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.local_shell import LocalShellBackend
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from digagent.config import AppSettings, get_settings, resolve_profile
from digagent.models import SessionPermissionOverrides

from .mcp import McpRuntime, create_mcp_runtime
from .memory import memory_source_paths
from .permissions import interrupt_on_config
from .skills import skill_source_paths
from .subagents import build_subagents
from .tools import build_custom_tools


@dataclass
class BuiltRuntime:
    agent: object
    backend: LocalShellBackend
    checkpointer: Any
    checkpoint_context: Any | None
    checkpoint_path: str
    mcp_runtime: McpRuntime
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
    mcp_runtime = create_mcp_runtime(resolved)
    tools = build_custom_tools(resolved, overrides=overrides, mcp_runtime=mcp_runtime)
    model = ChatOpenAI(
        model=profile.model or resolved.model,
        api_key=resolved.openai_api_key,
        base_url=resolved.base_url,
        temperature=0,
    )
    backend = LocalShellBackend(
        root_dir=resolved.workspace_root,
        virtual_mode=True,
        timeout=resolved.shell_timeout_sec,
        max_output_bytes=resolved.shell_output_limit,
        inherit_env=True,
    )
    checkpoint_path = checkpoint_db_path(resolved)
    checkpoint_context = AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
    checkpointer = await checkpoint_context.__aenter__()
    agent = create_deep_agent(
        model=model,
        tools=tools,
        system_prompt=profile.system_prompt,
        skills=skill_sources or None,
        memory=memory_sources or None,
        subagents=build_subagents(tools, skill_sources, resolved, root_profile_name=profile_name),
        backend=backend,
        interrupt_on=interrupt_on_config(overrides, auto_approve=auto_approve, settings=resolved),
        checkpointer=checkpointer,
        name="digagent",
    )
    return BuiltRuntime(
        agent=agent,
        backend=backend,
        checkpointer=checkpointer,
        checkpoint_context=checkpoint_context,
        checkpoint_path=str(checkpoint_path),
        mcp_runtime=mcp_runtime,
        skill_sources=skill_sources,
        memory_sources=memory_sources,
        tool_names=[item.name for item in tools],
    )
