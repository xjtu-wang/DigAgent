from __future__ import annotations

import asyncio
from typing import Any

from digagent.config import current_env_summary, load_profiles
from digagent.deepagents_runtime.factory import build_runtime
from digagent.deepagents_runtime.mcp import list_mcp_server_names
from digagent.deepagents_runtime.memory import memory_source_paths
from digagent.deepagents_runtime.project_tools import project_tool_catalog
from digagent.deepagents_runtime.skills import skill_source_paths
from digagent.deepagents_runtime.state import SessionRuntimeHandle
from digagent.deepagents_runtime.turns import POLL_INTERVAL_SEC, TERMINAL_TURN_STATUSES, load_session_events, load_turn_events
from digagent.models import ApprovalStatus, MessageRecord, Scope, SessionPermissionOverrides, SessionRecord, TurnEvent, TurnRecord, TurnStatus
from digagent.plugins import PluginCatalog


class TurnManagerSessionMixin:
    def catalog(self) -> dict[str, Any]:
        profiles = load_profiles(self.settings)
        return {
            "framework": "deepagents",
            "env": current_env_summary(self.settings),
            "profiles": [
                {"name": item.name, "description": item.description, "model": item.model or self.settings.model}
                for item in profiles.values()
            ],
            "tools": project_tool_catalog(self.settings),
            "skills": skill_source_paths(self.settings),
            "memory": memory_source_paths(self.settings),
            "plugins": PluginCatalog(self.settings).catalog(),
            "mcp_servers": list_mcp_server_names(self.settings),
            "cve": self.cve_status(),
        }

    def create_session(self, title: str, profile_name: str, scope: Scope) -> SessionRecord:
        return self.storage.create_session(title=title, root_agent_profile=profile_name, scope=scope)

    def list_sessions(self) -> list[SessionRecord]:
        return self.storage.list_sessions()

    def list_messages(self, session_id: str) -> list[MessageRecord]:
        return self.storage.load_messages(session_id)

    def list_turns(self, session_id: str) -> list[TurnRecord]:
        return self.storage.list_turns(session_id)

    def get_turn(self, turn_id: str) -> TurnRecord:
        return self.storage.find_turn(turn_id)

    async def get_turn_graph(self, turn_id: str) -> dict[str, Any]:
        turn = self.storage.find_turn(turn_id)
        if turn.task_graph and turn.task_graph.nodes:
            payload = turn.task_graph.model_dump(mode="json")
            payload["source"] = "task_graph"
            return payload
        session = self.storage.load_session(turn.session_id)
        handle = await self._runtime_handle(session, auto_approve=turn.auto_approve)
        payload = handle.runtime.agent.get_graph(config=self._thread_config(session.session_id)).to_json(with_schemas=True)
        payload["source"] = "runtime_graph"
        return payload

    def pending_approvals_for_turn(self, turn_id: str) -> list[dict[str, Any]]:
        turn = self.storage.find_turn(turn_id)
        approvals = []
        for approval_id in turn.approval_ids:
            approval = self.storage.load_approval(approval_id)
            if approval.status != ApprovalStatus.PENDING:
                continue
            approvals.append(approval)
        return [self._serialize_pending_approval(item) for item in approvals]

    async def stream_events(self, session_id: str, *, since_index: int | None = None, event_types: set[str] | None = None):
        index = self.session_event_count(session_id) if since_index is None else since_index
        while True:
            events = self.load_session_event_history(session_id, event_types=event_types)
            while index < len(events):
                yield events[index]
                index += 1
            await asyncio.sleep(POLL_INTERVAL_SEC)

    async def stream_turn_events(self, turn_id: str, *, since_index: int | None = None):
        turn = self.storage.find_turn(turn_id)
        index = self.turn_event_count(turn.turn_id) if since_index is None else since_index
        while True:
            events = self.load_turn_event_history(turn.turn_id)
            while index < len(events):
                yield events[index]
                index += 1
            if index >= len(events) and self.turn_stream_stopped(turn.turn_id):
                return
            await asyncio.sleep(POLL_INTERVAL_SEC)
            turn = self.storage.find_turn(turn_id)

    def load_session_event_history(self, session_id: str, *, event_types: set[str] | None = None) -> list[TurnEvent]:
        return self._filter_events(load_session_events(self.storage, session_id), event_types)

    def load_turn_event_history(self, turn_id: str) -> list[TurnEvent]:
        turn = self.storage.find_turn(turn_id)
        return load_turn_events(self.storage, turn.session_id, turn.turn_id)

    def session_event_count(self, session_id: str, *, event_types: set[str] | None = None) -> int:
        return len(self.load_session_event_history(session_id, event_types=event_types))

    def turn_event_count(self, turn_id: str) -> int:
        return len(self.load_turn_event_history(turn_id))

    def turn_stream_stopped(self, turn_id: str) -> bool:
        return self.storage.find_turn(turn_id).status in {TurnStatus.AWAITING_APPROVAL, TurnStatus.AWAITING_USER_INPUT} or self._is_turn_terminal(turn_id)

    def update_session_scope(self, *, session_id: str, add: Scope, remove: Scope, replace: Scope | None) -> SessionRecord:
        session = self.storage.load_session(session_id)
        session.scope = replace or Scope(
            repo_paths=self._merge_list(session.scope.repo_paths, add.repo_paths, remove.repo_paths),
            allowed_domains=self._merge_list(session.scope.allowed_domains, add.allowed_domains, remove.allowed_domains),
            artifacts=self._merge_list(session.scope.artifacts, add.artifacts, remove.artifacts),
        )
        self.storage.save_session(session)
        return session

    def update_session_permissions(
        self,
        *,
        session_id: str,
        merge: SessionPermissionOverrides | None,
        replace: SessionPermissionOverrides | None,
        clear: bool,
    ) -> SessionRecord:
        session = self.storage.load_session(session_id)
        if clear:
            session.permission_overrides = SessionPermissionOverrides()
        elif replace is not None:
            session.permission_overrides = replace
        elif merge is not None:
            session.permission_overrides = self._merge_permissions(session.permission_overrides, merge)
        self.storage.save_session(session)
        self._runtimes.pop(session_id, None)
        return session

    def archive_session(self, session_id: str) -> SessionRecord:
        session = self.storage.load_session(session_id)
        if session.active_turn_id:
            raise RuntimeError("Cannot archive a session with an active turn.")
        return self.storage.archive_session(session_id)

    def unarchive_session(self, session_id: str) -> SessionRecord:
        return self.storage.unarchive_session(session_id)

    def delete_session(self, session_id: str) -> str:
        session = self.storage.load_session(session_id)
        if session.active_turn_id:
            raise RuntimeError("Cannot delete a session with an active turn.")
        handle = self._runtimes.pop(session_id, None)
        if handle is not None and hasattr(handle.runtime, "mcp_runtime"):
            handle.runtime.mcp_runtime.close()
        self.storage.delete_session(session_id)
        return session_id

    def get_evidence(self, evidence_id: str):
        return self.storage.load_evidence(evidence_id)

    def get_artifact(self, artifact_id: str):
        return self.storage.load_artifact(artifact_id)

    async def sync_cve(self, max_records: int | None = None) -> dict[str, Any]:
        return (await self.knowledge_base.sync(max_records=max_records)).model_dump(mode="json")

    def cve_status(self) -> dict[str, Any]:
        return self.knowledge_base.state().model_dump(mode="json")

    def search_cve(self, *, query: str = "", cve_id: str | None = None, cwe: str | None = None, product: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        return [item.model_dump(mode="json") for item in self.knowledge_base.search(query=query, cve_id=cve_id, cwe=cwe, product=product, limit=limit)]

    async def _runtime_handle(self, session: SessionRecord, *, auto_approve: bool) -> SessionRuntimeHandle:
        resolved_auto_approve = auto_approve or session.permission_overrides.auto_approve
        handle = self._runtimes.get(session.session_id)
        if handle is not None and handle.auto_approve == resolved_auto_approve and handle.profile_name == session.root_agent_profile:
            return handle
        if handle is not None:
            await handle.aclose()
        runtime = await build_runtime(
            session_id=session.session_id,
            profile_name=session.root_agent_profile,
            auto_approve=resolved_auto_approve,
            overrides=session.permission_overrides,
            settings=self.settings,
        )
        handle = SessionRuntimeHandle(
            session_id=session.session_id,
            profile_name=session.root_agent_profile,
            auto_approve=resolved_auto_approve,
            runtime=runtime,
            checkpoint_context=runtime.checkpoint_context,
        )
        self._runtimes[session.session_id] = handle
        return handle

    def _thread_config(self, session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}}

    def _filter_events(self, events: list[TurnEvent], event_types: set[str] | None) -> list[TurnEvent]:
        if not event_types:
            return events
        return [event for event in events if event.type in event_types]

    def _is_turn_terminal(self, turn_id: str) -> bool:
        return self.storage.find_turn(turn_id).status in TERMINAL_TURN_STATUSES
