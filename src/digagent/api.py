from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from digagent.config import get_settings
from digagent.models import Scope
from digagent.runtime import RunManager


class CreateSessionRequest(BaseModel):
    title: str
    profile: str = "sisyphus-default"
    task_type: str = "general"
    scope: Scope = Field(default_factory=Scope)


class SessionMessageRequest(BaseModel):
    content: str
    profile: str = "sisyphus-default"
    auto_approve: bool = False
    title: str | None = None
    scope: Scope = Field(default_factory=Scope)


class CreateRunRequest(BaseModel):
    task: str
    profile: str = "sisyphus-default"
    session_id: str | None = None
    auto_approve: bool = False
    title: str | None = None
    scope: Scope = Field(default_factory=Scope)


class ApprovalRequest(BaseModel):
    approved: bool
    resolver: str = "webui"
    reason: str | None = None
    approval_token: str


class CveSyncRequest(BaseModel):
    max_records: int | None = None


def create_app(manager: RunManager | None = None) -> FastAPI:
    manager = manager or RunManager()
    settings = get_settings()
    app = FastAPI(title="DigAgent API")
    app.state.manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/catalog")
    async def catalog():
        return manager.catalog()

    @app.post("/api/sessions")
    async def create_session(body: CreateSessionRequest):
        session = manager.create_session(
            title=body.title,
            profile_name=body.profile,
            task_type=body.task_type,
            scope=body.scope,
        )
        return session.model_dump(mode="json")

    @app.get("/api/sessions")
    async def list_sessions():
        return [session.model_dump(mode="json") for session in manager.list_sessions()]

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        return manager.storage.load_session(session_id).model_dump(mode="json")

    @app.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        return [message.model_dump(mode="json") for message in manager.list_messages(session_id)]

    @app.get("/api/sessions/{session_id}/runs")
    async def get_session_runs(session_id: str):
        return [run.model_dump(mode="json") for run in manager.list_runs(session_id)]

    @app.post("/api/sessions/{session_id}/messages")
    async def post_session_message(session_id: str, body: SessionMessageRequest):
        session, turn = await manager.handle_message(
            session_id=session_id,
            content=body.content,
            profile_name=body.profile,
            scope=body.scope,
            auto_approve=body.auto_approve,
            title=body.title,
        )
        payload = turn.model_dump(mode="json")
        payload["session"] = session.model_dump(mode="json")
        if turn.run_id:
            payload["run"] = manager.storage.find_run(turn.run_id).model_dump(mode="json")
        return payload

    @app.get("/api/sessions/{session_id}/events")
    async def stream_session_events(session_id: str, history_only: bool = False):
        async def event_stream() -> AsyncIterator[str]:
            history = manager.event_history.get(session_id, [])
            if history_only:
                for event in history:
                    yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
                return
            async for event in manager.stream_events(session_id):
                yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/runs")
    async def create_run(body: CreateRunRequest):
        if body.session_id:
            session_id = body.session_id
        else:
            session_id = manager.create_session(
                title=body.title or body.task[:60],
                profile_name=body.profile,
                task_type="general",
                scope=body.scope,
            ).session_id
        session, turn = await manager.handle_message(
            session_id=session_id,
            content=body.task,
            profile_name=body.profile,
            scope=body.scope,
            auto_approve=body.auto_approve,
            title=body.title,
        )
        if not turn.run_id:
            raise HTTPException(status_code=409, detail=turn.assistant_message or "run was not created")
        run = manager.storage.find_run(turn.run_id)
        return {
            "session": session.model_dump(mode="json"),
            "run": run.model_dump(mode="json"),
            "turn": turn.model_dump(mode="json"),
        }

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        return manager.storage.find_run(run_id).model_dump(mode="json")

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_run(run_id: str):
        run = await manager.cancel_run_by_id(run_id)
        return run.model_dump(mode="json")

    @app.get("/api/runs/{run_id}/graph")
    async def get_run_graph(run_id: str):
        return manager.get_run_graph(run_id)

    @app.get("/api/runs/{run_id}/events")
    async def stream_run_events(run_id: str, history_only: bool = False):
        run = manager.storage.find_run(run_id)

        async def event_stream() -> AsyncIterator[str]:
            history = [event for event in manager.event_history.get(run.session_id, []) if event.run_id == run_id]
            if history_only:
                for event in history:
                    yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
                return
            async for event in manager.stream_run_events(run_id):
                yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/approvals/{approval_id}")
    async def resolve_approval(approval_id: str, body: ApprovalRequest):
        try:
            approval = await manager.approve(
                approval_id,
                approved=body.approved,
                resolver=body.resolver,
                reason=body.reason,
                approval_token=body.approval_token,
                background=True,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return approval.model_dump(mode="json")

    @app.post("/api/sessions/{session_id}/archive")
    async def archive_session(session_id: str):
        try:
            return manager.archive_session(session_id).model_dump(mode="json")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/unarchive")
    async def unarchive_session(session_id: str):
        return manager.unarchive_session(session_id).model_dump(mode="json")

    @app.get("/api/evidence/{evidence_id}")
    async def get_evidence(evidence_id: str):
        evidence = manager.get_evidence(evidence_id)
        payload = evidence.model_dump(mode="json")
        payload["artifacts"] = [manager.get_artifact(artifact_id).model_dump(mode="json") for artifact_id in evidence.artifact_refs]
        return payload

    @app.get("/api/artifacts/{artifact_id}")
    async def get_artifact(artifact_id: str):
        return manager.get_artifact(artifact_id).model_dump(mode="json")

    @app.get("/api/artifacts/{artifact_id}/content")
    async def get_artifact_content(artifact_id: str):
        artifact = manager.get_artifact(artifact_id)
        return FileResponse(artifact.storage_path, media_type=artifact.mime_type, filename=artifact.storage_path.split("/")[-1])

    @app.get("/api/reports/{report_id}")
    async def get_report(report_id: str):
        report = manager.storage.load_report(report_id)
        markdown_path = manager.storage.report_markdown_path(report_id)
        payload = report.model_dump(mode="json")
        payload["markdown"] = markdown_path.read_text(encoding="utf-8")
        return payload

    @app.get("/api/reports/{report_id}/download")
    async def download_report(report_id: str, format: str = "markdown"):
        if format == "markdown":
            return FileResponse(manager.storage.report_markdown_path(report_id), media_type="text/markdown")
        if format == "pdf":
            return FileResponse(manager.storage.report_pdf_path(report_id), media_type="application/pdf")
        raise HTTPException(status_code=400, detail="Unsupported format")

    @app.get("/api/cve/status")
    async def cve_status():
        return manager.cve_status()

    @app.post("/api/cve/sync")
    async def cve_sync(body: CveSyncRequest):
        try:
            return await manager.sync_cve(max_records=body.max_records)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/cve/search")
    async def cve_search(query: str = "", cve_id: str | None = None, cwe: str | None = None, product: str | None = None, limit: int = 20):
        return {
            "items": manager.search_cve(query=query, cve_id=cve_id, cwe=cwe, product=product, limit=limit),
            "state": manager.cve_status(),
        }

    frontend_dist = settings.frontend_dist
    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{full_path:path}")
        async def spa_fallback(full_path: str):
            target = frontend_dist / full_path
            if full_path and target.exists() and target.is_file():
                return FileResponse(target)
            return FileResponse(frontend_dist / "index.html")

    return app
