from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from digagent.config import AppSettings, get_settings, load_profiles
from digagent.deepagents_runtime import session_ops as session_ops_module
from digagent.deepagents_runtime.manager_ops import TurnManagerOpsMixin
from digagent.deepagents_runtime.state import SessionRuntimeHandle, extract_assistant_text, extract_text_chunk
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
        self._runtimes: dict[str, Any] = {}
        self._pending_approvals: dict[str, Any] = {}
        self._title_tasks: dict[str, asyncio.Task[None]] = {}
        self._session_live_subscribers: dict[str, list[tuple[asyncio.Queue[Any], set[str] | None]]] = {}
        self._turn_live_subscribers: dict[str, list[tuple[asyncio.Queue[Any], set[str] | None]]] = {}

    def _publish_live_event(self, event) -> None:
        self._fan_out_live_event(self._session_live_subscribers.get(event.session_id, []), event)
        if event.turn_id:
            self._fan_out_live_event(self._turn_live_subscribers.get(event.turn_id, []), event)

    def _fan_out_live_event(self, subscribers: list[tuple[asyncio.Queue[Any], set[str] | None]], event) -> None:
        if not subscribers:
            return
        stale: list[tuple[asyncio.Queue[Any], set[str] | None]] = []
        for queue, event_types in list(subscribers):
            if event_types and event.type not in event_types:
                continue
            try:
                queue.put_nowait(event)
            except RuntimeError:
                stale.append((queue, event_types))
        for subscriber in stale:
            with suppress(ValueError):
                subscribers.remove(subscriber)

    async def _stream_live_session_events(self, session_id: str, *, event_types: set[str] | None = None):
        queue: asyncio.Queue[Any] = asyncio.Queue()
        subscribers = self._session_live_subscribers.setdefault(session_id, [])
        subscriber = (queue, event_types)
        subscribers.append(subscriber)
        try:
            while True:
                yield await queue.get()
        finally:
            with suppress(ValueError):
                subscribers.remove(subscriber)
            if not subscribers:
                self._session_live_subscribers.pop(session_id, None)

    async def _stream_live_turn_events(self, turn_id: str, *, event_types: set[str] | None = None):
        queue: asyncio.Queue[Any] = asyncio.Queue()
        subscribers = self._turn_live_subscribers.setdefault(turn_id, [])
        subscriber = (queue, event_types)
        subscribers.append(subscriber)
        try:
            while True:
                yield await queue.get()
        finally:
            with suppress(ValueError):
                subscribers.remove(subscriber)
            if not subscribers:
                self._turn_live_subscribers.pop(turn_id, None)

    async def handle_message(
        self,
        *,
        session_id: str,
        content: str,
        profile_name: str,
        scope: Scope,
        auto_approve: bool,
        mentions: list[str] | None = None,
        title: str | None = None,
    ) -> tuple[SessionRecord, UserTurnResult]:
        if not self.settings.can_use_model:
            raise RuntimeError("Real model is not configured; refusing to run without a real model.")
        addressed = self._validate_mentions(mentions)
        routed_profile = addressed[0] if addressed else profile_name
        context = self._turn_context_for(profile_name, routed_profile, addressed)
        session = self.storage.load_session(session_id)
        session = self._update_session_metadata(session, profile_name=profile_name, title=title, scope=scope, **context)
        turn = self.storage.create_turn(
            session_id=session.session_id,
            profile_name=routed_profile,
            task=content,
            scope=session.scope,
            budget=RuntimeBudget(),
            auto_approve=auto_approve,
        )
        turn.root_agent_id = profile_name
        turn = self._sync_turn_context(turn, **context)
        user_message = self._append_message(
            session.session_id,
            turn.turn_id,
            content,
            role=MessageRole.USER,
            speaker_profile="user",
            addressed_participants=addressed,
            participant_profile=routed_profile,
            handoff_from=profile_name if addressed else None,
            handoff_to=routed_profile if addressed else None,
        )
        turn.trigger_message_id = user_message.message_id
        self.storage.save_turn(turn)
        self._sync_session_context(session.session_id, **context)
        self._maybe_schedule_session_title(
            session,
            turn_id=turn.turn_id,
            message_id=user_message.message_id,
            content=content,
        )
        handle = await self._runtime_handle(self.storage.load_session(session_id), auto_approve=auto_approve)
        old_turn, old_task = await self._activate_turn(handle, turn, content, **context)
        if old_turn is not None:
            self._supersede_turn(old_turn, new_turn_id=turn.turn_id)
        if old_task is not None:
            old_task.cancel()
            with suppress(asyncio.CancelledError):
                await old_task
        await self._attach_task(handle, turn.turn_id)
        if addressed:
            return await self._execute_mentioned_turn(
                session_id=session.session_id,
                turn_id=turn.turn_id,
                requester_profile=profile_name,
                handle=handle,
            )
        return await self._execute_turn(
            session_id=session.session_id,
            turn_id=turn.turn_id,
            graph_input={"messages": [HumanMessage(content=content)]},
            handle=handle,
        )

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
        approval_context = self._turn_context(turn)
        snapshot = None
        await self._attach_task(handle, turn.turn_id)
        try:
            if turn.addressed_participants:
                await self._run_mention_chain(
                    session_id=turn.session_id,
                    turn_id=turn.turn_id,
                    requester_profile=session.root_agent_profile,
                    resume_payload=payload,
                )
            else:
                _, snapshot = await self._stream_graph(
                    turn.session_id,
                    turn.turn_id,
                    Command(resume={"decisions": payload}),
                    handle=handle,
                )
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
        self._emit(
            session.session_id,
            turn.turn_id,
            "approval_resolved",
            {"approval_id": approval_id, "status": approval.status},
            **approval_context,
        )
        turn = self.storage.find_turn(turn.turn_id)
        turn.approval_ids = [item for item in turn.approval_ids if item != approval_id]
        self.storage.save_turn(turn)
        session = self.storage.update_session(turn.session_id, lambda item: _drop_pending_approval(item, approval_id))
        self._emit_turn_updated(turn)
        self._emit_session_updated(session.session_id)
        if snapshot is not None:
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

    def _validate_mentions(self, mentions: list[str] | None) -> list[str]:
        available = {name.lower(): name for name in load_profiles(self.settings)}
        resolved: list[str] = []
        for raw_value in mentions or []:
            candidate = str(raw_value or "").strip().lstrip("@")
            if not candidate:
                raise ValueError("Mentions must not be blank.")
            profile_name = available.get(candidate.lower())
            if profile_name is None:
                available_names = ", ".join(sorted(available.values()))
                raise ValueError(f"Unknown mentioned agent '{candidate}'. Available: {available_names}")
            if profile_name not in resolved:
                resolved.append(profile_name)
        return resolved

    def _turn_context_for(self, requester_profile: str, participant_profile: str, addressed: list[str]) -> dict[str, Any]:
        return self._participant_context(
            speaker_profile=participant_profile,
            addressed_participants=addressed,
            participant_profile=participant_profile,
            handoff_from=requester_profile if addressed else None,
            handoff_to=participant_profile if addressed else None,
        )

    def _participant_step_context(
        self,
        turn: TurnRecord,
        *,
        participant_profile: str,
        handoff_from: str,
    ) -> dict[str, Any]:
        return self._participant_context(
            speaker_profile=participant_profile,
            addressed_participants=turn.addressed_participants,
            participant_profile=participant_profile,
            handoff_from=handoff_from,
            handoff_to=participant_profile,
        )

    def _participant_outputs(self, session_id: str, turn_id: str) -> list[tuple[str, str]]:
        outputs: list[tuple[str, str]] = []
        for message in self.list_messages(session_id):
            if message.turn_id != turn_id or message.role != MessageRole.ASSISTANT:
                continue
            speaker = message.speaker_profile or message.participant_profile or "assistant"
            outputs.append((speaker, message.content))
        return outputs

    def _participant_input(self, turn: TurnRecord, participant_profile: str, prior_outputs: list[tuple[str, str]]) -> str:
        if not prior_outputs:
            return turn.user_task
        prior_text = "\n\n".join(f"@{speaker}\n{content}" for speaker, content in prior_outputs)
        addressed = ", ".join(f"@{item}" for item in turn.addressed_participants)
        return (
            f"Original user request:\n{turn.user_task}\n\n"
            f"Mention chain order: {addressed}\n\n"
            f"Prior participant outputs:\n{prior_text}\n\n"
            f"You are @{participant_profile}. Continue the chain by responding to the original request after considering the prior outputs."
        )

    def _participant_thread_config(self, session_id: str, turn_id: str, participant_profile: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"{session_id}:{turn_id}:{participant_profile}"}}

    async def _build_profile_handle(self, session: SessionRecord, profile_name: str, *, auto_approve: bool) -> SessionRuntimeHandle:
        resolved_auto_approve = auto_approve or session.permission_overrides.auto_approve
        runtime = await session_ops_module.build_runtime(
            session_id=session.session_id,
            profile_name=profile_name,
            auto_approve=resolved_auto_approve,
            overrides=session.permission_overrides,
            settings=self.settings,
        )
        return SessionRuntimeHandle(
            session_id=session.session_id,
            profile_name=profile_name,
            auto_approve=resolved_auto_approve,
            runtime=runtime,
            checkpoint_context=runtime.checkpoint_context,
        )

    async def _activate_turn(self, handle, turn: TurnRecord, content: str, **kwargs: Any):
        current_task = asyncio.current_task()
        old_turn = None
        old_task = None
        context = self._context_for_turn(turn, **kwargs)
        async with handle.lock:
            session = self.storage.load_session(turn.session_id)
            if session.active_turn_id and session.active_turn_id != turn.turn_id:
                old_turn = self.storage.load_turn(turn.session_id, session.active_turn_id)
                old_task = handle.active_task if handle.active_task is not current_task else None
            session, turn = self._mark_turn_started(session, turn)
            turn = self._sync_turn_context(turn, **context)
            self._sync_session_context(session.session_id, **context)
            handle.active_turn_id = turn.turn_id
            handle.active_task = current_task
            self._emit(
                session.session_id,
                turn.turn_id,
                "turn_started",
                {"task": content, "profile_name": turn.profile_name},
                **context,
            )
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

    async def _execute_turn(self, session_id: str, turn_id: str, graph_input: Any, *, handle=None):
        turn = self.storage.load_turn(session_id, turn_id)
        active_handle = handle or await self._runtime_handle(self.storage.load_session(session_id), auto_approve=turn.auto_approve)
        try:
            session, snapshot = await self._stream_graph(session_id, turn_id, graph_input, handle=active_handle)
        except asyncio.CancelledError:
            return self._cancelled_result(session_id, turn_id)
        except Exception as exc:
            session = self._fail_turn(self.storage.load_session(session_id), self.storage.load_turn(session_id, turn_id), exc)
            turn = self.storage.load_turn(session_id, turn_id)
            return session, UserTurnResult(disposition=UserTurnDisposition.REJECT, session_id=session_id, turn_id=turn_id, reason=turn.error_message)
        finally:
            await self._detach_task(active_handle, turn_id)
        return self._resolve_snapshot(session, self.storage.load_turn(session_id, turn_id), snapshot)

    async def _execute_mentioned_turn(self, *, session_id: str, turn_id: str, requester_profile: str, handle):
        try:
            return await self._run_mention_chain(session_id=session_id, turn_id=turn_id, requester_profile=requester_profile)
        except asyncio.CancelledError:
            return self._cancelled_result(session_id, turn_id)
        except Exception as exc:
            session = self._fail_turn(self.storage.load_session(session_id), self.storage.load_turn(session_id, turn_id), exc)
            turn = self.storage.load_turn(session_id, turn_id)
            return session, UserTurnResult(disposition=UserTurnDisposition.REJECT, session_id=session_id, turn_id=turn_id, reason=turn.error_message)
        finally:
            await self._detach_task(handle, turn_id)

    async def _run_mention_chain(
        self,
        *,
        session_id: str,
        turn_id: str,
        requester_profile: str,
        resume_payload: list[dict[str, Any]] | None = None,
    ) -> tuple[SessionRecord, UserTurnResult]:
        session = self.storage.load_session(session_id)
        turn = self.storage.load_turn(session_id, turn_id)
        prior_outputs = self._participant_outputs(session_id, turn_id)
        start_index = len(prior_outputs)
        if start_index >= len(turn.addressed_participants):
            raise RuntimeError(f"No remaining mentioned participant for turn {turn_id}.")
        last_message = None
        for index in range(start_index, len(turn.addressed_participants)):
            participant = turn.addressed_participants[index]
            handoff_from = requester_profile if index == 0 else turn.addressed_participants[index - 1]
            turn = self._emit_participant_handoff(session, turn, handoff_from=handoff_from, handoff_to=participant)
            session = self.storage.load_session(session_id)
            turn = self.storage.load_turn(session_id, turn_id)
            graph_input = self._participant_graph_input(turn, participant, prior_outputs, resume_payload)
            snapshot = await self._run_participant_step(
                session=session,
                turn=turn,
                participant=participant,
                graph_input=graph_input,
                handoff_from=handoff_from,
            )
            if getattr(snapshot, "interrupts", ()):
                session = self._store_interrupts(session, turn, snapshot.interrupts)
                turn = self.storage.load_turn(session_id, turn_id)
                context = self._turn_context(turn)
                return session, UserTurnResult(
                    disposition=UserTurnDisposition.CREATE_TURN,
                    session_id=session_id,
                    turn_id=turn.turn_id,
                    approval_ids=turn.approval_ids,
                    **context,
                )
            assistant_text = extract_assistant_text(getattr(snapshot, "values", snapshot))
            context = self._participant_step_context(turn, participant_profile=participant, handoff_from=handoff_from)
            last_message = self._record_assistant_message(session, turn, assistant_text, **context)
            prior_outputs.append((participant, assistant_text))
            resume_payload = None
            session = self.storage.load_session(session_id)
            turn = self.storage.load_turn(session_id, turn_id)
        final_context = self._turn_context(turn)
        session = self._finalize_completed_turn(session, turn, last_message.content, **final_context)
        return session, UserTurnResult(
            disposition=UserTurnDisposition.CREATE_TURN,
            session_id=session_id,
            turn_id=turn_id,
            message_id=last_message.message_id,
            assistant_message=last_message.content,
            **final_context,
        )

    def _participant_graph_input(
        self,
        turn: TurnRecord,
        participant: str,
        prior_outputs: list[tuple[str, str]],
        resume_payload: list[dict[str, Any]] | None,
    ) -> Any:
        if resume_payload is not None:
            return Command(resume={"decisions": resume_payload})
        return {"messages": [HumanMessage(content=self._participant_input(turn, participant, prior_outputs))]}

    async def _run_participant_step(
        self,
        *,
        session: SessionRecord,
        turn: TurnRecord,
        participant: str,
        graph_input: Any,
        handoff_from: str,
    ) -> Any:
        context = self._participant_step_context(turn, participant_profile=participant, handoff_from=handoff_from)
        handle = await self._build_profile_handle(session, participant, auto_approve=turn.auto_approve)
        try:
            _, snapshot = await self._stream_graph(
                session.session_id,
                turn.turn_id,
                graph_input,
                handle=handle,
                thread_config=self._participant_thread_config(session.session_id, turn.turn_id, participant),
                context=context,
            )
            return snapshot
        finally:
            await handle.aclose()

    async def _stream_graph(
        self,
        session_id: str,
        turn_id: str,
        graph_input: Any,
        *,
        handle=None,
        thread_config: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ):
        session = self.storage.load_session(session_id)
        turn = self.storage.load_turn(session_id, turn_id)
        active_handle = handle or await self._runtime_handle(session, auto_approve=turn.auto_approve)
        active_context = context or self._turn_context(turn)
        config = thread_config or self._thread_config(session_id)
        async for chunk in active_handle.runtime.agent.astream(
            graph_input,
            config=config,
            stream_mode=STREAM_MODES,
            durability="sync",
            version="v2",
        ):
            mode, data, ns = coerce_stream_part(chunk)
            self._emit(session_id, turn_id, f"langgraph_{mode}", {"ns": list(ns), "payload": data}, **active_context)
            self._record_assistant_chunk(session_id, turn_id, mode, data, active_context)
            self._record_task_graph(session_id, turn_id, mode, data, ns, active_context)
        snapshot = await active_handle.runtime.agent.aget_state(config)
        return self.storage.load_session(session_id), snapshot

    def _resolve_snapshot(self, session: SessionRecord, turn: TurnRecord, snapshot: Any):
        context = self._turn_context(turn)
        if getattr(snapshot, "interrupts", ()):
            session = self._store_interrupts(session, turn, snapshot.interrupts)
            turn = self.storage.load_turn(session.session_id, turn.turn_id)
            return session, UserTurnResult(
                disposition=UserTurnDisposition.CREATE_TURN,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                approval_ids=turn.approval_ids,
                **self._turn_context(turn),
            )
        assistant_text = extract_assistant_text(getattr(snapshot, "values", snapshot))
        session, assistant_message = self._complete_turn(session, turn, assistant_text, **context)
        return session, UserTurnResult(
            disposition=UserTurnDisposition.CREATE_TURN,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            message_id=assistant_message.message_id,
            assistant_message=assistant_text,
            **context,
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
            **self._turn_context(turn),
        )

    def _fail_approval(self, approval: ApprovalRecord, turn: TurnRecord, resolver: str, exc: Exception) -> ApprovalRecord:
        context = self._turn_context(turn)
        approval.status = ApprovalStatus.REJECTED
        approval.resolver = resolver
        approval.reason = f"{type(exc).__name__}: {exc}"
        approval.resolved_at = utc_now()
        self.storage.save_approval(approval)
        self._emit(
            turn.session_id,
            turn.turn_id,
            "approval_resolved",
            {"approval_id": approval.approval_id, "status": approval.status},
            **context,
        )
        self._fail_turn(self.storage.load_session(turn.session_id), turn, exc)
        return approval

    def _record_assistant_chunk(self, session_id: str, turn_id: str, mode: str, data: Any, context: dict[str, Any]) -> None:
        if mode != "messages" or not isinstance(data, (tuple, list)) or len(data) != 2:
            return
        message, metadata = data
        text = extract_text_chunk(message)
        if not text:
            return
        self._emit(session_id, turn_id, "assistant_chunk", {"text": text, "metadata": metadata}, **context)

    def _record_task_graph(
        self,
        session_id: str,
        turn_id: str,
        mode: str,
        data: Any,
        ns: tuple[str, ...],
        context: dict[str, Any],
    ) -> None:
        turn = self.storage.load_turn(session_id, turn_id)
        graph, events, changed = apply_stream_part(turn.task_graph, turn_id=turn_id, mode=mode, data=data, ns=ns)
        if not changed:
            return
        turn.task_graph = graph
        turn.budget_usage = compute_budget_usage(graph, started_at=turn.started_at or turn.created_at, now=utc_now())
        self.storage.save_turn(turn)
        self._emit(session_id, turn_id, "task_graph_updated", graph.model_dump(mode="json"), **context)
        for event_type, payload in events:
            self._emit(session_id, turn_id, event_type, payload, **context)


class SessionManager(TurnManager):
    pass


def _drop_pending_approval(session: SessionRecord, approval_id: str) -> SessionRecord:
    session.pending_approval_ids = [item for item in session.pending_approval_ids if item != approval_id]
    if session.status == SessionStatus.AWAITING_APPROVAL and not session.pending_approval_ids and session.active_turn_id:
        session.status = SessionStatus.ACTIVE_TURN
    return session
