from __future__ import annotations

from digagent.deepagents_runtime.capability_catalog import build_capability_catalog
from digagent.deepagents_runtime.skills import skill_source_paths
from digagent.deepagents_runtime.tools import build_custom_tools


def _tool_by_name(test_settings, name: str):
    tools = build_custom_tools(test_settings)
    return next(tool for tool in tools if tool.name == name)


def test_ctf_orchestrator_inventory_tool_ignores_injected_config(test_settings) -> None:
    tool = _tool_by_name(test_settings, "ctf_orchestrator_inventory")

    payload = tool.invoke({}, config={"configurable": {"thread_id": "sess_test"}})

    assert payload["name"] == "ctf-sandbox-orchestrator"
    assert "ctf-sandbox-orchestrator" in payload["bundled_skills"]
    assert payload["skill_count"] >= 1


def test_shell_exec_tool_still_runs_with_wrapper_config_filter(test_settings) -> None:
    tool = _tool_by_name(test_settings, "shell_exec")

    payload = tool.invoke({"command": "printf ok"}, config={"configurable": {"thread_id": "sess_test"}})

    assert payload["exit_code"] == 0
    assert payload["output"] == "ok"


def test_skills_and_mcp_catalog_expose_current_project_state(test_settings) -> None:
    catalog = build_capability_catalog(test_settings)

    assert skill_source_paths(test_settings) == ["/.agents/skills"]
    assert any(item["name"] == "digagent-runtime" for item in catalog["skills"])
    assert {item["server_id"] for item in catalog["mcp_servers"]} == {"github", "playwright", "shodan"}
