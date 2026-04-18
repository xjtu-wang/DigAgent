from __future__ import annotations

import json
from typing import Any

from digagent.models import (
    ApprovalRecord,
    ApprovalStatus,
    MessageRecord,
    MessageRole,
    RuntimeBudget,
    Scope,
    SessionStatus,
    TurnEvent,
    TurnStatus,
    UserTurnDisposition,
    UserTurnResult,
)
from digagent.utils import new_id, utc_now


DEFAULT_PROFILE = "sisyphus-default"


def parse_sse_events(raw_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for chunk in raw_text.split("\n\n"):
        block = chunk.strip()
        if not block:
            continue
        data_lines = [line.removeprefix("data: ").strip() for line in block.splitlines() if line.startswith("data: ")]
        if data_lines:
            events.append(json.loads("\n".join(data_lines)))
    return events


def seed_completed_turn(
    manager: Any,
    *,
    session_id: str,
    content: str,
    assistant_text: str,
    profile_name: str = DEFAULT_PROFILE,
    auto_approve: bool = False,
    scope: Scope | None = None,
    emit_events: bool = True,
    title: str | None = None,
) -> tuple[Any, UserTurnResult]:
    session = _update_session_metadata(manager, session_id=session_id, scope=scope, title=title)
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name=profile_name,
        task=content,
        scope=session.scope,
        budget=RuntimeBudget(),
        auto_approve=auto_approve,
    )
    user_message = _append_message(manager, session_id=session.session_id, content=content, role=MessageRole.USER, turn_id=turn.turn_id)
    turn.trigger_message_id = user_message.message_id
    manager.storage.save_turn(turn)
    session = manager.storage.load_session(session.session_id)
    session.active_turn_id = turn.turn_id
    session.status = SessionStatus.ACTIVE_TURN
    manager.storage.save_session(session)
    if emit_events:
        _append_event(manager, session_id=session.session_id, turn_id=turn.turn_id, event_type="turn_started", data={"task": content, "profile_name": profile_name})
    assistant_message = _append_message(
        manager,
        session_id=session.session_id,
        content=assistant_text,
        role=MessageRole.ASSISTANT,
        turn_id=turn.turn_id,
    )
    turn.status = TurnStatus.COMPLETED
    turn.final_response = assistant_text
    turn.finished_at = utc_now()
    manager.storage.save_turn(turn)
    session = manager.storage.load_session(session.session_id)
    session.status = SessionStatus.IDLE
    session.active_turn_id = None
    manager.storage.save_session(session)
    if emit_events:
        _append_event(manager, session_id=session.session_id, turn_id=turn.turn_id, event_type="completed", data={"message": assistant_text})
    return session, UserTurnResult(
        disposition=UserTurnDisposition.CREATE_TURN,
        session_id=session.session_id,
        turn_id=turn.turn_id,
        message_id=assistant_message.message_id,
        assistant_message=assistant_text,
    )


def seed_pending_approval_turn(
    manager: Any,
    *,
    session_id: str,
    content: str,
    approval_id: str,
    profile_name: str = DEFAULT_PROFILE,
    auto_approve: bool = False,
    scope: Scope | None = None,
    title: str | None = None,
) -> tuple[Any, UserTurnResult]:
    session = _update_session_metadata(manager, session_id=session_id, scope=scope, title=title)
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name=profile_name,
        task=content,
        scope=session.scope,
        budget=RuntimeBudget(),
        auto_approve=auto_approve,
    )
    user_message = _append_message(manager, session_id=session.session_id, content=content, role=MessageRole.USER, turn_id=turn.turn_id)
    turn.trigger_message_id = user_message.message_id
    manager.storage.save_turn(turn)
    approval = ApprovalRecord(
        approval_id=approval_id,
        action_id=f"act_{approval_id}",
        turn_id=turn.turn_id,
        status=ApprovalStatus.PENDING,
        action_digest=f"sha256:{approval_id}",
        requested_by=profile_name,
        requested_at=utc_now(),
    )
    manager.storage.save_approval(approval)
    turn.status = TurnStatus.AWAITING_APPROVAL
    turn.approval_ids = [approval.approval_id]
    manager.storage.save_turn(turn)
    session = manager.storage.load_session(session.session_id)
    session.status = SessionStatus.AWAITING_APPROVAL
    session.active_turn_id = turn.turn_id
    session.pending_approval_ids = [approval.approval_id]
    manager.storage.save_session(session)
    _append_event(manager, session_id=session.session_id, turn_id=turn.turn_id, event_type="awaiting_approval", data={"approval_ids": [approval.approval_id]})
    return session, UserTurnResult(
        disposition=UserTurnDisposition.CREATE_TURN,
        session_id=session.session_id,
        turn_id=turn.turn_id,
        approval_ids=[approval.approval_id],
    )


def seed_superseded_approval_chain(
    manager: Any,
    *,
    session_id: str,
    content: str,
    old_approval_id: str,
    new_approval_id: str,
    profile_name: str = DEFAULT_PROFILE,
    policy_key: str = "tool:web_fetch",
    scope: Scope | None = None,
) -> tuple[Any, ApprovalRecord, ApprovalRecord]:
    session = _update_session_metadata(manager, session_id=session_id, scope=scope, title=None)
    turn = manager.storage.create_turn(
        session_id=session.session_id,
        profile_name=profile_name,
        task=content,
        scope=session.scope,
        budget=RuntimeBudget(),
    )
    user_message = _append_message(manager, session_id=session.session_id, content=content, role=MessageRole.USER, turn_id=turn.turn_id)
    turn.trigger_message_id = user_message.message_id
    manager.storage.save_turn(turn)
    old_approval = ApprovalRecord(
        approval_id=old_approval_id,
        action_id=f"act_{old_approval_id}",
        turn_id=turn.turn_id,
        status=ApprovalStatus.SUPERSEDED,
        action_digest=f"sha256:{old_approval_id}",
        policy_key=policy_key,
        requested_by=profile_name,
        requested_at=utc_now(),
        superseded_by=new_approval_id,
    )
    new_approval = ApprovalRecord(
        approval_id=new_approval_id,
        action_id=f"act_{new_approval_id}",
        turn_id=turn.turn_id,
        status=ApprovalStatus.PENDING,
        action_digest=f"sha256:{new_approval_id}",
        policy_key=policy_key,
        parent_approval_id=old_approval_id,
        requested_by=profile_name,
        requested_at=utc_now(),
    )
    manager.storage.save_approval(old_approval)
    manager.storage.save_approval(new_approval)
    turn.status = TurnStatus.AWAITING_APPROVAL
    turn.approval_ids = [old_approval.approval_id, new_approval.approval_id]
    manager.storage.save_turn(turn)
    session = manager.storage.load_session(session.session_id)
    session.status = SessionStatus.AWAITING_APPROVAL
    session.active_turn_id = turn.turn_id
    session.pending_approval_ids = [new_approval.approval_id]
    manager.storage.save_session(session)
    _append_event(
        manager,
        session_id=session.session_id,
        turn_id=turn.turn_id,
        event_type="approval_superseded",
        data={
            "old_approval_id": old_approval.approval_id,
            "new_approval_id": new_approval.approval_id,
            "policy_key": policy_key,
            "reason": "seeded supersede contract",
        },
    )
    return turn, old_approval, new_approval


def _update_session_metadata(
    manager: Any,
    *,
    session_id: str,
    scope: Scope | None,
    title: str | None,
) -> Any:
    session = manager.storage.load_session(session_id)
    if title:
        session.title = title
    if scope and any([scope.repo_paths, scope.allowed_domains, scope.artifacts]):
        session.scope = scope
    manager.storage.save_session(session)
    return session


def _append_message(
    manager: Any,
    *,
    session_id: str,
    content: str,
    role: MessageRole,
    turn_id: str | None = None,
) -> MessageRecord:
    message = MessageRecord(
        message_id=new_id("msg"),
        session_id=session_id,
        turn_id=turn_id,
        role=role,
        sender="user" if role == MessageRole.USER else "assistant",
        content=content,
        created_at=utc_now(),
    )
    manager.storage.append_message(message)
    return message


def _append_event(
    manager: Any,
    *,
    session_id: str,
    turn_id: str | None,
    event_type: str,
    data: dict[str, Any],
) -> TurnEvent:
    event = TurnEvent(
        event_id=new_id("evt"),
        session_id=session_id,
        turn_id=turn_id,
        type=event_type,
        data=data,
        created_at=utc_now(),
    )
    manager.storage.append_turn_event(session_id, event)
    return event
