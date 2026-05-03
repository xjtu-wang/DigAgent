from __future__ import annotations

import httpx
import pytest

from digagent.deepagents_runtime.capability_catalog import build_capability_catalog
from digagent.deepagents_runtime.project_tools import _build_args_schema, build_project_tools
from digagent.deepagents_runtime.skills import skill_source_paths
from digagent.deepagents_runtime.tools import build_custom_tools
from digagent.deepagents_runtime.workspace import ensure_runtime_workspace
from digagent.models import Scope, ToolManifest
from digagent.toolsets.network import NetworkToolset


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


def test_python_exec_tool_uses_project_venv_and_workspace_cwd(test_settings, tmp_path) -> None:
    workspace = tmp_path / "agent-workspace"
    workspace.mkdir()
    tools = [binding.tool for binding in build_project_tools(test_settings, workspace_dir=workspace)]
    tool = next(item for item in tools if item.name == "python_exec")

    payload = tool.invoke(
        {"code": "import os, sys\nprint(os.getcwd())\nprint(sys.executable)"},
        config={"configurable": {"thread_id": "sess_test"}},
    )

    assert payload["exit_code"] == 0
    assert str(workspace) in payload["stdout"]
    assert ".venv" in payload["stdout"]


def test_runtime_workspace_materializes_scoped_repo_paths(test_settings) -> None:
    workspace = ensure_runtime_workspace(
        session_id="sess_scope",
        profile_name="sisyphus-default",
        scope=Scope(repo_paths=["src/digagent/models.py"]),
        settings=test_settings,
    )

    assert (workspace.workspace_dir / "src" / "digagent" / "models.py").is_file()


def test_project_tool_args_schema_inherits_callable_defaults() -> None:
    async def tool_run(*, url: str, method: str = "GET") -> dict[str, object]:
        return {"url": url, "method": method}

    manifest = ToolManifest(
        name="dummy_fetch",
        description="dummy",
        function="run",
        args_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "HEAD"]},
            },
            "required": ["url"],
        },
    )

    args_model = _build_args_schema(manifest, tool_run)
    payload = args_model(url="https://example.com")

    assert payload.method == "GET"


@pytest.mark.asyncio
async def test_web_fetch_tool_uses_default_method_when_omitted(test_settings, monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_web_fetch(self, arguments):
        captured.update(arguments)
        return "title", "summary", "raw", [], {"tool_name": "web_fetch"}, "application/json", "file"

    monkeypatch.setattr(NetworkToolset, "web_fetch", fake_web_fetch)
    tool = _tool_by_name(test_settings, "web_fetch")

    payload = await tool.ainvoke({"url": "https://example.com"}, config={"configurable": {"thread_id": "sess_test"}})

    assert payload["summary"] == "summary"
    assert captured == {"url": "https://example.com", "method": "GET"}


@pytest.mark.asyncio
async def test_network_web_fetch_treats_none_method_as_get(test_settings, monkeypatch) -> None:
    captured: dict[str, str] = {}

    async def fake_request(self, method, url, **kwargs):
        captured["method"] = method
        request = httpx.Request(method, url)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<title>Example</title><a href='https://example.com/x'>x</a>",
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    toolset = NetworkToolset(test_settings)

    _, summary, raw, facts, source, mime_type, output_kind = await toolset.web_fetch(
        {"url": "https://example.com", "method": None}
    )

    assert captured["method"] == "GET"
    assert "status 200" in summary
    assert any(item["key"] == "status_code" and item["value"] == 200 for item in facts)
    assert source["url"] == "https://example.com"
    assert mime_type == "application/json"
    assert output_kind == "html"
    assert '"status_code": 200' in raw


def test_skills_and_mcp_catalog_expose_current_project_state(test_settings) -> None:
    catalog = build_capability_catalog(test_settings)

    assert skill_source_paths(test_settings) == ["/.agents/skills"]
    assert any(item["name"] == "digagent-runtime" for item in catalog["skills"])
    assert {item["server_id"] for item in catalog["mcp_servers"]} == {"github", "playwright", "shodan"}
