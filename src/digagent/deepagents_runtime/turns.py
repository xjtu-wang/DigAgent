from __future__ import annotations

from datetime import UTC, datetime
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
    session = storage.load_session(session_id)
    turn_order = {
        turn_id: index
        for index, turn_id in enumerate([SESSION_EVENT_TURN_ID, *session.turn_ids])
    }
    events: list[TurnEvent] = []
    for turn_id in [SESSION_EVENT_TURN_ID, *session.turn_ids]:
        events.extend(load_turn_events(storage, session_id, turn_id))
    ordered = sorted(events, key=lambda item: _session_sort_key(item, turn_order))
    return _with_session_event_indices(ordered)


def load_turn_events(storage: Any, session_id: str, turn_id: str) -> list[TurnEvent]:
    return _with_turn_event_indices(_coerce_events(storage.load_turn_events(session_id, turn_id)))


def turn_stream_stopped(turn: TurnRecord) -> bool:
    return turn.status in TERMINAL_TURN_STATUSES | {TurnStatus.AWAITING_APPROVAL, TurnStatus.AWAITING_USER_INPUT}


def _coerce_events(rows: list[dict[str, Any]]) -> list[TurnEvent]:
    return [TurnEvent.model_validate(row) for row in rows]


def _with_turn_event_indices(events: list[TurnEvent]) -> list[TurnEvent]:
    indexed: list[TurnEvent] = []
    for index, event in enumerate(events, start=1):
        indexed.append(event.model_copy(update={"turn_event_index": index}))
    return indexed


def _with_session_event_indices(events: list[TurnEvent]) -> list[TurnEvent]:
    indexed: list[TurnEvent] = []
    for index, event in enumerate(events, start=1):
        indexed.append(event.model_copy(update={"session_event_index": index}))
    return indexed


def _session_sort_key(event: TurnEvent, turn_order: dict[str, int]) -> tuple[datetime, int, int]:
    return (
        _parse_event_time(event.created_at),
        turn_order.get(event.turn_id or SESSION_EVENT_TURN_ID, len(turn_order)),
        event.turn_event_index or 0,
    )


def _parse_event_time(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
