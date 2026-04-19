from __future__ import annotations

import json

from digagent.models import ApprovalRecord, ApprovalStatus, MessageRecord, RuntimeBudget, Scope, TurnEvent


def test_create_turn_persists_turn_ids_into_session(storage) -> None:
    session = storage.create_session("turn-storage", "sisyphus-default", Scope())
    turn = storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="inspect repo",
        scope=Scope(),
        budget=RuntimeBudget(),
        auto_approve=True,
        trigger_message_id="msg_seed_turn",
    )

    reloaded_session = storage.load_session(session.session_id)
    turns = storage.list_turns(session.session_id)

    assert reloaded_session.turn_ids == [turn.turn_id]
    assert turns[0].turn_id == turn.turn_id
    assert storage.find_turn(turn.turn_id).trigger_message_id == "msg_seed_turn"


def test_turn_event_storage_round_trips_turn_and_session_streams(storage) -> None:
    session = storage.create_session("turn-events", "sisyphus-default", Scope())
    turn = storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="stream events",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    turn_event = TurnEvent(
        event_id="evt_turn_started",
        session_id=session.session_id,
        turn_id=turn.turn_id,
        type="turn_started",
        data={"turn_id": turn.turn_id},
        created_at="2026-04-18T12:00:00Z",
    )
    session_event = TurnEvent(
        event_id="evt_session_note",
        session_id=session.session_id,
        turn_id=None,
        type="session_note",
        data={"message": "session scoped"},
        created_at="2026-04-18T12:00:01Z",
    )

    storage.append_turn_event(session.session_id, turn_event)
    storage.append_turn_event(session.session_id, session_event)

    assert storage.load_turn_events(session.session_id, turn.turn_id) == [turn_event.model_dump(mode="json")]
    assert storage.load_turn_events(session.session_id, "session") == [session_event.model_dump(mode="json")]


def test_participant_metadata_round_trips_across_session_turn_message_and_event(storage) -> None:
    session = storage.create_session("participant-metadata", "sisyphus-default", Scope())
    session.speaker_profile = "prometheus-planner"
    session.addressed_participants = ["hephaestus-deepworker", "prometheus-planner"]
    session.participant_profile = "prometheus-planner"
    session.handoff_from = "hephaestus-deepworker"
    session.handoff_to = "prometheus-planner"
    storage.save_session(session)
    turn = storage.create_turn(
        session_id=session.session_id,
        profile_name="hephaestus-deepworker",
        task="participant metadata",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    turn.speaker_profile = "prometheus-planner"
    turn.addressed_participants = ["hephaestus-deepworker", "prometheus-planner"]
    turn.participant_profile = "prometheus-planner"
    turn.handoff_from = "hephaestus-deepworker"
    turn.handoff_to = "prometheus-planner"
    storage.save_turn(turn)
    message = MessageRecord(
        message_id="msg_participant",
        session_id=session.session_id,
        turn_id=turn.turn_id,
        role="assistant",
        sender="assistant",
        content="participant reply",
        speaker_profile="prometheus-planner",
        addressed_participants=["hephaestus-deepworker", "prometheus-planner"],
        participant_profile="prometheus-planner",
        handoff_from="hephaestus-deepworker",
        handoff_to="prometheus-planner",
        created_at="2026-04-19T01:00:00Z",
    )
    event = TurnEvent(
        event_id="evt_participant",
        session_id=session.session_id,
        turn_id=turn.turn_id,
        type="assistant_message",
        data={"message": "participant reply"},
        speaker_profile="prometheus-planner",
        addressed_participants=["hephaestus-deepworker", "prometheus-planner"],
        participant_profile="prometheus-planner",
        handoff_from="hephaestus-deepworker",
        handoff_to="prometheus-planner",
        created_at="2026-04-19T01:00:01Z",
    )

    storage.append_message(message)
    storage.append_turn_event(session.session_id, event)

    reloaded_session = storage.load_session(session.session_id)
    reloaded_turn = storage.load_turn(session.session_id, turn.turn_id)
    reloaded_message = storage.load_messages(session.session_id)[0]
    reloaded_event = TurnEvent.model_validate(storage.load_turn_events(session.session_id, turn.turn_id)[0])

    assert reloaded_session.handoff_to == "prometheus-planner"
    assert reloaded_turn.addressed_participants == ["hephaestus-deepworker", "prometheus-planner"]
    assert reloaded_message.speaker_profile == "prometheus-planner"
    assert reloaded_event.handoff_from == "hephaestus-deepworker"


def test_list_approvals_filters_pending_records_by_turn_id(storage) -> None:
    session = storage.create_session("turn-approvals", "sisyphus-default", Scope())
    turn_a = storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="needs approval",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    turn_b = storage.create_turn(
        session_id=session.session_id,
        profile_name="sisyphus-default",
        task="other approval",
        scope=Scope(),
        budget=RuntimeBudget(),
    )
    superseded = ApprovalRecord(
        approval_id="apr_old_turn_a",
        action_id="act_old_turn_a",
        turn_id=turn_a.turn_id,
        status=ApprovalStatus.SUPERSEDED,
        action_digest="sha256:old-turn-a",
        requested_by="sisyphus-default",
        requested_at="2026-04-18T12:00:00Z",
        superseded_by="apr_new_turn_a",
    )
    pending = ApprovalRecord(
        approval_id="apr_new_turn_a",
        action_id="act_new_turn_a",
        turn_id=turn_a.turn_id,
        status=ApprovalStatus.PENDING,
        action_digest="sha256:new-turn-a",
        requested_by="sisyphus-default",
        requested_at="2026-04-18T12:00:01Z",
        parent_approval_id="apr_old_turn_a",
    )
    other_turn = ApprovalRecord(
        approval_id="apr_turn_b",
        action_id="act_turn_b",
        turn_id=turn_b.turn_id,
        status=ApprovalStatus.PENDING,
        action_digest="sha256:turn-b",
        requested_by="sisyphus-default",
        requested_at="2026-04-18T12:00:02Z",
    )

    storage.save_approval(superseded)
    storage.save_approval(pending)
    storage.save_approval(other_turn)

    approvals = storage.list_approvals(turn_id=turn_a.turn_id, status=ApprovalStatus.PENDING)

    assert [item.approval_id for item in approvals] == ["apr_new_turn_a"]


def test_list_approvals_skips_legacy_run_schema_files(storage) -> None:
    legacy_payload = {
        "approval_id": "apr_legacy_run",
        "action_id": "act_legacy_run",
        "run_id": "run_legacy_only",
        "status": "pending",
        "action_digest": "sha256:legacy-run",
        "requested_by": "sisyphus-default",
        "requested_at": "2026-04-18T12:00:00Z",
        "resolved_at": None,
        "resolver": None,
        "reason": None,
        "challenge": None,
        "challenge_issued_at": None,
        "challenge_expires_at": None,
        "policy_key": None,
        "kind": "primary",
        "parent_approval_id": None,
        "superseded_by": None,
        "node_id": None,
    }
    storage.approval_path("apr_legacy_run").parent.mkdir(parents=True, exist_ok=True)
    storage.approval_path("apr_legacy_run").write_text(json.dumps(legacy_payload), encoding="utf-8")
    valid = ApprovalRecord(
        approval_id="apr_valid_turn",
        action_id="act_valid_turn",
        turn_id="turn_valid_turn",
        status=ApprovalStatus.PENDING,
        action_digest="sha256:valid-turn",
        requested_by="sisyphus-default",
        requested_at="2026-04-18T12:00:01Z",
    )

    storage.save_approval(valid)

    approvals = storage.list_approvals(status=ApprovalStatus.PENDING)

    assert [item.approval_id for item in approvals] == ["apr_valid_turn"]
