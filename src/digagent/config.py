from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from digagent.models import AgentProfile
from digagent.utils import expand_env_text


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    base_url: str | None = Field(default=None, alias="BASE_URL")
    model: str | None = Field(default=None, alias="MODEL")
    nvd_api_key: str | None = Field(default=None, alias="NVD_API_KEY")
    digagent_use_fake_model: bool = Field(default=False, alias="DIGAGENT_USE_FAKE_MODEL")
    workspace_root: Path = Field(default_factory=lambda: Path.cwd())
    config_dir: Path = Field(default_factory=lambda: Path.cwd() / "config")
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / "data")
    frontend_dist: Path = Field(default_factory=lambda: Path.cwd() / "webui" / "dist")
    pdf_renderer_script: Path = Field(default_factory=lambda: Path.cwd() / "webui" / "render-pdf.mjs")
    chrome_bin: str = Field(default="/usr/sbin/google-chrome-stable", alias="GOOGLE_CHROME_BIN")
    shell_timeout_sec: int = 60
    shell_output_limit: int = 32768

    @property
    def can_use_model(self) -> bool:
        return not self.digagent_use_fake_model and bool(self.openai_api_key and self.base_url and self.model)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


def load_profiles(settings: AppSettings | None = None) -> dict[str, AgentProfile]:
    settings = settings or get_settings()
    profiles: dict[str, AgentProfile] = {}
    agent_dir = settings.config_dir / "agents"
    for path in sorted(agent_dir.glob("*.yaml")):
        raw_text = expand_env_text(path.read_text(encoding="utf-8"))
        payload = yaml.safe_load(raw_text) or {}
        prompt_path = Path(payload.pop("system_prompt_file"))
        if not prompt_path.is_absolute():
            prompt_path = settings.workspace_root / prompt_path
        prompt_text = prompt_path.read_text(encoding="utf-8")
        payload["system_prompt"] = prompt_text.strip()
        profile = AgentProfile.model_validate(payload)
        profiles[profile.name] = profile
    return profiles


def resolve_profile(profile_name: str, settings: AppSettings | None = None) -> AgentProfile:
    profiles = load_profiles(settings)
    if profile_name not in profiles:
        available = ", ".join(sorted(profiles))
        raise KeyError(f"Unknown profile '{profile_name}'. Available: {available}")
    return profiles[profile_name]


def current_env_summary(settings: AppSettings | None = None) -> dict[str, str | bool | None]:
    settings = settings or get_settings()
    return {
        "model": settings.model,
        "base_url": settings.base_url,
        "can_use_model": settings.can_use_model,
        "fake_model": settings.digagent_use_fake_model,
        "has_nvd_api_key": bool(settings.nvd_api_key),
        "workspace_root": str(settings.workspace_root),
    }
