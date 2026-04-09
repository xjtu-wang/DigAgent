from __future__ import annotations

import json
from pathlib import Path

import yaml

from digagent.config import AppSettings, get_settings
from digagent.models import (
    ActionRequest,
    ActionTargets,
    AgentProfile,
    BudgetUsage,
    PermissionDecision,
    PermissionOutcome,
    Scope,
)
from digagent.utils import normalize_domain

HIGH_RISK_TAGS = {
    "filesystem_write",
    "shell_exec",
    "network",
    "external_exploit",
    "export_sensitive",
}

REGISTERED_SYSTEM_ACTIONS = {
    "skill_consult",
    "report_export",
}


class PolicyResolver:
    def __init__(self, registered_actions: set[str] | None = None, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        discovered = set(registered_actions or set()) or self._discover_registered_actions()
        self.registered_actions = discovered | REGISTERED_SYSTEM_ACTIONS

    def _discover_registered_actions(self) -> set[str]:
        names: set[str] = set()
        tools_dir = self.settings.data_dir / "tools"
        for path in sorted(list(tools_dir.glob("*.yaml")) + list(tools_dir.glob("*.json"))):
            try:
                if path.suffix == ".json":
                    payload = json.loads(path.read_text(encoding="utf-8"))
                else:
                    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                name = str(payload.get("name") or "").strip()
                if name:
                    names.add(name)
            except Exception:
                continue
        return names

    def resolve(
        self,
        action: ActionRequest,
        profile: AgentProfile,
        scope: Scope,
        budget_usage: BudgetUsage | None = None,
    ) -> PermissionOutcome:
        normalized = ActionTargets(
            paths=[str(Path(path).resolve()) for path in action.targets.paths],
            domains=[normalize_domain(domain) for domain in action.targets.domains],
        )

        if action.name not in self.registered_actions:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason=f"action '{action.name}' is not registered",
                normalized_targets=normalized,
            )

        if action.name not in profile.tool_allowlist:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason=f"tool '{action.name}' is not on the profile allowlist",
                normalized_targets=normalized,
            )

        if normalized.paths and profile.filesystem_scope:
            outcome = self._check_paths(normalized, profile.filesystem_scope, "profile filesystem scope")
            if outcome:
                return outcome

        if normalized.paths and scope.repo_paths:
            outcome = self._check_paths(normalized, scope.repo_paths, "session scope")
            if outcome:
                return outcome

        if normalized.domains and profile.network_scope:
            outcome = self._check_domains(normalized, profile.network_scope, "profile network scope")
            if outcome:
                return outcome

        if normalized.domains and scope.allowed_domains:
            outcome = self._check_domains(normalized, scope.allowed_domains, "session scope")
            if outcome:
                return outcome

        if budget_usage and budget_usage.tool_calls_used >= profile.runtime_budget.max_tool_calls:
            return PermissionOutcome(
                decision=PermissionDecision.DENY,
                reason="tool call budget exceeded",
                normalized_targets=normalized,
            )

        if any(tag in HIGH_RISK_TAGS for tag in action.risk_tags):
            return PermissionOutcome(
                decision=PermissionDecision.CONFIRM,
                reason="high-risk action requires approval",
                normalized_targets=normalized,
            )

        return PermissionOutcome(
            decision=PermissionDecision.ALLOW,
            reason="allowed by profile and session scope",
            normalized_targets=normalized,
        )

    def _check_paths(self, normalized: ActionTargets, allowed_roots: list[str], label: str) -> PermissionOutcome | None:
        roots = [str(Path(path).resolve()) for path in allowed_roots]
        for path in normalized.paths:
            if not any(path == root or path.startswith(f"{root}/") for root in roots):
                return PermissionOutcome(
                    decision=PermissionDecision.DENY,
                    reason=f"path '{path}' is outside the {label}",
                    normalized_targets=normalized,
                )
        return None

    def _check_domains(self, normalized: ActionTargets, allowed_domains: list[str], label: str) -> PermissionOutcome | None:
        allowset = {normalize_domain(domain) for domain in allowed_domains}
        for domain in normalized.domains:
            if domain not in allowset:
                return PermissionOutcome(
                    decision=PermissionDecision.DENY,
                    reason=f"domain '{domain}' is outside the {label}",
                    normalized_targets=normalized,
                )
        return None


class PermissionEngine:
    def __init__(
        self,
        settings: AppSettings | None = None,
        resolver: PolicyResolver | None = None,
        *,
        registered_actions: set[str] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.resolver = resolver or PolicyResolver(registered_actions=registered_actions, settings=self.settings)

    def decide(
        self,
        action: ActionRequest,
        profile: AgentProfile,
        scope: Scope,
        budget_usage: BudgetUsage | None = None,
    ) -> PermissionOutcome:
        return self.resolver.resolve(action, profile, scope, budget_usage)
