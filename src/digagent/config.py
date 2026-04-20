from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from digagent.models import AgentProfile
from digagent.prompts import load_prompt_text
from digagent.utils import expand_env_text


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    base_url: str | None = Field(default=None, alias="BASE_URL")
    model: str | None = Field(default=None, alias="MODEL")
    nvd_api_key: str | None = Field(default=None, alias="NVD_API_KEY")
    digagent_use_fake_model: bool = Field(default=False, alias="DIGAGENT_USE_FAKE_MODEL")
    workspace_root: Path = Field(default_factory=lambda: Path.cwd())
    data_dir: Path = Field(default_factory=lambda: Path.cwd() / "data")
    frontend_dist: Path = Field(default_factory=lambda: Path.cwd() / "webui" / "dist")
    pdf_renderer_script: Path = Field(default_factory=lambda: Path.cwd() / "webui" / "render-pdf.mjs")
    chrome_bin: str = Field(default="/usr/sbin/google-chrome-stable", alias="GOOGLE_CHROME_BIN")
    web_search_base_url: str = Field(default="https://www.bing.com/search", alias="WEB_SEARCH_BASE_URL")
    mcp_servers_dir: Path | None = Field(default=None, alias="MCP_SERVERS_DIR")
    shell_timeout_sec: int = 60
    shell_output_limit: int = 32768
    approval_timeout_sec: int = Field(default=900, alias="APPROVAL_TIMEOUT_SEC")

    @model_validator(mode="after")
    def _resolve_default_paths(self) -> "AppSettings":
        if self.mcp_servers_dir is None:
            self.mcp_servers_dir = self.workspace_root / ".agents" / "mcp"
        return self

    @property
    def can_use_model(self) -> bool:
        return not self.digagent_use_fake_model and bool(self.openai_api_key and self.base_url and self.model)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()


def _settings_env_values(settings: AppSettings) -> dict[str, str]:
    values: dict[str, str] = {}
    for name, field in type(settings).model_fields.items():
        value = getattr(settings, name)
        if value is None:
            continue
        key = field.alias or name.upper()
        values[key] = str(value)
    return values


def load_profiles(settings: AppSettings | None = None) -> dict[str, AgentProfile]:
    settings = settings or get_settings()
    profiles: dict[str, AgentProfile] = {}
    agent_dir = settings.workspace_root / ".agents" / "subagents"
    env_values = _settings_env_values(settings)
    for path in sorted(agent_dir.glob("*/agent.yaml")):
        raw_text = expand_env_text(path.read_text(encoding="utf-8"), env_values)
        payload = yaml.safe_load(raw_text) or {}
        payload["system_prompt"] = load_prompt_text(path.parent, settings=settings)
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
        "approval_timeout_sec": settings.approval_timeout_sec,
    }
