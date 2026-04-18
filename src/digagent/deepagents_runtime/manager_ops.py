from __future__ import annotations

from typing import Any

from digagent.deepagents_runtime.state import PendingApproval, to_event_data
from digagent.deepagents_runtime.streaming import compute_budget_usage
from digagent.deepagents_runtime.turns import is_turn_terminal
from digagent.deepagents_runtime.session_ops import TurnManagerSessionMixin
from digagent.models import (
    ApprovalRecord,
    ApprovalStatus,
    MessageRecord,
    MessageRole,
    Scope,
    SessionPermissionOverrides,
    SessionRecord,
    SessionStatus,
    TurnEvent,
    TurnRecord,
    TurnStatus,
)
from digagent.utils import action_digest, new_id, utc_now


class TurnManagerOpsMixin(TurnManagerSessionMixin):
    def _append_message(self, session_id: str, turn_id: str | None, content: str, role: MessageRole) -> MessageRecord:
        message = MessageRecord(
            message_id=new_id("msg"),
            session_id=session_id,
            turn_id=turn_id,
            role=role,
            sender="user" if role == MessageRole.USER else "assistant",
            content=content,
            created_at=utc_now(),
        )
        self.storage.append_message(message)
        return message

    def _emit(self, session_id: str, turn_id: str | None, event_type: str, data: dict[str, Any]) -> TurnEvent:
        event = TurnEvent(
            event_id=new_id("evt"),
            session_id=session_id,
            turn_id=turn_id,
            type=event_type,
            data=to_event_data(data),
            created_at=utc_now(),
        )
        self.storage.append_turn_event(session_id, event)
        return event

    def _update_session_metadata(self, session: SessionRecord, *, profile_name: str, title: str | None, scope: Scope) -> SessionRecord:
        session.root_agent_profile = profile_name
        if title:
            session.title = title
        if any([scope.repo_paths, scope.allowed_domains, scope.artifacts]):
            session.scope = scope
        self.storage.save_session(session)
        return session

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

    def _complete_turn(self, session: SessionRecord, turn: TurnRecord, assistant_text: str):
        assistant_message = self._append_message(session.session_id, turn.turn_id, assistant_text, MessageRole.ASSISTANT)
        self._emit(
            session.session_id,
            turn.turn_id,
            "assistant_message",
            {"message_id": assistant_message.message_id, "message": assistant_text, "turn_id": turn.turn_id},
        )
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.COMPLETED
        turn.approval_ids = []
        turn.awaiting_reason = None
        turn.final_response = assistant_text
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        session = self._release_session_turn(session.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(session.session_id, turn.turn_id, "completed", {"message": assistant_text})
        return session, assistant_message

    def _store_interrupts(self, session: SessionRecord, turn: TurnRecord, interrupts: tuple[Any, ...]):
        approval_ids: list[str] = []
        for interrupt in interrupts:
            approval_id = new_id("apr")
            record = ApprovalRecord(
                approval_id=approval_id,
                action_id=interrupt.id,
                turn_id=turn.turn_id,
                status=ApprovalStatus.PENDING,
                action_digest=action_digest(to_event_data(interrupt.value)),
                requested_by=turn.profile_name,
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
            )
        turn.status = TurnStatus.AWAITING_APPROVAL
        turn.approval_ids = approval_ids
        turn.awaiting_reason = "Turn is awaiting approval."
        self.storage.save_turn(turn)
        session.status = SessionStatus.AWAITING_APPROVAL
        session.active_turn_id = turn.turn_id
        session.pending_approval_ids = approval_ids
        self.storage.save_session(session)
        self._emit(session.session_id, turn.turn_id, "awaiting_approval", {"approval_ids": approval_ids, "interrupts": [item for item in interrupts]})
        return session

    def _fail_turn(self, session: SessionRecord, turn: TurnRecord, exc: Exception) -> SessionRecord:
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.FAILED
        turn.approval_ids = []
        turn.error_message = f"{type(exc).__name__}: {exc}"
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        session = self._release_session_turn(session.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(session.session_id, turn.turn_id, "failed", {"error": turn.error_message})
        return session

    def _cancel_turn(self, turn: TurnRecord, *, reason: str | None = None, event_type: str = "cancelled") -> TurnRecord:
        if is_turn_terminal(turn):
            return turn
        for approval_id in turn.approval_ids:
            approval = self.storage.load_approval(approval_id)
            if approval.status != ApprovalStatus.PENDING:
                continue
            approval.status = ApprovalStatus.REJECTED
            approval.reason = reason or "Turn cancelled."
            approval.resolved_at = utc_now()
            self.storage.save_approval(approval)
            self._pending_approvals.pop(approval_id, None)
            self._emit(turn.session_id, turn.turn_id, "approval_resolved", {"approval_id": approval_id, "status": approval.status})
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.CANCELLED
        turn.error_message = reason or turn.error_message
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        self._release_session_turn(turn.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(turn.session_id, turn.turn_id, event_type, {"reason": reason})
        return turn

    def _supersede_turn(self, turn: TurnRecord, *, new_turn_id: str) -> TurnRecord:
        if is_turn_terminal(turn):
            return turn
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
            )
        turn.budget_usage = self._budget_usage(turn)
        turn.status = TurnStatus.SUPERSEDED
        turn.error_message = f"Superseded by turn {new_turn_id}."
        turn.finished_at = utc_now()
        self.storage.save_turn(turn)
        self._release_session_turn(turn.session_id, turn.turn_id, SessionStatus.IDLE)
        self._emit(turn.session_id, turn.turn_id, "turn_superseded", {"new_turn_id": new_turn_id, "reason": turn.error_message})
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
