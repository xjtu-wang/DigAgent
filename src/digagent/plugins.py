from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from digagent.config import AppSettings, get_settings
from digagent.models import PluginCommandManifest, PluginManifest


class PluginCatalog:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.plugins_dir = self.settings.data_dir / "plugins"
        self._bootstrap_manifests()

    def _bootstrap_manifests(self) -> None:
        self.plugins_dir.mkdir(parents=True, exist_ok=True)
        bundled_dir = self.settings.workspace_root / "data" / "plugins"
        if bundled_dir.resolve() == self.plugins_dir.resolve() or not bundled_dir.exists():
            return
        for source in bundled_dir.iterdir():
            target = self.plugins_dir / source.name
            if not target.exists():
                shutil.copytree(source, target)

    def load_all(self) -> dict[str, PluginManifest]:
        manifests: dict[str, PluginManifest] = {}
        for manifest_path in sorted(self.plugins_dir.glob("*/.plugin/plugin.json")):
            manifest = self._load_manifest(manifest_path)
            manifests[manifest.plugin_id] = manifest
        return manifests

    def load(self, plugin_id: str) -> PluginManifest:
        manifest_path = self.plugins_dir / plugin_id / ".plugin" / "plugin.json"
        if not manifest_path.exists():
            raise KeyError(f"Unknown plugin bundle: {plugin_id}")
        return self._load_manifest(manifest_path)

    def command_manifests(self) -> list[PluginCommandManifest]:
        commands: list[PluginCommandManifest] = []
        for manifest in self.load_all().values():
            commands.extend(manifest.commands)
        return commands

    def catalog(self) -> list[dict[str, object]]:
        return [manifest.model_dump(mode="json") for manifest in self.load_all().values()]

    def _load_manifest(self, manifest_path: Path) -> PluginManifest:
        plugin_root = manifest_path.parent.parent
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        command_payloads = [self._load_command(plugin_root, path) for path in sorted((plugin_root / "commands").glob("*.yaml"))]
        payload["path"] = str(plugin_root)
        payload["references"] = self._reference_paths(plugin_root)
        payload["commands"] = command_payloads
        agent_path = plugin_root / "agents" / "openai.yaml"
        payload["agent_config_path"] = str(agent_path) if agent_path.exists() else None
        return PluginManifest.model_validate(payload)

    def _load_command(self, plugin_root: Path, path: Path) -> dict[str, object]:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        plugin_id = plugin_root.name
        payload.setdefault("plugin_id", plugin_id)
        if payload.get("script_path"):
            payload["script_path"] = str((plugin_root / payload["script_path"]).resolve())
        default_targets = dict(payload.get("default_targets") or {})
        resolved_paths: list[str] = []
        for raw_path in default_targets.get("paths", []):
            candidate = Path(str(raw_path))
            resolved = candidate.resolve() if candidate.is_absolute() else (plugin_root / candidate).resolve()
            resolved_paths.append(str(resolved))
        if resolved_paths:
            default_targets["paths"] = resolved_paths
            payload["default_targets"] = default_targets
        return payload

    def _reference_paths(self, plugin_root: Path) -> list[str]:
        reference_dir = plugin_root / "references"
        if not reference_dir.exists():
            return []
        return [
            path.relative_to(plugin_root).as_posix()
            for path in sorted(reference_dir.rglob("*"))
            if path.is_file()
        ]
