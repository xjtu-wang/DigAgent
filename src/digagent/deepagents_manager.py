from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from digagent.config import AppSettings, get_settings
from digagent.cve import CveKnowledgeBase
from digagent.deepagents_runtime.manager_ops import TurnManagerOpsMixin
from digagent.deepagents_runtime.state import extract_assistant_text, extract_text_chunk
from digagent.deepagents_runtime.streaming import apply_stream_part, coerce_stream_part, compute_budget_usage
from digagent.models import (
    ApprovalRecord,
    ApprovalStatus,
    MessageRole,
    RuntimeBudget,
    Scope,
    SessionRecord,
    SessionStatus,
    TurnRecord,
    TurnStatus,
    UserTurnDisposition,
    UserTurnResult,
)
from digagent.storage import FileStorage
from digagent.utils import utc_now

STREAM_MODES = ["messages", "tasks", "checkpoints", "updates"]
TERMINAL_TURN_STATES = {
    TurnStatus.COMPLETED,
    TurnStatus.FAILED,
    TurnStatus.CANCELLED,
    TurnStatus.SUPERSEDED,
    TurnStatus.TIMED_OUT,
}


class TurnManager(TurnManagerOpsMixin):
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.storage = FileStorage(self.settings)
        self.knowledge_base = CveKnowledgeBase(self.settings, self.storage)
        self._runtimes: dict[str, Any] = {}
        self._pending_approvals: dict[str, Any] = {}
        self._title_tasks: dict[str, asyncio.Task[None]] = {}

    async def handle_message(
        self,
        *,
        session_id: str,
        content: str,
        profile_name: str,
        scope: Scope,
        auto_approve: bool,
        title: str | None = None,
    ) -> tuple[SessionRecord, UserTurnResult]:
        if not self.settings.can_use_model:
            raise RuntimeError("Real model is not configured; refusing to run without a real model.")
        session = self.storage.load_session(session_id)
        session = self._update_session_metadata(session, profile_name=profile_name, title=title, scope=scope)
        turn = self.storage.create_turn(
            session_id=session.session_id,
            profile_name=profile_name,
            task=content,
            scope=session.scope,
            budget=RuntimeBudget(),
            auto_approve=auto_approve,
        )
        message = self._append_message(session.session_id, turn.turn_id, content, role=MessageRole.USER)
        turn.trigger_message_id = message.message_id
        self.storage.save_turn(turn)
        self._maybe_schedule_session_title(
            session,
            turn_id=turn.turn_id,
            message_id=message.message_id,
            content=content,
        )
        handle = self._runtimes.get(session.session_id)
        if handle is None:
            handle = await self._runtime_handle(session, auto_approve=auto_approve)
        old_turn, old_task = await self._activate_turn(handle, turn, content)
        if old_turn is not None:
            self._supersede_turn(old_turn, new_turn_id=turn.turn_id)
        if old_task is not None:
            old_task.cancel()
            with suppress(asyncio.CancelledError):
                await old_task
        await self._attach_task(await self._runtime_handle(self.storage.load_session(session_id), auto_approve=auto_approve), turn.turn_id)
        return await self._execute_turn(session.session_id, turn.turn_id, {"messages": [HumanMessage(content=content)]})

    async def approve(
        self,
        approval_id: str,
        *,
        decisions: list[dict[str, Any]] | None = None,
        approved: bool | None = None,
        resolver: str = "webui",
        reason: str | None = None,
        **_: Any,
    ) -> ApprovalRecord:
        approval = self.storage.load_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise ValueError(f"Approval is not pending: {approval_id}")
        pending = self._pending_approvals.get(approval_id)
        payload = decisions or self._approval_decisions(pending, approved=bool(approved), reason=reason)
        turn = self.storage.find_turn(approval.turn_id)
        session = self.storage.load_session(turn.session_id)
        handle = await self._runtime_handle(session, auto_approve=turn.auto_approve)
        await self._attach_task(handle, turn.turn_id)
        try:
            _, snapshot = await self._stream_graph(turn.session_id, turn.turn_id, Command(resume={"decisions": payload}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._pending_approvals.pop(approval_id, None)
            return self._fail_approval(approval, turn, resolver, exc)
        finally:
            await self._detach_task(handle, turn.turn_id)
        self._pending_approvals.pop(approval_id, None)
        approval.status = ApprovalStatus.APPROVED if all(item["type"] == "approve" for item in payload) else ApprovalStatus.REJECTED
        approval.resolver = resolver
        approval.reason = reason
        approval.resolved_at = utc_now()
        self.storage.save_approval(approval)
        self._emit(session.session_id, turn.turn_id, "approval_resolved", {"approval_id": approval_id, "status": approval.status})
        turn = self.storage.find_turn(turn.turn_id)
        turn.approval_ids = [item for item in turn.approval_ids if item != approval_id]
        self.storage.save_turn(turn)
        self.storage.update_session(turn.session_id, lambda item: _drop_pending_approval(item, approval_id))
        self._resolve_snapshot(self.storage.load_session(turn.session_id), turn, snapshot)
        return approval

    async def cancel_turn_by_id(self, turn_id: str) -> TurnRecord:
        turn = self.storage.find_turn(turn_id)
        if turn.status in TERMINAL_TURN_STATES:
            return turn
        handle = self._runtimes.get(turn.session_id)
        task = None
        if handle is not None:
            async with handle.lock:
                if handle.active_turn_id == turn.turn_id:
                    task = handle.active_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return self._cancel_turn(turn, reason="Cancelled by user.")

    async def _activate_turn(self, handle, turn: TurnRecord, content: str):
        current_task = asyncio.current_task()
        old_turn = None
        old_task = None
        async with handle.lock:
            session = self.storage.load_session(turn.session_id)
            if session.active_turn_id and session.active_turn_id != turn.turn_id:
                old_turn = self.storage.load_turn(turn.session_id, session.active_turn_id)
                old_task = handle.active_task if handle.active_task is not current_task else None
            session, turn = self._mark_turn_started(session, turn)
            handle.active_turn_id = turn.turn_id
            handle.active_task = current_task
            self._emit(session.session_id, turn.turn_id, "turn_started", {"task": content, "profile_name": turn.profile_name})
        return old_turn, old_task

    async def _attach_task(self, handle, turn_id: str) -> None:
        async with handle.lock:
            handle.active_turn_id = turn_id
            handle.active_task = asyncio.current_task()

    async def _detach_task(self, handle, turn_id: str) -> None:
        async with handle.lock:
            if handle.active_turn_id == turn_id:
                handle.active_turn_id = None
            if handle.active_task is asyncio.current_task():
                handle.active_task = None

    async def _execute_turn(self, session_id: str, turn_id: str, graph_input: Any):
        turn = self.storage.load_turn(session_id, turn_id)
        handle = await self._runtime_handle(self.storage.load_session(session_id), auto_approve=turn.auto_approve)
        try:
            session, snapshot = await self._stream_graph(session_id, turn_id, graph_input)
        except asyncio.CancelledError:
            return self._cancelled_result(session_id, turn_id)
        except Exception as exc:
            session = self._fail_turn(self.storage.load_session(session_id), self.storage.load_turn(session_id, turn_id), exc)
            turn = self.storage.load_turn(session_id, turn_id)
            return session, UserTurnResult(disposition=UserTurnDisposition.REJECT, session_id=session_id, turn_id=turn_id, reason=turn.error_message)
        finally:
            await self._detach_task(handle, turn_id)
        return self._resolve_snapshot(session, self.storage.load_turn(session_id, turn_id), snapshot)

    async def _stream_graph(self, session_id: str, turn_id: str, graph_input: Any):
        session = self.storage.load_session(session_id)
        turn = self.storage.load_turn(session_id, turn_id)
        handle = await self._runtime_handle(session, auto_approve=turn.auto_approve)
        async for chunk in handle.runtime.agent.astream(
            graph_input,
            config=self._thread_config(session_id),
            stream_mode=STREAM_MODES,
            durability="sync",
            version="v2",
        ):
            mode, data, ns = coerce_stream_part(chunk)
            self._emit(session_id, turn_id, f"langgraph_{mode}", {"ns": list(ns), "payload": data})
            self._record_assistant_chunk(session_id, turn_id, mode, data)
            self._record_task_graph(session_id, turn_id, mode, data, ns)
        snapshot = await handle.runtime.agent.aget_state(self._thread_config(session_id))
        return self.storage.load_session(session_id), snapshot

    def _resolve_snapshot(self, session: SessionRecord, turn: TurnRecord, snapshot: Any):
        if getattr(snapshot, "interrupts", ()):
            session = self._store_interrupts(session, turn, snapshot.interrupts)
            turn = self.storage.load_turn(session.session_id, turn.turn_id)
            return session, UserTurnResult(
                disposition=UserTurnDisposition.CREATE_TURN,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                approval_ids=turn.approval_ids,
            )
        assistant_text = extract_assistant_text(getattr(snapshot, "values", snapshot))
        session, assistant_message = self._complete_turn(session, turn, assistant_text)
        return session, UserTurnResult(
            disposition=UserTurnDisposition.CREATE_TURN,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            message_id=assistant_message.message_id,
            assistant_message=assistant_text,
        )

    def _cancelled_result(self, session_id: str, turn_id: str):
        turn = self.storage.load_turn(session_id, turn_id)
        if turn.status not in TERMINAL_TURN_STATES:
            turn = self._cancel_turn(turn, reason="Cancelled.")
        session = self.storage.load_session(session_id)
        return session, UserTurnResult(
            disposition=UserTurnDisposition.REJECT,
            session_id=session_id,
            turn_id=turn_id,
            reason=turn.error_message or "Cancelled.",
        )

    def _fail_approval(self, approval: ApprovalRecord, turn: TurnRecord, resolver: str, exc: Exception) -> ApprovalRecord:
        approval.status = ApprovalStatus.REJECTED
        approval.resolver = resolver
        approval.reason = f"{type(exc).__name__}: {exc}"
        approval.resolved_at = utc_now()
        self.storage.save_approval(approval)
        self._emit(turn.session_id, turn.turn_id, "approval_resolved", {"approval_id": approval.approval_id, "status": approval.status})
        self._fail_turn(self.storage.load_session(turn.session_id), turn, exc)
        return approval

    def _record_assistant_chunk(self, session_id: str, turn_id: str, mode: str, data: Any) -> None:
        if mode != "messages" or not isinstance(data, (tuple, list)) or len(data) != 2:
            return
        message, metadata = data
        text = extract_text_chunk(message)
        if not text:
            return
        self._emit(session_id, turn_id, "assistant_chunk", {"text": text, "metadata": metadata})

    def _record_task_graph(self, session_id: str, turn_id: str, mode: str, data: Any, ns: tuple[str, ...]) -> None:
        turn = self.storage.load_turn(session_id, turn_id)
        graph, events, changed = apply_stream_part(turn.task_graph, turn_id=turn_id, mode=mode, data=data, ns=ns)
        if not changed:
            return
        turn.task_graph = graph
        turn.budget_usage = compute_budget_usage(graph, started_at=turn.started_at or turn.created_at, now=utc_now())
        self.storage.save_turn(turn)
        self._emit(session_id, turn_id, "task_graph_updated", graph.model_dump(mode="json"))
        for event_type, payload in events:
            self._emit(session_id, turn_id, event_type, payload)


class SessionManager(TurnManager):
    pass


def _drop_pending_approval(session: SessionRecord, approval_id: str) -> SessionRecord:
    session.pending_approval_ids = [item for item in session.pending_approval_ids if item != approval_id]
    if session.status == SessionStatus.AWAITING_APPROVAL and not session.pending_approval_ids and session.active_turn_id:
        session.status = SessionStatus.ACTIVE_TURN
    return session
