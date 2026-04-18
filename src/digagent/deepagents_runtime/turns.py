from __future__ import annotations

from typing import Any

from digagent.models import TurnEvent, TurnRecord, TurnStatus

SESSION_EVENT_TURN_ID = "session"
POLL_INTERVAL_SEC = 0.1

TERMINAL_TURN_STATUSES = {
    TurnStatus.COMPLETED,
    TurnStatus.FAILED,
    TurnStatus.CANCELLED,
    TurnStatus.SUPERSEDED,
    TurnStatus.TIMED_OUT,
}


def is_turn_terminal(turn: TurnRecord) -> bool:
    return turn.status in TERMINAL_TURN_STATUSES


def load_session_events(storage: Any, session_id: str) -> list[TurnEvent]:
    turn_ids = [SESSION_EVENT_TURN_ID, *storage.load_session(session_id).turn_ids]
    events: list[TurnEvent] = []
    for turn_id in turn_ids:
        events.extend(_coerce_events(storage.load_turn_events(session_id, turn_id)))
    return sorted(events, key=lambda item: item.created_at)


def load_turn_events(storage: Any, session_id: str, turn_id: str) -> list[TurnEvent]:
    return _coerce_events(storage.load_turn_events(session_id, turn_id))


def turn_stream_stopped(turn: TurnRecord) -> bool:
    return turn.status in TERMINAL_TURN_STATUSES | {TurnStatus.AWAITING_APPROVAL, TurnStatus.AWAITING_USER_INPUT}


def _coerce_events(rows: list[dict[str, Any]]) -> list[TurnEvent]:
    return [TurnEvent.model_validate(row) for row in rows]
