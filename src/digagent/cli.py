from __future__ import annotations

import asyncio
import json

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel

from digagent.api import create_app
from digagent.models import Scope
from digagent.runtime import TurnManager

app = typer.Typer(help="DigAgent CLI")
console = Console()


def _parse_scope(repo: list[str], domain: list[str], artifact: list[str]) -> Scope:
    return Scope(repo_paths=repo, allowed_domains=domain, artifacts=artifact)


async def _print_new_events(manager: TurnManager, session_id: str, start_index: int, turn_id: str | None) -> int:
    stop_statuses = {"completed", "failed", "timed_out", "awaiting_approval", "awaiting_user_input"}
    while True:
        history = manager.load_session_event_history(session_id)
        emitted = False
        while start_index < len(history):
            event = history[start_index]
            start_index += 1
            if turn_id and event.turn_id not in {None, turn_id}:
                continue
            console.print(Panel(json.dumps(event.data, ensure_ascii=False, indent=2), title=event.type))
            emitted = True
            if event.turn_id == turn_id and event.type in stop_statuses:
                return start_index
        if emitted and not turn_id:
            return start_index
        await asyncio.sleep(0.05)


@app.command()
def run(
    task: str = typer.Option(..., "--task", help="Task to execute."),
    profile: str = typer.Option("sisyphus-default", "--profile"),
    repo: list[str] = typer.Option([], "--repo"),
    domain: list[str] = typer.Option([], "--domain"),
    artifact: list[str] = typer.Option([], "--artifact"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
) -> None:
    async def runner() -> None:
        manager = TurnManager()
        session = manager.create_session(title=task[:60], profile_name=profile, scope=_parse_scope(repo, domain, artifact))
        cursor = len(manager.load_session_event_history(session.session_id))
        _, result = await manager.handle_message(
            session_id=session.session_id,
            content=task,
            profile_name=profile,
            scope=_parse_scope(repo, domain, artifact),
            auto_approve=auto_approve,
        )
        if result.turn_id:
            await _print_new_events(manager, session.session_id, cursor, result.turn_id)
        elif result.assistant_message:
            console.print(result.assistant_message)

    asyncio.run(runner())


@app.command()
def chat(
    task: str = typer.Option("", "--task"),
    profile: str = typer.Option("sisyphus-default", "--profile"),
    repo: list[str] = typer.Option([], "--repo"),
    domain: list[str] = typer.Option([], "--domain"),
    artifact: list[str] = typer.Option([], "--artifact"),
    auto_approve: bool = typer.Option(False, "--auto-approve"),
) -> None:
    async def runner() -> None:
        manager = TurnManager()
        scope = _parse_scope(repo, domain, artifact)
        session = manager.create_session(title=(task or "DigAgent Session")[:60], profile_name=profile, scope=scope)
        if task:
            cursor = len(manager.load_session_event_history(session.session_id))
            _, result = await manager.handle_message(
                session_id=session.session_id,
                content=task,
                profile_name=profile,
                scope=scope,
                auto_approve=auto_approve,
            )
            if result.turn_id:
                await _print_new_events(manager, session.session_id, cursor, result.turn_id)
            elif result.assistant_message:
                console.print(result.assistant_message)
            return

        console.print(f"Session: {session.session_id}")
        while True:
            text = typer.prompt("Message").strip()
            if text.lower() in {"exit", "quit"}:
                break
            cursor = len(manager.load_session_event_history(session.session_id))
            _, result = await manager.handle_message(
                session_id=session.session_id,
                content=text,
                profile_name=profile,
                scope=scope,
                auto_approve=auto_approve,
            )
            if result.turn_id:
                await _print_new_events(manager, session.session_id, cursor, result.turn_id)
            elif result.assistant_message:
                console.print(result.assistant_message)

    asyncio.run(runner())


@app.command()
def approve(
    approval_id: str = typer.Argument(...),
    approved: bool = typer.Option(True, "--approved/--rejected"),
    resolver: str = typer.Option("cli", "--resolver"),
    reason: str = typer.Option("", "--reason"),
) -> None:
    async def runner() -> None:
        manager = TurnManager()
        approval = await manager.approve(
            approval_id,
            approved=approved,
            resolver=resolver,
            reason=reason or None,
        )
        console.print_json(data=approval.model_dump(mode="json"))

    asyncio.run(runner())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@app.command("tools-doctor")
def tools_doctor(
    query: str = typer.Option("example", "--query", help="web_search smoke query"),
    url: str = typer.Option("https://example.com", "--url", help="web_fetch smoke URL"),
) -> None:
    """对网络工具做健康检查，输出 OK / DEGRADED / FAIL。"""
    from digagent.config import AppSettings
    from digagent.toolsets.network import NetworkToolset

    async def runner() -> None:
        toolset = NetworkToolset(AppSettings())
        report: dict[str, dict] = {}
        try:
            _, summary, _, facts, source, _, _ = await toolset.web_search({"query": query, "limit": 5})
            fact_map = {f["key"]: f["value"] for f in facts}
            status = "OK"
            if not fact_map.get("provider_reachable", True):
                status = "FAIL"
            elif not fact_map.get("provider_usable", True):
                status = "FAIL"
            elif fact_map.get("empty_result"):
                status = "DEGRADED"
            report["web_search"] = {"status": status, "summary": summary, "facts": fact_map, "source": source}
        except Exception as exc:
            report["web_search"] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        try:
            _, summary, _, facts, source, _, _ = await toolset.web_fetch({"url": url})
            fact_map = {f["key"]: f["value"] for f in facts}
            status = "OK"
            if fact_map.get("transport_error"):
                status = "FAIL"
            elif fact_map.get("error_status"):
                status = "DEGRADED"
            report["web_fetch"] = {"status": status, "summary": summary, "facts": fact_map, "source": source}
        except Exception as exc:
            report["web_fetch"] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        typer.echo(json.dumps(report, ensure_ascii=False, indent=2))

    asyncio.run(runner())


if __name__ == "__main__":
    app()
