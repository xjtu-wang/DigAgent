from __future__ import annotations

import asyncio
import logging
from typing import Any

from digagent.deepagents_runtime.session_ops import TurnManagerSessionMixin
from digagent.deepagents_runtime.state import PendingApproval, to_event_data
from digagent.deepagents_runtime.streaming import compute_budget_usage
from digagent.deepagents_runtime.turns import is_turn_terminal
from digagent.models import (
    ApprovalRecord,
    ApprovalStatus,
    MessageRecord,
    MessageRole,
    Scope,
    SessionPermissionOverrides,
    SessionRecord,
    SessionStatus,
    SessionTitleSource,
    SessionTitleStatus,
    TurnEvent,
    TurnRecord,
    TurnStatus,
)
from digagent.session_titles import generate_session_title, is_seed_title
from digagent.utils import action_digest, new_id, utc_now

logger = logging.getLogger(__name__)
PARTICIPANT_CONTEXT_FIELDS = (
    "speaker_profile",
    "addressed_participants",
    "participant_profile",
    "handoff_from",
    "handoff_to",
)


class TurnManagerOpsMixin(TurnManagerSessionMixin):
    def _participant_context(
        self,
        *,
        speaker_profile: str | None = None,
        addressed_participants: list[str] | None = None,
        participant_profile: str | None = None,
        handoff_from: str | None = None,
        handoff_to: str | None = None,
    ) -> dict[str, Any]:
        return {
            "speaker_profile": speaker_profile,
            "addressed_participants": list(addressed_participants or []),
            "participant_profile": participant_profile,
            "handoff_from": handoff_from,
            "handoff_to": handoff_to,
        }

    def _turn_context(self, turn: TurnRecord) -> dict[str, Any]:
        return {
            "speaker_profile": turn.speaker_profile,
            "addressed_participants": list(turn.addressed_participants),
            "participant_profile": turn.participant_profile,
            "handoff_from": turn.handoff_from,
            "handoff_to": turn.handoff_to,
        }

    def _context_for_turn(self, turn: TurnRecord, **kwargs: Any) -> dict[str, Any]:
        return self._participant_context(**kwargs) if kwargs else self._turn_context(turn)

    def _apply_context(self, record: Any, context: dict[str, Any]) -> Any:
        for field in PARTICIPANT_CONTEXT_FIELDS:
            value = context[field]
            setattr(record, field, list(value) if field == "addressed_participants" else value)
        return record

    def _sync_turn_context(self, turn: TurnRecord, **kwargs: Any) -> TurnRecord:
        self._apply_context(turn, self._participant_context(**kwargs))
        self.storage.save_turn(turn)
        return turn

    def _sync_session_context(self, session_id: str, **kwargs: Any) -> SessionRecord:
        context = self._participant_context(**kwargs)

        def updater(session: SessionRecord) -> SessionRecord:
            return self._apply_context(session, context)

        return self.storage.update_session(session_id, updater)

    def _event_payload(self, data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        payload = to_event_data(data)
        if not isinstance(payload, dict):
            raise TypeError(f"Turn events require mapping payloads; got {type(payload).__name__}")
        return {**context, **payload}

    def _append_message(
        self,
        session_id: str,
        turn_id: str | None,
        content: str,
        role: MessageRole,
        **kwargs: Any,
    ) -> MessageRecord:
        context = self._participant_context(**kwargs)
        message = MessageRecord(
            message_id=new_id("msg"),
            session_id=session_id,
            turn_id=turn_id,
            role=role,
            sender="user" if role == MessageRole.USER else "assistant",
            content=content,
            **context,
            created_at=utc_now(),
        )
        self.storage.append_message(message)
        self._sync_session_context(session_id, **context)
        return message

    def _emit(self, session_id: str, turn_id: str | None, event_type: str, data: dict[str, Any], **kwargs: Any) -> TurnEvent:
        context = self._participant_context(**kwargs)
        event = TurnEvent(
            event_id=new_id("evt"),
            session_id=session_id,
            turn_id=turn_id,
            type=event_type,
            data=self._event_payload(data, context),
            **context,
            created_at=utc_now(),
        )
        self.storage.append_turn_event(session_id, event)
        return event

    def _update_session_metadata(
        self,
        session: SessionRecord,
        *,
        profile_name: str,
        title: str | None,
        scope: Scope,
        **kwargs: Any,
    ) -> SessionRecord:
        session.root_agent_profile = profile_name
        if title:
            session.title = title
        if any([scope.repo_paths, scope.allowed_domains, scope.artifacts]):
            session.scope = scope
        self._apply_context(session, self._participant_context(**kwargs))
        self.storage.save_session(session)
        return session

    def _maybe_schedule_session_title(
        self,
        session: SessionRecord,
        *,
        turn_id: str,
        message_id: str,
        content: str,
    ) -> None:
        if not self._is_first_user_message(session):
            return
        if not self._is_seed_title_candidate(session.title, content):
            if session.title_status == SessionTitleStatus.PENDING and session.title_source == SessionTitleSource.SEED:
                self.storage.update_session_title_state(
                    session.session_id,
                    title_status=SessionTitleStatus.READY,
                    title_source=SessionTitleSource.MANUAL,
                )
            return
        if session.session_id in self._title_tasks:
            return
        self.storage.update_session_title_state(
            session.session_id,
            title_status=SessionTitleStatus.GENERATING,
            title_source=SessionTitleSource.SEED,
        )
        task = asyncio.create_task(
            self._generate_session_title(session_id=session.session_id, turn_id=turn_id, message_id=message_id, content=content)
        )
        self._title_tasks[session.session_id] = task
        task.add_done_callback(lambda _: self._title_tasks.pop(session.session_id, None))

    def _is_first_user_message(self, session: SessionRecord) -> bool:
        return session.last_user_message_id is None

    def _is_seed_title_candidate(self, title: str, content: str) -> bool:
        if is_seed_title(title):
            return True
        return bool(title) and len(title) <= 60 and content.startswith(title)

    async def _generate_session_title(self, *, session_id: str, turn_id: str, message_id: str, content: str) -> None:
        session = self.storage.load_session(session_id)
        try:
            title = await generate_session_title(
                settings=self.settings,
                profile_name=session.root_agent_profile,
                message=content,
            )
        except Exception as exc:
            session = self.storage.update_session_title_state(session_id, title_status=SessionTitleStatus.FAILED)
            self._emit(
                session.session_id,
                None,
                "session_title_updated",
                {
                    "message_id": message_id,
                    "title": session.title,
                    "title_source": session.title_source,
                    "title_status": session.title_status,
                    "turn_id": turn_id,
                },
            )
            logger.warning("Session title generation failed for %s: %s", session_id, exc)
            return
        session = self.storage.update_session_title_state(
            session_id,
            title=title,
            title_status=SessionTitleStatus.READY,
            title_source=SessionTitleSource.MODEL,
        )
        self._emit(
            session.session_id,
            None,
            "session_title_updated",
            {
                "message_id": message_id,
                "title": session.title,
                "title_source": session.title_source,
                "title_status": session.title_status,
                "turn_id": turn_id,
            },
        )

    def _mark_turn_started(self, session: SessionRecord, turn: TurnRecord) -> tuple[SessionRecord, TurnRecord]:
        now = utc_now()
        turn.status = TurnStatus.RUNNING
        turn.started_at = turn.started_at or now
        turn.updated_at = now
        self.storage.save_turn(turn)
        session.status = SessionStatus.ACTIVE_TURN
        session.active_turn_id = turn.turn_id
        session.pending_approval_ids = []
        self.storage.save_session(session)
        return session, turn

    def _emit_participant_handoff(self, session: SessionRecord, turn: TurnRecord, *, handoff_from: str, handoff_to: str) -> TurnRecord:
        context = self._participant_context(
            speaker_profile=handoff_to,
            addressed_participants=turn.addressed_participants,
            participant_profile=handoff_to,
            handoff_from=handoff_from,
            handoff_to=handoff_to,
        )
        turn = self._sync_turn_context(turn, **context)
        self._sync_session_context(session.session_id, **context)
        self._emit(
            session.session_id,
            turn.turn_id,
            "participant_handoff",
            {"turn_id": turn.turn_id, "handoff_from": handoff_from, "handoff_to": handoff_to},
            **context,
        )
        return turn

    def _record_assistant_message(self, session: SessionRecord, turn: TurnRecord, assistant_text: str, **kwargs: Any) -> MessageRecord:
        context = self._context_for_turn(turn, **kwargs)
        turn = self._sync_turn_context(turn, **context)
        self._sync_session_context(session.session_id, **context)
        assistant_message = self._append_message(
            session.session_id,
            turn.turn_id,
            assistant_text,
            MessageRole.ASSISTANT,
            **context,
        )
        self._emit(
            session.session_id,
            turn.turn_id,
            "assistant_message",
            {"message_id": assistant_message.message_id, "message": assistant_text, "turn_id": turn.turn_id},
            **context,
        )
        return assistant_message

    def _finalize_completed_turn(self, session: SessionRecord, turn: TurnRecord, assistant_text: str, **kwargs: Any) -> SessionRecord:
        context = self._context_for_turn(turn, **kwargs)
        turn = self._sync_turn_context(turn, **context)
        self._sync_session_context(session.session_id, **context)
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.COMPLETED
        turn.approval_ids = []
        turn.awaiting_reason = None
        turn.final_response = assistant_text
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        session = self._release_session_turn(session.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(session.session_id, turn.turn_id, "completed", {"message": assistant_text}, **context)
        return session

    def _complete_turn(self, session: SessionRecord, turn: TurnRecord, assistant_text: str, **kwargs: Any):
        assistant_message = self._record_assistant_message(session, turn, assistant_text, **kwargs)
        session = self._finalize_completed_turn(session, turn, assistant_text, **kwargs)
        return session, assistant_message

    def _store_interrupts(self, session: SessionRecord, turn: TurnRecord, interrupts: tuple[Any, ...]):
        context = self._turn_context(turn)
        approval_ids: list[str] = []
        for interrupt in interrupts:
            approval_id = new_id("apr")
            record = ApprovalRecord(
                approval_id=approval_id,
                action_id=interrupt.id,
                turn_id=turn.turn_id,
                status=ApprovalStatus.PENDING,
                action_digest=action_digest(to_event_data(interrupt.value)),
                requested_by=turn.participant_profile or turn.profile_name,
                requested_at=utc_now(),
            )
            self.storage.save_approval(record)
            self._pending_approvals[approval_id] = PendingApproval(
                approval_id=approval_id,
                session_id=session.session_id,
                turn_id=turn.turn_id,
                interrupt_id=interrupt.id,
                request=interrupt.value,
            )
            approval_ids.append(approval_id)
            self._emit(
                session.session_id,
                turn.turn_id,
                "approval_required",
                {**self._serialize_pending_approval(record), "turn_id": turn.turn_id},
                **context,
            )
        turn.status = TurnStatus.AWAITING_APPROVAL
        turn.approval_ids = approval_ids
        turn.awaiting_reason = "Turn is awaiting approval."
        self.storage.save_turn(turn)
        session.status = SessionStatus.AWAITING_APPROVAL
        session.active_turn_id = turn.turn_id
        session.pending_approval_ids = approval_ids
        self.storage.save_session(session)
        self._emit(
            session.session_id,
            turn.turn_id,
            "awaiting_approval",
            {"approval_ids": approval_ids, "interrupts": [item for item in interrupts]},
            **context,
        )
        return session

    def _fail_turn(self, session: SessionRecord, turn: TurnRecord, exc: Exception) -> SessionRecord:
        context = self._turn_context(turn)
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.FAILED
        turn.approval_ids = []
        turn.error_message = f"{type(exc).__name__}: {exc}"
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        session = self._release_session_turn(session.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(session.session_id, turn.turn_id, "failed", {"error": turn.error_message}, **context)
        return session

    def _cancel_turn(self, turn: TurnRecord, *, reason: str | None = None, event_type: str = "cancelled") -> TurnRecord:
        if is_turn_terminal(turn):
            return turn
        context = self._turn_context(turn)
        for approval_id in turn.approval_ids:
            approval = self.storage.load_approval(approval_id)
            if approval.status != ApprovalStatus.PENDING:
                continue
            approval.status = ApprovalStatus.REJECTED
            approval.reason = reason or "Turn cancelled."
            approval.resolved_at = utc_now()
            self.storage.save_approval(approval)
            self._pending_approvals.pop(approval_id, None)
            self._emit(
                turn.session_id,
                turn.turn_id,
                "approval_resolved",
                {"approval_id": approval_id, "status": approval.status},
                **context,
            )
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.CANCELLED
        turn.error_message = reason or turn.error_message
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        self._release_session_turn(turn.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(turn.session_id, turn.turn_id, event_type, {"reason": reason}, **context)
        return turn

    def _supersede_turn(self, turn: TurnRecord, *, new_turn_id: str) -> TurnRecord:
        if is_turn_terminal(turn):
            return turn
        context = self._turn_context(turn)
        for approval_id in turn.approval_ids:
            approval = self.storage.load_approval(approval_id)
            if approval.status != ApprovalStatus.PENDING:
                continue
            approval.status = ApprovalStatus.SUPERSEDED
            approval.reason = f"Superseded by turn {new_turn_id}."
            approval.resolved_at = utc_now()
            self.storage.save_approval(approval)
            self._pending_approvals.pop(approval_id, None)
            self._emit(
                turn.session_id,
                turn.turn_id,
                "approval_superseded",
                {"old_approval_id": approval_id, "new_turn_id": new_turn_id, "reason": f"Superseded by turn {new_turn_id}."},
                **context,
            )
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.SUPERSEDED
        turn.error_message = f"Superseded by turn {new_turn_id}."
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        self._release_session_turn(turn.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(
            turn.session_id,
            turn.turn_id,
            "turn_superseded",
            {"new_turn_id": new_turn_id, "reason": turn.error_message},
            **context,
        )
        return self.storage.load_turn(turn.session_id, turn.turn_id)

    def _release_session_turn(self, session_id: str, turn_id: str, fallback_status: SessionStatus) -> SessionRecord:
        def updater(session: SessionRecord) -> SessionRecord:
            session.pending_approval_ids = [item for item in session.pending_approval_ids if item not in self.storage.find_turn(turn_id).approval_ids]
            if session.active_turn_id == turn_id:
                session.active_turn_id = None
                session.status = fallback_status
            return session

        return self.storage.update_session(session_id, updater)

    def _default_decisions(self, pending: PendingApproval, *, approved: bool, reason: str | None) -> list[dict[str, Any]]:
        request = pending.request if isinstance(pending.request, dict) else {}
        action_requests = request.get("action_requests", [])
        decision = {"type": "approve"} if approved else {"type": "reject", "message": reason or "Rejected by user."}
        return [decision for _ in action_requests] or [decision]

    def _approval_decisions(self, pending: PendingApproval | None, *, approved: bool, reason: str | None) -> list[dict[str, Any]]:
        if pending is None:
            return [{"type": "approve"}] if approved else [{"type": "reject", "message": reason or "Rejected by user."}]
        return self._default_decisions(pending, approved=approved, reason=reason)

    def _serialize_pending_approval(self, approval: ApprovalRecord) -> dict[str, Any]:
        payload = approval.model_dump(mode="json")
        name, reason = self._approval_display(approval)
        payload["name"] = name
        payload["reason"] = reason
        return payload

    def _approval_display(self, approval: ApprovalRecord) -> tuple[str, str]:
        pending = self._pending_approvals.get(approval.approval_id)
        request = pending.request if pending and isinstance(pending.request, dict) else {}
        action_requests = request.get("action_requests", [])
        first = next((item for item in action_requests if isinstance(item, dict)), {})
        name = str(
            request.get("tool_name")
            or request.get("name")
            or first.get("tool")
            or first.get("tool_name")
            or first.get("name")
            or first.get("action_type")
            or approval.requested_by
            or approval.approval_id
        )
        reason = request.get("reason") or request.get("message") or request.get("review_summary")
        if not reason:
            reason = first.get("reason") or first.get("description") or first.get("summary")
        return name, str(reason or "This turn is awaiting approval.")

    def _merge_permissions(self, current: SessionPermissionOverrides, incoming: SessionPermissionOverrides) -> SessionPermissionOverrides:
        merged = current.model_copy(deep=True)
        merged.tool_rules.update(incoming.tool_rules)
        merged.mcp_server_rules.update(incoming.mcp_server_rules)
        merged.risk_tag_rules.update(incoming.risk_tag_rules)
        if incoming.auto_approve:
            merged.auto_approve = True
        if incoming.budget_override is not None:
            merged.budget_override = incoming.budget_override
        return merged

    def _merge_list(self, current: list[str], add: list[str], remove: list[str]) -> list[str]:
        items = [item for item in current if item not in remove]
        for item in add:
            if item not in items:
                items.append(item)
        return items

    def _budget_usage(self, turn: TurnRecord):
        return compute_budget_usage(turn.task_graph, started_at=turn.started_at or turn.created_at, now=utc_now())
