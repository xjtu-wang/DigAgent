from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.runtime_import_stubs import load_runtime_api

@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture()
def test_settings(tmp_path: Path, repo_root: Path):
    from digagent.config import AppSettings

    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "data" / "skills", data_dir / "skills")
    return AppSettings(
        OPENAI_API_KEY="test-key",
        BASE_URL="https://example.invalid/v1",
        MODEL="fake-model",
        DIGAGENT_USE_FAKE_MODEL=False,
        workspace_root=repo_root,
        config_dir=repo_root / "config",
        data_dir=data_dir,
        frontend_dist=repo_root / "webui" / "dist",
        pdf_renderer_script=repo_root / "webui" / "render-pdf.mjs",
    )


@pytest.fixture()
def storage(test_settings):
    from digagent.storage import FileStorage

    return FileStorage(test_settings)


@pytest.fixture()
def runtime_modules(monkeypatch):
    return load_runtime_api(monkeypatch)


@pytest.fixture()
def manager(test_settings, runtime_modules):
    turn_manager, _ = runtime_modules
    return turn_manager(test_settings)


@pytest.fixture()
def app(manager, runtime_modules):
    _, create_app = runtime_modules
    return create_app(manager)
