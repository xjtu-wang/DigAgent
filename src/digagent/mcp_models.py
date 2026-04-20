from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from digagent.models import DigAgentModel


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


class McpServerTool(DigAgentModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    risk_tags: list[str] = Field(default_factory=list)


class McpServerTransport(DigAgentModel):
    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _drop_unresolved_env_placeholders(self) -> "McpServerTransport":
        self.env = {
            key: value
            for key, value in self.env.items()
            if isinstance(value, str) and value and not _is_env_placeholder(value)
        }
        return self


class McpServerManifest(DigAgentModel):
    server_id: str
    name: str
    description: str
    enabled: bool = False
    transport: McpServerTransport
    related_skills: list[str] = Field(default_factory=list)
    default_risk_tags: list[str] = Field(default_factory=list)
    tool_risk_overrides: dict[str, list[str]] = Field(default_factory=dict)
    tool_allowlist: list[str] = Field(default_factory=list)
    required_env: list[str] = Field(default_factory=list)
    advertised_tools: list[McpServerTool] = Field(default_factory=list)

    def allows_tool(self, tool_name: str) -> bool:
        return not self.tool_allowlist or tool_name in self.tool_allowlist

    def missing_required_env(self) -> list[str]:
        return [name for name in self.required_env if not self.transport.env.get(name)]

    def advertised_tool(self, tool_name: str) -> McpServerTool | None:
        for tool in self.advertised_tools:
            if tool.name == tool_name:
                return tool
        return None

    def tool_risk_tags(self, tool_name: str) -> list[str]:
        advertised = self.advertised_tool(tool_name)
        advertised_tags = advertised.risk_tags if advertised else []
        override_tags = self.tool_risk_overrides.get(tool_name, [])
        return _dedupe([*self.default_risk_tags, *advertised_tags, *override_tags])

    def visible_advertised_tools(self) -> list[McpServerTool]:
        return [tool for tool in self.advertised_tools if self.allows_tool(tool.name)]


class McpServerCatalogEntry(DigAgentModel):
    server_id: str
    name: str
    description: str
    enabled: bool
    transport: str
    related_skills: list[str] = Field(default_factory=list)
    default_risk_tags: list[str] = Field(default_factory=list)
    advertised_tools: list[McpServerTool] = Field(default_factory=list)
    required_env: list[str] = Field(default_factory=list)
    available: bool = False
    issues: list[str] = Field(default_factory=list)


def _is_env_placeholder(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("${") and stripped.endswith("}")
