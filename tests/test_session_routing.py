from __future__ import annotations

import pytest

from digagent.models import IntentProfile, PlanningBundle, Scope, TaskGraph, TaskNode, TaskNodeKind, TaskNodeStatus, UserTurnDisposition
from digagent.tools import ToolExecutionResult

from tests.helpers import wait_for_run


@pytest.mark.asyncio
async def test_session_routes_direct_answer_and_reject(manager):
    async def fake_fetch(arguments):
        return ToolExecutionResult(
            title="Web Fetch: https://fixture.test",
            summary="Fetched fixture.test with status 200.",
            raw_output='{"title":"Fixture Site","status_code":200}',
            structured_facts=[
                {"key": "status_code", "value": 200},
                {"key": "title", "value": "Fixture Site"},
                {"key": "link_count", "value": 1},
            ],
            mime_type="application/json",
            artifact_kind="html",
            source={"tool_name": "web_fetch", "url": "https://fixture.test"},
        )

    manager.tools.web_fetch = fake_fetch
    session = manager.create_session(
        title="routing",
        profile_name="sisyphus-default",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="请分析 https://fixture.test",
        scope=Scope(allowed_domains=["fixture.test"]),
    )
    paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_approval", "failed"})
    assert paused.status.value == "awaiting_approval"

    _, answer = await manager.handle_message(session_id=session.session_id, content="为什么需要审批？")
    assert answer.disposition == UserTurnDisposition.DIRECT_ANSWER
    assert "高风险" in (answer.assistant_message or "")

    _, reject = await manager.handle_message(session_id=session.session_id, content="再分析一下当前项目源码")
    assert reject.disposition == UserTurnDisposition.REJECT
    session_after = manager.storage.load_session(session.session_id)
    assert session_after.run_ids == [turn.run_id]


@pytest.mark.asyncio
async def test_continue_run_from_awaiting_user_input(manager):
    session = manager.create_session(title="clarify", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(session_id=session.session_id, content="帮我分析一下")
    paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_user_input", "failed"})
    assert paused.status.value == "awaiting_user_input"
    assistant_messages = [message for message in manager.list_messages(session.session_id) if message.role.value == "assistant"]
    assert assistant_messages[-1].content != "当前任务范围不足，请补充更具体的信息，例如仓库路径、目标域名或题目附件。"
    assert "我" in assistant_messages[-1].content

    _, continued = await manager.handle_message(session_id=session.session_id, content="请对当前项目做一次源码分析并生成报告")
    assert continued.disposition == UserTurnDisposition.CONTINUE_RUN
    assert continued.run_id == turn.run_id

    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert completed.status.value == "completed"
    assert completed.report_id


@pytest.mark.asyncio
async def test_question_during_clarify_stays_direct_answer(manager):
    session = manager.create_session(title="clarify-qa", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(session_id=session.session_id, content="hello world")
    paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_user_input", "failed"})
    assert paused.status.value == "awaiting_user_input"

    _, answer = await manager.handle_message(session_id=session.session_id, content="解释一下什么是CTF")
    assert answer.disposition == UserTurnDisposition.DIRECT_ANSWER
    assert "Capture The Flag" in (answer.assistant_message or "")

    still_paused = manager.storage.find_run(turn.run_id)
    assert still_paused.status.value == "awaiting_user_input"
    assert all(node.owner_profile_name != "hackey-ctf" for node in still_paused.task_graph.nodes if node.kind == TaskNodeKind.SUBAGENT)


@pytest.mark.asyncio
async def test_multiple_commands_single_message_stays_single_run(manager, repo_root):
    session = manager.create_session(
        title="multi-intent",
        profile_name="sisyphus-default",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    _, turn = await manager.handle_message(
        session_id=session.session_id,
        content="请对当前项目做一次源码分析并生成报告，然后总结重点模块",
        scope=Scope(repo_paths=[str(repo_root)]),
    )
    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert completed.status.value == "completed"
    assert completed.followup_messages == ["总结重点模块"]
    session_after = manager.storage.load_session(session.session_id)
    assert len(session_after.run_ids) == 1


@pytest.mark.asyncio
async def test_planner_entrypoint_is_used(manager):
    called: dict[str, TaskGraph | bool] = {"value": False}
    original = manager.agent.build_test_planning_bundle

    async def fake_plan_task_graph(**kwargs):
        called["value"] = True
        return original(
            run_id=kwargs["run_id"],
            task=kwargs["task"],
            scope=Scope.model_validate(kwargs["scope"]),
            followup_messages=kwargs.get("followup_messages"),
        )

    manager.agent.plan_task_graph = fake_plan_task_graph
    session = manager.create_session(title="planner", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(session_id=session.session_id, content="请对当前项目做一次源码分析并生成报告")
    completed = await wait_for_run(manager, turn.run_id, statuses={"completed", "failed"})
    assert completed.status.value == "completed"
    assert called["value"] is True
    assistant_messages = [message.content for message in manager.list_messages(session.session_id) if message.role.value == "assistant"]
    assert any("任务图" in message or "目标" in message for message in assistant_messages)


@pytest.mark.asyncio
async def test_archived_session_still_answers_questions(manager):
    session = manager.create_session(title="archived", profile_name="sisyphus-default")
    manager.archive_session(session.session_id)

    _, turn = await manager.handle_message(session_id=session.session_id, content="这个会话现在还能做什么？")
    assert turn.disposition == UserTurnDisposition.DIRECT_ANSWER
    assert "archived" in (turn.assistant_message or "")
    session_after = manager.storage.load_session(session.session_id)
    assert session_after.run_ids == []


@pytest.mark.asyncio
async def test_waiting_user_input_uses_metadata_question(manager):
    question = "你好！请问今天有什么具体的任务需要我帮您处理吗？"

    async def fake_plan_task_graph(**kwargs):
        return PlanningBundle(
            intent_profile=IntentProfile(
                objective="澄清任务需求",
                labels=["general"],
                report_kind_hint="analysis_note",
                confidence=0.9,
            ),
            planner_message="我先确认一下你今天要做的具体任务。",
            clarify_message=question,
            task_graph=TaskGraph(
                run_id=kwargs["run_id"],
                nodes=[
                    TaskNode(
                        node_id="clarify_intent",
                        title="澄清任务需求",
                        kind=TaskNodeKind.INPUT,
                        status=TaskNodeStatus.WAITING_USER_INPUT,
                        description="用户发送了问候语，需要明确具体的任务指令以开始工作。",
                        summary="等待用户提供具体任务描述",
                        metadata={"question": question},
                    )
                ],
                edges=[],
            ),
        )

    manager.agent.plan_task_graph = fake_plan_task_graph
    session = manager.create_session(title="hello", profile_name="sisyphus-default")
    _, turn = await manager.handle_message(session_id=session.session_id, content="你好")
    paused = await wait_for_run(manager, turn.run_id, statuses={"awaiting_user_input", "failed"})
    assert paused.status.value == "awaiting_user_input"
    assert paused.awaiting_reason == question
    messages = [message.content for message in manager.list_messages(session.session_id) if message.role.value == "assistant"]
    assert messages[-1] == question

    await manager.execute_run(turn.run_id)
    messages_after = [message.content for message in manager.list_messages(session.session_id) if message.role.value == "assistant"]
    assert messages_after.count(question) == 1
