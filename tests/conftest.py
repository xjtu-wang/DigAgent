from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from digagent.api import create_app
from digagent.config import AppSettings
from digagent.runtime import RunManager


@pytest.fixture()
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.fixture()
def test_settings(tmp_path: Path, repo_root: Path) -> AppSettings:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(repo_root / "data" / "skills", data_dir / "skills")
    return AppSettings(
        OPENAI_API_KEY="test-key",
        BASE_URL="https://example.invalid/v1",
        MODEL="fake-model",
        DIGAGENT_USE_FAKE_MODEL=True,
        workspace_root=repo_root,
        config_dir=repo_root / "config",
        data_dir=data_dir,
        frontend_dist=repo_root / "webui" / "dist",
        pdf_renderer_script=repo_root / "webui" / "render-pdf.mjs",
    )


@pytest.fixture()
def manager(test_settings: AppSettings) -> RunManager:
    manager = RunManager(test_settings)

    def export_stub(html_path: Path, output_path: Path) -> bytes:
        pdf = b"%PDF-1.4\n% DigAgent Test PDF\n"
        output_path.write_bytes(pdf)
        return pdf

    manager.reporter.export_pdf = export_stub
    return manager


@pytest.fixture()
def app(manager: RunManager):
    return create_app(manager)
