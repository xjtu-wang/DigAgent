from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from digagent.config import AppSettings, get_settings
from digagent.cve import CveKnowledgeBase
from digagent.models import PluginCommandManifest, ToolManifest
from digagent.plugins import PluginCatalog
from digagent.storage import FileStorage
from digagent.storage.memory_search import MemorySearchEngine

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", "data/artifacts/blob", "webui/dist"}


@dataclass
class ToolExecutionResult:
    title: str
    summary: str
    raw_output: str
    structured_facts: list[dict[str, Any]] = field(default_factory=list)
    mime_type: str = "text/plain"
    artifact_kind: str = "stdout"
    source: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(
        self,
        settings: AppSettings | None = None,
        knowledge_base: CveKnowledgeBase | None = None,
        *,
        storage: FileStorage | None = None,
        memory_search: MemorySearchEngine | None = None,
        plugins: PluginCatalog | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.knowledge_base = knowledge_base or CveKnowledgeBase(self.settings)
        self.storage = storage or FileStorage(self.settings)
        self.memory_search_engine = memory_search or MemorySearchEngine(self.storage)
        self.plugins = plugins or PluginCatalog(self.settings)
        self.tools_dir = self.settings.data_dir / "tools"
        self._bootstrap_manifests()

    def _bootstrap_manifests(self) -> None:
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        if any(self.tools_dir.glob("*.yaml")) or any(self.tools_dir.glob("*.json")):
            return
        bundled_dir = self.settings.workspace_root / "data" / "tools"
        if bundled_dir.resolve() == self.tools_dir.resolve():
            return
        for pattern in ("*.yaml", "*.json"):
            for path in bundled_dir.glob(pattern):
                shutil.copy2(path, self.tools_dir / path.name)

    def _manifest_paths(self) -> list[Path]:
        return sorted(list(self.tools_dir.glob("*.yaml")) + list(self.tools_dir.glob("*.json")))

    def load_all(self) -> dict[str, ToolManifest]:
        manifests: dict[str, ToolManifest] = {}
        for path in self._manifest_paths():
            if path.suffix == ".json":
                payload = json.loads(path.read_text(encoding="utf-8"))
            else:
                payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            manifest = ToolManifest.model_validate(payload)
            manifests[manifest.name] = manifest
        for command in self.plugins.command_manifests():
            manifests[command.name] = ToolManifest.model_validate(command.model_dump(mode="json"))
        return manifests

    def load(self, name: str) -> ToolManifest:
        manifests = self.load_all()
        if name not in manifests:
            raise KeyError(f"Unknown tool manifest: {name}")
        return manifests[name]

    def catalog(self) -> list[dict[str, Any]]:
        return [manifest.model_dump(mode="json") for manifest in self.load_all().values()]

    def registered_action_names(self) -> set[str]:
        return set(self.load_all())

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        manifest = self.load(name)
        adapter = getattr(self, manifest.executor_adapter, None)
        if adapter is None:
            raise KeyError(f"Unknown tool adapter: {manifest.executor_adapter}")
        result = adapter({**arguments, "__tool_name": name})
        if hasattr(result, "__await__"):
            return await result
        return result

    def repo_search(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        repo_paths = [Path(item).resolve() for item in arguments.get("repo_paths", [])]
        query = str(arguments.get("query", "")).strip()
        limit = int(arguments.get("limit", 20))
        files_examined = 0
        matches: list[dict[str, Any]] = []

        for repo_path in repo_paths:
            if repo_path.is_file():
                candidates = [repo_path]
            else:
                candidates = []
                for root, dirs, files in os.walk(repo_path):
                    dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
                    for filename in files:
                        candidates.append(Path(root) / filename)
            for path in candidates:
                if any(part in SKIP_DIRS for part in path.parts):
                    continue
                path_str = path.as_posix()
                try:
                    if path.stat().st_size > 256_000:
                        continue
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                files_examined += 1
                if query:
                    for idx, line in enumerate(text.splitlines(), start=1):
                        if query.lower() in line.lower():
                            matches.append({"path": path_str, "line": idx, "text": line.strip()[:240]})
                            if len(matches) >= limit:
                                break
                else:
                    matches.append({"path": path_str, "line": 1, "text": text.splitlines()[0][:240] if text else ""})
                if len(matches) >= limit:
                    break
            if len(matches) >= limit:
                break

        title = "Repository Search Results"
        summary = f"Scanned {files_examined} files and collected {len(matches)} matches."
        raw_output = json.dumps(matches, ensure_ascii=False, indent=2)
        facts = [{"key": "files_examined", "value": files_examined}, {"key": "match_count", "value": len(matches)}]
        if query:
            facts.append({"key": "query", "value": query})
        return ToolExecutionResult(
            title=title,
            summary=summary,
            raw_output=raw_output,
            structured_facts=facts,
            source={"tool_name": "repo_search", "paths": [str(path) for path in repo_paths]},
        )

    async def web_fetch(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        url = str(arguments["url"])
        method = str(arguments.get("method", "GET")).upper()
        if method not in {"GET", "HEAD"}:
            raise ValueError(f"web_fetch only supports GET/HEAD, got {method}")
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.request(method, url)
        text = response.text[:5000]
        title_match = re.search(r"<title[^>]*>(.*?)</title>", text, re.IGNORECASE | re.DOTALL)
        title = title_match.group(1).strip() if title_match else url
        links = re.findall(r"""href=["']([^"']+)["']""", text, re.IGNORECASE)
        facts = [
            {"key": "status_code", "value": response.status_code},
            {"key": "content_type", "value": response.headers.get("content-type", "")},
            {"key": "title", "value": title},
            {"key": "link_count", "value": len(links)},
        ]
        summary = f"Fetched {url} with status {response.status_code} and extracted {len(links)} links."
        raw_output = json.dumps(
            {
                "url": str(response.url),
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "title": title,
                "links": links[:20],
                "body_excerpt": text,
            },
            ensure_ascii=False,
            indent=2,
        )
        return ToolExecutionResult(
            title=f"Web Fetch: {url}",
            summary=summary,
            raw_output=raw_output,
            structured_facts=facts,
            mime_type="application/json",
            artifact_kind="html",
            source={"tool_name": "web_fetch", "url": str(response.url)},
        )

    def shell_exec(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        command = str(arguments["command"])
        cwd = str(arguments.get("cwd") or self.settings.workspace_root)
        completed = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=self.settings.shell_timeout_sec,
        )
        output = (completed.stdout or "") + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
        output = output[: self.settings.shell_output_limit]
        summary = f"Command exited with code {completed.returncode}."
        facts = [{"key": "exit_code", "value": completed.returncode}, {"key": "cwd", "value": cwd}]
        return ToolExecutionResult(
            title=f"Shell Exec: {command}",
            summary=summary,
            raw_output=output,
            structured_facts=facts,
            source={"tool_name": "shell_exec", "path": cwd},
        )

    def vuln_kb_lookup(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        query = str(arguments.get("query") or "").strip()
        cve_id = str(arguments.get("cve_id") or "").strip() or None
        cwe = str(arguments.get("cwe") or "").strip() or None
        product = str(arguments.get("product") or "").strip() or None
        limit = int(arguments.get("limit") or 10)
        matches = self.knowledge_base.search(query=query, cve_id=cve_id, cwe=cwe, product=product, limit=limit)
        payload = [
            {
                "cve_id": item.cve_id,
                "published_at": item.published_at,
                "updated_at": item.updated_at,
                "cwes": item.cwes,
                "affected_products": item.affected_products,
                "cvss": item.cvss,
                "descriptions": item.descriptions[:2],
                "references": item.references[:5],
            }
            for item in matches
        ]
        summary = f"Matched {len(matches)} CVE records from the local vulnerability knowledge base."
        facts = [
            {"key": "match_count", "value": len(matches)},
            {"key": "query", "value": query},
        ]
        if cve_id:
            facts.append({"key": "cve_id", "value": cve_id})
        if cwe:
            facts.append({"key": "cwe", "value": cwe})
        if product:
            facts.append({"key": "product", "value": product})
        return ToolExecutionResult(
            title="Vulnerability Knowledge Base Lookup",
            summary=summary,
            raw_output=json.dumps(payload, ensure_ascii=False, indent=2),
            structured_facts=facts,
            mime_type="application/json",
            artifact_kind="file",
            source={"tool_name": "vuln_kb_lookup"},
        )

    def memory_search(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        hits = self.memory_search_engine.search(
            query=str(arguments.get("query") or ""),
            session_id=arguments.get("session_id"),
            run_id=arguments.get("run_id"),
            scope=str(arguments.get("scope") or "session"),
            sensitivity=str(arguments.get("sensitivity") or "normal"),
            limit=int(arguments.get("limit") or 5),
        )
        payload = [hit.model_dump(mode="json") for hit in hits]
        return ToolExecutionResult(
            title="Memory Search Results",
            summary=f"Matched {len(hits)} memory entries.",
            raw_output=json.dumps(payload, ensure_ascii=False, indent=2),
            structured_facts=[{"key": "match_count", "value": len(hits)}],
            mime_type="application/json",
            artifact_kind="file",
            source={"tool_name": "memory_search"},
        )

    def memory_get(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        ref = str(arguments.get("ref") or "")
        hit = self.memory_search_engine.get(
            ref,
            session_id=arguments.get("session_id"),
            sensitivity=str(arguments.get("sensitivity") or "normal"),
        )
        payload = hit.model_dump(mode="json")
        return ToolExecutionResult(
            title=f"Memory Entry: {hit.title}",
            summary=hit.summary,
            raw_output=json.dumps(payload, ensure_ascii=False, indent=2),
            structured_facts=[
                {"key": "ref", "value": hit.ref},
                {"key": "source_type", "value": hit.source_type},
                {"key": "score", "value": hit.score},
            ],
            mime_type="application/json",
            artifact_kind="file",
            source={"tool_name": "memory_get", "ref": hit.ref},
        )

    def plugin_command(self, arguments: dict[str, Any]) -> ToolExecutionResult:
        manifest = self._plugin_command_manifest(str(arguments.get("__tool_name") or ""))
        if manifest.script_path is None:
            raise RuntimeError(f"plugin command '{manifest.name}' has no script_path")
        argv = [str(item) for item in arguments.get("argv", [])]
        completed = subprocess.run(
            [manifest.script_path, *argv],
            text=True,
            capture_output=True,
            timeout=self.settings.shell_timeout_sec,
        )
        output = (completed.stdout or "") + ("\n[stderr]\n" + completed.stderr if completed.stderr else "")
        return ToolExecutionResult(
            title=f"Plugin Command: {manifest.name}",
            summary=f"Plugin command exited with code {completed.returncode}.",
            raw_output=output[: self.settings.shell_output_limit],
            structured_facts=[
                {"key": "exit_code", "value": completed.returncode},
                {"key": "plugin_id", "value": manifest.plugin_id},
            ],
            source={"tool_name": manifest.name, "plugin_id": manifest.plugin_id},
        )

    def _plugin_command_manifest(self, name: str) -> PluginCommandManifest:
        for command in self.plugins.command_manifests():
            if command.name == name:
                return command
        raise KeyError(f"Unknown plugin command: {name}")
