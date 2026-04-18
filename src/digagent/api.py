from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from digagent.config import current_env_summary, get_settings
from digagent.models import Scope, SessionPermissionOverrides, SessionTitleSource, SessionTitleStatus
from digagent.runtime import TurnManager
from digagent.session_titles import DEFAULT_SESSION_TITLE, is_seed_title


class CreateSessionRequest(BaseModel):
    title: str
    profile: str = "sisyphus-default"
    scope: Scope = Field(default_factory=Scope)


class SessionTurnRequest(BaseModel):
    content: str
    profile: str = "sisyphus-default"
    auto_approve: bool | None = None
    title: str | None = None
    scope: Scope = Field(default_factory=Scope)


class CreateTurnRequest(BaseModel):
    task: str
    profile: str = "sisyphus-default"
    session_id: str | None = None
    auto_approve: bool | None = None
    title: str | None = None
    scope: Scope = Field(default_factory=Scope)


class ApprovalRequest(BaseModel):
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    approved: bool | None = None
    resolver: str = "webui"
    reason: str | None = None


class ScopeUpdateRequest(BaseModel):
    add: Scope = Field(default_factory=Scope)
    remove: Scope = Field(default_factory=Scope)
    replace: Scope | None = None


class PermissionOverridesPatch(BaseModel):
    merge: SessionPermissionOverrides | None = None
    replace: SessionPermissionOverrides | None = None
    clear: bool = False


class CveSyncRequest(BaseModel):
    max_records: int | None = None


def create_app(manager: TurnManager | None = None) -> FastAPI:
    manager = manager or TurnManager()
    settings = getattr(manager, "settings", None) or get_settings()
    app = FastAPI(title="DigAgent API")
    app.state.manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def serialize_turn(turn):
        payload = turn.model_dump(mode="json")
        payload["pending_approvals"] = manager.pending_approvals_for_turn(turn.turn_id)
        return payload

    def serialize_session_summary(session):
        messages = manager.list_messages(session.session_id)
        last_preview = messages[-1].content[:140] if messages else None
        payload = session.model_dump(mode="json")
        payload["last_message_preview"] = last_preview
        payload["pending_approval_count"] = len(session.pending_approval_ids)
        return payload

    def serialize_session(session):
        payload = serialize_session_summary(session)
        payload["turns"] = [serialize_turn(turn) for turn in manager.list_turns(session.session_id)]
        return payload

    def require_supported_session(session_id: str):
        try:
            return manager.storage.load_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=session_id) from exc
        except ValueError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc

    def serialize_turn_result(session, result):
        payload = result.model_dump(mode="json")
        payload["session"] = serialize_session_summary(session)
        if result.turn_id:
            payload["turn"] = serialize_turn(manager.get_turn(result.turn_id))
        return payload

    async def stream_event_payload(events: AsyncIterator[Any]) -> AsyncIterator[str]:
        async for event in events:
            yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"

    @app.get("/api/health")
    async def health():
        return {"ok": True}

    @app.get("/api/catalog")
    async def catalog():
        return manager.catalog()

    @app.get("/api/settings/summary")
    async def settings_summary():
        return current_env_summary(settings)

    @app.post("/api/sessions")
    async def create_session(body: CreateSessionRequest):
        title = body.title or DEFAULT_SESSION_TITLE
        session = manager.storage.create_session(
            title=title,
            root_agent_profile=body.profile,
            scope=body.scope,
            title_status=SessionTitleStatus.PENDING if is_seed_title(title) else SessionTitleStatus.READY,
            title_source=SessionTitleSource.SEED if is_seed_title(title) else SessionTitleSource.MANUAL,
        )
        return serialize_session_summary(session)

    @app.get("/api/sessions")
    async def list_sessions():
        return [serialize_session_summary(session) for session in manager.list_sessions()]

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: str):
        return serialize_session(require_supported_session(session_id))

    @app.patch("/api/sessions/{session_id}/scope")
    async def patch_session_scope(session_id: str, body: ScopeUpdateRequest):
        require_supported_session(session_id)
        session = manager.update_session_scope(session_id=session_id, add=body.add, remove=body.remove, replace=body.replace)
        return session.model_dump(mode="json")

    @app.get("/api/sessions/{session_id}/permissions")
    async def get_session_permissions(session_id: str):
        return require_supported_session(session_id).permission_overrides.model_dump(mode="json")

    @app.patch("/api/sessions/{session_id}/permissions")
    async def patch_session_permissions(session_id: str, body: PermissionOverridesPatch):
        require_supported_session(session_id)
        session = manager.update_session_permissions(session_id=session_id, merge=body.merge, replace=body.replace, clear=body.clear)
        return session.permission_overrides.model_dump(mode="json")

    @app.get("/api/sessions/{session_id}/messages")
    async def get_session_messages(session_id: str):
        require_supported_session(session_id)
        return [message.model_dump(mode="json") for message in manager.list_messages(session_id)]

    @app.get("/api/sessions/{session_id}/turns")
    async def get_session_turns(session_id: str):
        require_supported_session(session_id)
        return [serialize_turn(turn) for turn in manager.list_turns(session_id)]

    @app.post("/api/sessions/{session_id}/turns")
    async def post_session_turn(session_id: str, body: SessionTurnRequest):
        require_supported_session(session_id)
        session, result = await manager.handle_message(
            session_id=session_id,
            content=body.content,
            profile_name=body.profile,
            scope=body.scope,
            auto_approve=bool(body.auto_approve),
            title=body.title,
        )
        return serialize_turn_result(session, result)

    @app.get("/api/sessions/{session_id}/events")
    async def stream_session_events(session_id: str, history_only: bool = False):
        require_supported_session(session_id)
        if history_only:
            async def history_stream() -> AsyncIterator[str]:
                for event in manager.load_session_event_history(session_id):
                    yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"

            return StreamingResponse(history_stream(), media_type="text/event-stream")
        return StreamingResponse(stream_event_payload(manager.stream_events(session_id)), media_type="text/event-stream")

    @app.post("/api/turns")
    async def create_turn(body: CreateTurnRequest):
        session_id = body.session_id
        if session_id is None:
            title = body.title or DEFAULT_SESSION_TITLE
            session = manager.storage.create_session(
                title=title,
                root_agent_profile=body.profile,
                scope=body.scope,
                title_status=SessionTitleStatus.PENDING if is_seed_title(title) else SessionTitleStatus.READY,
                title_source=SessionTitleSource.SEED if is_seed_title(title) else SessionTitleSource.MANUAL,
            )
            session_id = session.session_id
        session, result = await manager.handle_message(
            session_id=session_id,
            content=body.task,
            profile_name=body.profile,
            scope=body.scope,
            auto_approve=bool(body.auto_approve),
            title=body.title,
        )
        return serialize_turn_result(session, result)

    @app.get("/api/turns/{turn_id}")
    async def get_turn(turn_id: str):
        return serialize_turn(manager.get_turn(turn_id))

    @app.post("/api/turns/{turn_id}/cancel")
    async def cancel_turn(turn_id: str):
        turn = await manager.cancel_turn_by_id(turn_id)
        return serialize_turn(turn)

    @app.get("/api/turns/{turn_id}/graph")
    async def get_turn_graph(turn_id: str):
        return await manager.get_turn_graph(turn_id)

    @app.get("/api/turns/{turn_id}/events")
    async def stream_turn_events(turn_id: str, history_only: bool = False):
        if history_only:
            async def history_stream() -> AsyncIterator[str]:
                for event in manager.load_turn_event_history(turn_id):
                    yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"

            return StreamingResponse(history_stream(), media_type="text/event-stream")
        return StreamingResponse(stream_event_payload(manager.stream_turn_events(turn_id)), media_type="text/event-stream")

    @app.post("/api/approvals/{approval_id}")
    async def resolve_approval(approval_id: str, body: ApprovalRequest):
        try:
            approval = await manager.approve(
                approval_id,
                decisions=body.decisions or None,
                approved=body.approved,
                resolver=body.resolver,
                reason=body.reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return approval.model_dump(mode="json")

    @app.post("/api/sessions/{session_id}/messages")
    async def post_session_message_alias(session_id: str, body: SessionTurnRequest):
        require_supported_session(session_id)
        session, result = await manager.handle_message(
            session_id=session_id,
            content=body.content,
            profile_name=body.profile,
            scope=body.scope,
            auto_approve=bool(body.auto_approve),
            title=body.title,
        )
        return serialize_turn_result(session, result)

    @app.post("/api/sessions/{session_id}/archive")
    async def archive_session(session_id: str):
        try:
            require_supported_session(session_id)
            return manager.archive_session(session_id).model_dump(mode="json")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/sessions/{session_id}/unarchive")
    async def unarchive_session(session_id: str):
        require_supported_session(session_id)
        return manager.unarchive_session(session_id).model_dump(mode="json")

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str):
        try:
            require_supported_session(session_id)
            deleted_session_id = manager.delete_session(session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=session_id) from exc
        except ValueError as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"deleted_session_id": deleted_session_id}

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
        payload = report.model_dump(mode="json")
        payload["markdown"] = manager.storage.report_markdown_path(report_id).read_text(encoding="utf-8")
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
