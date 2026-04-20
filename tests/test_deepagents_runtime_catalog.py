from __future__ import annotations

from digagent.deepagents_runtime.memory import memory_source_paths
from digagent.deepagents_runtime.mcp_prompt import append_mcp_prompt_context
from digagent.deepagents_runtime.permissions import interrupt_on_config
from digagent.deepagents_runtime.project_tools import load_project_tool_manifests
from digagent.deepagents_runtime.skills import skill_source_paths
from digagent.deepagents_runtime.tools import build_custom_tools
from digagent.config import resolve_profile
from digagent.deepagents_runtime.tool_policy import RuntimeToolBinding
from digagent.runtime import TurnManager

EXPECTED_PROJECT_TOOLS = {
    "cve_fetch_online",
    "cve_search_local",
    "cve_sync_sources",
    "ctf_orchestrator_inventory",
    "report_export",
    "shell_exec",
    "vuln_kb_lookup",
    "web_fetch",
    "web_search",
}


def test_skill_and_memory_sources_use_agents_directory(test_settings) -> None:
    assert skill_source_paths(test_settings) == ["/.agents/skills"]
    assert memory_source_paths(test_settings) == ["/.agents/memory/active.md", "/.agents/memory/project.md"]


def test_project_tool_manifests_load_from_agents_directory(test_settings) -> None:
    manifests = load_project_tool_manifests(test_settings)
    names = {item.name for item in manifests}
    assert names == EXPECTED_PROJECT_TOOLS
    assert all(item.path and item.path.startswith("/.agents/tools/") for item in manifests)
    report_export = next(item for item in manifests if item.name == "report_export")
    assert report_export.interrupt_on_call is True
    assert report_export.function == "run"


def test_build_custom_tools_includes_manifest_backed_project_tools(test_settings) -> None:
    tools = build_custom_tools(test_settings)
    names = {item.name for item in tools}
    assert EXPECTED_PROJECT_TOOLS <= names
    assert "mcp_call_tool" not in names


def test_interrupt_config_uses_manifest_defaults(test_settings) -> None:
    config = interrupt_on_config(None, auto_approve=False, settings=test_settings)
    assert config is not None
    assert config["cve_sync_sources"] is True
    assert config["edit_file"] is True
    assert config["report_export"] is True
    assert config["shell_exec"] is True
    assert "vuln_kb_lookup" not in config


def test_turn_manager_catalog_exposes_agents_tools(test_settings) -> None:
    manager = TurnManager(test_settings)
    catalog = manager.catalog()
    assert catalog["memory"] == ["/.agents/memory/active.md", "/.agents/memory/project.md"]
    assert {item["name"] for item in catalog["tools"]} == EXPECTED_PROJECT_TOOLS
    assert any(item["name"] == "cve-intel" and item["path"] == "/.agents/skills/cve-intel" for item in catalog["skills"])
    assert any(item["name"] == "digagent-runtime" and item["path"] == "/.agents/skills/digagent-runtime" for item in catalog["skills"])
    assert any(item["name"] == "report-delivery" and item["path"] == "/.agents/skills/report-delivery" for item in catalog["skills"])
    servers = {item["server_id"]: item for item in catalog["mcp_servers"]}
    assert set(servers) == {"github", "playwright", "shodan"}
    assert "missing_required_env:GITHUB_PERSONAL_ACCESS_TOKEN" in servers["github"]["issues"]
    assert "missing_required_env:SHODAN_API_KEY" in servers["shodan"]["issues"]
    assert not any(issue.startswith("missing_required_env") for issue in servers["playwright"]["issues"])


def test_append_mcp_prompt_context_includes_availability_and_tools(test_settings) -> None:
    profile = resolve_profile("hephaestus-deepworker", test_settings)
    bindings = [
        RuntimeToolBinding(tool=type("_Tool", (), {"name": "playwright_browser_navigate"})(), server_name="playwright"),
        RuntimeToolBinding(tool=type("_Tool", (), {"name": "playwright_browser_snapshot"})(), server_name="playwright"),
    ]

    prompt = append_mcp_prompt_context("base prompt", profile=profile, bindings=bindings, settings=test_settings)

    assert "MCP 附录：" in prompt
    assert "github: unavailable; issues: missing_required_env:GITHUB_PERSONAL_ACCESS_TOKEN" in prompt
    assert "playwright: " in prompt
    assert "playwright_browser_navigate" in prompt
