#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def _relative_files(root: Path, relative: str) -> list[str]:
    base = root / relative
    if not base.exists():
        return []
    return [
        path.relative_to(root).as_posix()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    ]


def main() -> None:
    plugin_root = Path(__file__).resolve().parents[1]
    manifest_path = plugin_root / ".plugin" / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = {
        "plugin_id": manifest["plugin_id"],
        "name": manifest["name"],
        "version": manifest.get("version"),
        "plugin_root": str(plugin_root),
        "bundled_skills": manifest.get("bundled_skills", []),
        "commands": sorted(path.stem for path in (plugin_root / "commands").glob("*.yaml")),
        "references": _relative_files(plugin_root, "references"),
        "agent_configs": _relative_files(plugin_root, "agents"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
