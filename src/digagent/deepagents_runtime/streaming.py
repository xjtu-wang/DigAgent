from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from digagent.deepagents_runtime.state import to_event_data
from digagent.models import BudgetUsage, TaskGraph, TaskNodeKind, TaskNodeStatus

RUNNING_STATUSES = {TaskNodeStatus.RUNNING.value}
USED_STATUSES = {
    TaskNodeStatus.RUNNING.value,
    TaskNodeStatus.WAITING_APPROVAL.value,
    TaskNodeStatus.WAITING_USER_INPUT.value,
    TaskNodeStatus.COMPLETED.value,
    TaskNodeStatus.FAILED.value,
    TaskNodeStatus.BLOCKED.value,
}
TOOL_KEYWORDS = ("tool", "tools", "execute", "shell", "search", "fetch", "read", "write", "edit")
SUBAGENT_KEYWORDS = ("subagent", "delegate", "task")
REPORT_KEYWORDS = ("report", "summary", "aggregate")
EXPORT_KEYWORDS = ("export", "download")
MAX_PREVIEW_CHARS = 240


def coerce_stream_part(chunk: Any) -> tuple[str, Any, tuple[str, ...]]:
    if isinstance(chunk, dict) and "type" in chunk:
        return str(chunk["type"]), chunk.get("data"), tuple(chunk.get("ns") or ())
    if isinstance(chunk, tuple) and len(chunk) == 2:
        mode, data = chunk
        return str(mode), data, ()
    return "values", chunk, ()


def ensure_task_graph(turn_id: str, graph: TaskGraph | None) -> TaskGraph:
    return graph.model_copy(deep=True) if graph is not None else TaskGraph(turn_id=turn_id)


def apply_stream_part(
    graph: TaskGraph | None,
    *,
    turn_id: str,
    mode: str,
    data: Any,
    ns: tuple[str, ...],
) -> tuple[TaskGraph, list[tuple[str, dict[str, Any]]], bool]:
    current = ensure_task_graph(turn_id, graph)
    if mode == "tasks":
        return _apply_task_payload(current, data, ns)
    if mode == "updates":
        return _apply_update_payload(current, data, ns)
    return current, [], False


def compute_budget_usage(graph: TaskGraph | None, *, started_at: str | None, now: str) -> BudgetUsage:
    if graph is None:
        return BudgetUsage(runtime_seconds_used=_elapsed_seconds(started_at, now))
    active_tools = 0
    active_subagents = 0
    tool_calls_used = 0
    for node in graph.nodes:
        status = str(node.status)
        kind = str(node.kind)
        if kind == TaskNodeKind.TOOL.value and status in USED_STATUSES:
            tool_calls_used += 1
        if status not in RUNNING_STATUSES:
            continue
        if kind == TaskNodeKind.TOOL.value:
            active_tools += 1
        if kind == TaskNodeKind.SUBAGENT.value:
            active_subagents += 1
    return BudgetUsage(
        tool_calls_used=tool_calls_used,
        runtime_seconds_used=_elapsed_seconds(started_at, now),
        active_subagents=active_subagents,
        active_tools=active_tools,
    )


def _apply_task_payload(
    graph: TaskGraph,
    data: Any,
    ns: tuple[str, ...],
) -> tuple[TaskGraph, list[tuple[str, dict[str, Any]]], bool]:
    payload = graph.model_dump(mode="json")
    node = _task_node_payload(payload["nodes"], data, ns)
    if node is None:
        return graph, [], False
    index = _node_index(payload["nodes"], node["node_id"])
    if index is None:
        payload["nodes"].append(node)
    else:
        payload["nodes"][index] = {**payload["nodes"][index], **node}
    next_graph = TaskGraph.model_validate(payload)
    event_type = _task_event_type(node)
    event_data = {
        "node_id": node["node_id"],
        "title": node["title"],
        "status": node["status"],
        "summary": node.get("summary") or node["description"],
        "metadata": node["metadata"],
    }
    events = [(event_type, event_data)]
    return next_graph, events, True


def _apply_update_payload(
    graph: TaskGraph,
    data: Any,
    ns: tuple[str, ...],
) -> tuple[TaskGraph, list[tuple[str, dict[str, Any]]], bool]:
    if not isinstance(data, dict) or not data:
        return graph, [], False
    payload = graph.model_dump(mode="json")
    first_name = next(iter(data))
    index = _find_node_by_title(payload["nodes"], first_name)
    if index is None:
        return graph, [], False
    node = payload["nodes"][index]
    update_preview = _preview(data[first_name])
    metadata = dict(node.get("metadata") or {})
    metadata["last_update"] = to_event_data(data[first_name])
    metadata["ns"] = list(ns)
    node["metadata"] = metadata
    if update_preview:
        node["summary"] = update_preview
    payload["nodes"][index] = node
    next_graph = TaskGraph.model_validate(payload)
    event = {
        "op_type": "UPDATE_NODE",
        "node_id": node["node_id"],
        "title": node["title"],
        "summary": update_preview or node.get("description") or node["title"],
    }
    return next_graph, [("graph_op_applied", event)], True


def _task_node_payload(nodes: list[dict[str, Any]], data: Any, ns: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    name = str(data.get("name") or data.get("id") or "task")
    node_id = str(data.get("id") or name)
    existing = _existing_node(nodes, node_id)
    metadata = dict(existing.get("metadata") or {})
    metadata["ns"] = list(ns)
    metadata["task_id"] = node_id
    status = _task_status(data)
    summary = _task_summary(data)
    metadata["payload"] = to_event_data(data)
    node = {
        "node_id": node_id,
        "title": name,
        "kind": _task_kind(name),
        "status": status,
        "description": summary or name,
        "summary": summary or None,
        "depends_on": existing.get("depends_on") or _default_depends_on(nodes),
        "children": existing.get("children") or [],
        "block_reason": _block_reason(data),
        "metadata": metadata,
    }
    return {**existing, **node}


def _task_kind(name: str) -> str:
    lowered = name.lower()
    if any(token in lowered for token in TOOL_KEYWORDS):
        return TaskNodeKind.TOOL.value
    if any(token in lowered for token in SUBAGENT_KEYWORDS):
        return TaskNodeKind.SUBAGENT.value
    if any(token in lowered for token in EXPORT_KEYWORDS):
        return TaskNodeKind.EXPORT.value
    if any(token in lowered for token in REPORT_KEYWORDS):
        return TaskNodeKind.REPORT.value
    return TaskNodeKind.AGGREGATE.value


def _task_status(data: dict[str, Any]) -> str:
    if data.get("interrupts"):
        return TaskNodeStatus.WAITING_APPROVAL.value
    if data.get("error"):
        return TaskNodeStatus.FAILED.value
    if "result" in data:
        return TaskNodeStatus.COMPLETED.value
    return TaskNodeStatus.RUNNING.value


def _task_event_type(node: dict[str, Any]) -> str:
    status = node["status"]
    if status == TaskNodeStatus.RUNNING.value:
        return "task_node_started"
    if status == TaskNodeStatus.WAITING_APPROVAL.value:
        return "task_node_waiting_approval"
    if status == TaskNodeStatus.WAITING_USER_INPUT.value:
        return "task_node_waiting_user_input"
    return "task_node_completed"


def _task_summary(data: dict[str, Any]) -> str:
    if data.get("error"):
        return _preview(data["error"])
    if data.get("interrupts"):
        return _preview(data["interrupts"])
    if "result" in data:
        return _preview(data["result"])
    if "input" in data:
        return _preview(data["input"])
    return ""


def _block_reason(data: dict[str, Any]) -> str | None:
    if data.get("interrupts"):
        return _preview(data["interrupts"])
    if data.get("error"):
        return _preview(data["error"])
    return None


def _default_depends_on(nodes: list[dict[str, Any]]) -> list[str]:
    if not nodes:
        return []
    return [str(nodes[-1]["node_id"])]


def _existing_node(nodes: list[dict[str, Any]], node_id: str) -> dict[str, Any]:
    index = _node_index(nodes, node_id)
    return {} if index is None else dict(nodes[index])


def _node_index(nodes: list[dict[str, Any]], node_id: str) -> int | None:
    for index, node in enumerate(nodes):
        if str(node.get("node_id")) == node_id:
            return index
    return None


def _find_node_by_title(nodes: list[dict[str, Any]], title: str) -> int | None:
    for index in range(len(nodes) - 1, -1, -1):
        if str(nodes[index].get("title")) == title:
            return index
    return None


def _elapsed_seconds(started_at: str | None, now: str) -> float:
    if not started_at:
        return 0.0
    started = _parse_timestamp(started_at)
    current = _parse_timestamp(now)
    return max(0.0, (current - started).total_seconds())


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _preview(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        normalized = " ".join(value.split())
        return normalized[:MAX_PREVIEW_CHARS]
    rendered = json.dumps(to_event_data(value), ensure_ascii=False, sort_keys=True)
    compact = " ".join(rendered.split())
    return compact[:MAX_PREVIEW_CHARS]
