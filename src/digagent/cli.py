from __future__ import annotations

import asyncio
import json

import typer
import uvicorn
from rich.console import Console
from rich.panel import Panel

from digagent.api import create_app
from digagent.models import Scope
from digagent.runtime import RunManager

app = typer.Typer(help="DigAgent CLI")
console = Console()


def _parse_scope(repo: list[str], domain: list[str], artifact: list[str]) -> Scope:
    return Scope(repo_paths=repo, allowed_domains=domain, artifacts=artifact)


async def _print_new_events(manager: RunManager, session_id: str, start_index: int, run_id: str | None) -> int:
    stop_statuses = {"completed", "failed", "awaiting_approval", "awaiting_user_input"}
    while True:
        history = manager.event_history.get(session_id, [])
        emitted = False
        while start_index < len(history):
            event = history[start_index]
            start_index += 1
            if run_id and event.run_id not in {None, run_id}:
                continue
            console.print(Panel(json.dumps(event.data, ensure_ascii=False, indent=2), title=event.type))
            emitted = True
            if event.run_id == run_id and event.type in stop_statuses:
                return start_index
        if emitted and not run_id:
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
        manager = RunManager()
        session = manager.create_session(title=task[:60], profile_name=profile, scope=_parse_scope(repo, domain, artifact))
        cursor = len(manager.event_history.get(session.session_id, []))
        _, turn = await manager.handle_message(
            session_id=session.session_id,
            content=task,
            profile_name=profile,
            scope=_parse_scope(repo, domain, artifact),
            auto_approve=auto_approve,
        )
        if turn.run_id:
            await _print_new_events(manager, session.session_id, cursor, turn.run_id)
        elif turn.assistant_message:
            console.print(turn.assistant_message)

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
        manager = RunManager()
        scope = _parse_scope(repo, domain, artifact)
        session = manager.create_session(title=(task or "DigAgent Session")[:60], profile_name=profile, scope=scope)
        if task:
            cursor = len(manager.event_history.get(session.session_id, []))
            _, turn = await manager.handle_message(
                session_id=session.session_id,
                content=task,
                profile_name=profile,
                scope=scope,
                auto_approve=auto_approve,
            )
            if turn.run_id:
                await _print_new_events(manager, session.session_id, cursor, turn.run_id)
            elif turn.assistant_message:
                console.print(turn.assistant_message)
            return

        console.print(f"Session: {session.session_id}")
        while True:
            text = typer.prompt("Message").strip()
            if text.lower() in {"exit", "quit"}:
                break
            cursor = len(manager.event_history.get(session.session_id, []))
            _, turn = await manager.handle_message(
                session_id=session.session_id,
                content=text,
                profile_name=profile,
                scope=scope,
                auto_approve=auto_approve,
            )
            if turn.run_id:
                await _print_new_events(manager, session.session_id, cursor, turn.run_id)
            elif turn.assistant_message:
                console.print(turn.assistant_message)

    asyncio.run(runner())


@app.command()
def approve(
    approval_id: str = typer.Argument(...),
    approved: bool = typer.Option(True, "--approved/--rejected"),
    resolver: str = typer.Option("cli", "--resolver"),
    reason: str = typer.Option("", "--reason"),
) -> None:
    async def runner() -> None:
        manager = RunManager()
        pending = manager.storage.load_approval(approval_id)
        token = manager._approval_token_value(pending, approved=approved, resolver=resolver)
        approval = await manager.approve(
            approval_id,
            approved=approved,
            resolver=resolver,
            reason=reason or None,
            approval_token=token,
        )
        console.print_json(data=approval.model_dump(mode="json"))

    asyncio.run(runner())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


@app.command("cve-sync")
def cve_sync(
    max_records: int = typer.Option(200, "--max-records", min=1, help="Limit records for the current sync run."),
) -> None:
    async def runner() -> None:
        manager = RunManager()
        payload = await manager.sync_cve(max_records=max_records)
        console.print_json(data=payload)

    asyncio.run(runner())


@app.command("cve-status")
def cve_status() -> None:
    manager = RunManager()
    console.print_json(data=manager.cve_status())


@app.command("cve-search")
def cve_search(
    query: str = typer.Option("", "--query"),
    cve_id: str = typer.Option("", "--cve-id"),
    cwe: str = typer.Option("", "--cwe"),
    product: str = typer.Option("", "--product"),
    limit: int = typer.Option(10, "--limit", min=1, max=100),
) -> None:
    manager = RunManager()
    payload = manager.search_cve(
        query=query,
        cve_id=cve_id or None,
        cwe=cwe or None,
        product=product or None,
        limit=limit,
    )
    console.print_json(data={"items": payload, "state": manager.cve_status()})
