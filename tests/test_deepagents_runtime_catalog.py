from __future__ import annotations

from digagent.deepagents_runtime.memory import memory_source_paths
from digagent.deepagents_runtime.permissions import interrupt_on_config
from digagent.deepagents_runtime.project_tools import load_project_tool_manifests
from digagent.deepagents_runtime.skills import skill_source_paths
from digagent.deepagents_runtime.tools import build_custom_tools
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
    assert memory_source_paths(test_settings) == ["/.agents/memory/project.md"]


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
    assert catalog["memory"] == ["/.agents/memory/project.md"]
    assert {item["name"] for item in catalog["tools"]} == EXPECTED_PROJECT_TOOLS
    assert any(item["name"] == "cve-intel" and item["path"] == "/.agents/skills/cve-intel" for item in catalog["skills"])
    assert any(item["name"] == "digagent-runtime" and item["path"] == "/.agents/skills/digagent-runtime" for item in catalog["skills"])
    assert {item["server_id"] for item in catalog["mcp_servers"]} == {"fixture-mcp", "kali-local", "playwright-local"}
