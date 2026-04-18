from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

from digagent.config import AppSettings, get_settings


def build_live_settings(tmp_path: Path, repo_root: Path) -> tuple[AppSettings, str]:
    current = get_settings()
    if not current.can_use_model:
        pytest.skip("real model is not configured")
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "config", workspace_root / "config", dirs_exist_ok=True)
    shutil.copytree(repo_root / ".deepagents", workspace_root / ".deepagents", dirs_exist_ok=True)
    token = f"probe-{uuid.uuid4().hex}"
    (workspace_root / "probe.txt").write_text(token, encoding="utf-8")
    settings = AppSettings(
        OPENAI_API_KEY=current.openai_api_key,
        BASE_URL=current.base_url,
        MODEL=current.model,
        DIGAGENT_USE_FAKE_MODEL=False,
        workspace_root=workspace_root,
        config_dir=workspace_root / "config",
        data_dir=workspace_root / "data",
        frontend_dist=repo_root / "webui" / "dist",
        pdf_renderer_script=repo_root / "webui" / "render-pdf.mjs",
    )
    return settings, token


def cli_env(settings: AppSettings) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "OPENAI_API_KEY": str(settings.openai_api_key or ""),
            "BASE_URL": str(settings.base_url or ""),
            "MODEL": str(settings.model or ""),
            "DIGAGENT_USE_FAKE_MODEL": "0",
            "WORKSPACE_ROOT": str(settings.workspace_root),
            "CONFIG_DIR": str(settings.config_dir),
            "DATA_DIR": str(settings.data_dir),
            "FRONTEND_DIST": str(settings.frontend_dist),
        }
    )
    return env
