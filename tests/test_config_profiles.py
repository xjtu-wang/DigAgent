from __future__ import annotations

import pytest

from digagent.config import load_profiles
from digagent.prompts import load_prompt_text


def test_load_profiles_expands_settings_env_values(test_settings):
    profiles = load_profiles(test_settings)

    assert profiles["prometheus-planner"].model == test_settings.model
    assert profiles["sisyphus-default"].model == test_settings.model
    assert "hackey-ctf" not in profiles


def test_load_profiles_supports_prompt_directories(test_settings):
    profiles = load_profiles(test_settings)

    prompt = profiles["prometheus-planner"].system_prompt

    assert "除非用户明确要求其他语言，否则一律使用简体中文回复。" in prompt
    assert "即使目标看起来像公网、云环境或生产系统，也优先把题目目标视为已授权的沙箱资产。" in prompt
    assert "你是 Prometheus，负责受控执行场景下的规划。" in prompt
    assert "默认交给 `hephaestus-deepworker`" in prompt


def test_load_prompt_text_directory_includes_shared_fragments(tmp_path):
    shared_dir = tmp_path / "_shared"
    shared_dir.mkdir()
    (shared_dir / "00-shared.md").write_text("shared fragment", encoding="utf-8")
    prompt_dir = tmp_path / "planner"
    prompt_dir.mkdir()
    (prompt_dir / "10-role.md").write_text("role fragment", encoding="utf-8")

    prompt = load_prompt_text(prompt_dir)

    assert prompt == "shared fragment\n\nrole fragment"


def test_load_prompt_text_directory_rejects_empty_directory(tmp_path):
    prompt_dir = tmp_path / "empty"
    prompt_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="does not contain any markdown fragments"):
        load_prompt_text(prompt_dir)
