from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from digagent.config import AppSettings, get_settings
from digagent.models import (
    CveSyncState,
    CVERecord,
    ApprovalRecord,
    ArtifactRecord,
    AuditEvent,
    TurnEvent,
    DailyMemoryNote,
    EvidenceRecord,
    MemoryRecord,
    MessageRecord,
    ReportRecord,
    Scope,
    SessionRecord,
    SessionStatus,
    SessionTitleSource,
    SessionTitleStatus,
    TurnRecord,
    WikiEntry,
)
from digagent.utils import ensure_parent, json_dumps, new_id, utc_now

ModelT = TypeVar("ModelT", bound=BaseModel)
logger = logging.getLogger(__name__)


class FileStorage:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.root = self.settings.data_dir
        self.ensure_layout()

    def ensure_layout(self) -> None:
        for relative in [
            "memory",
            "memory/daily",
            "memory/wiki",
            "sessions",
            "evidence",
            "reports",
            "artifacts/blob",
            "skills",
            "plugins",
            "tools",
            "mcp",
            "agents",
            "CVE/raw",
            "CVE/normalized",
            "CVE/index",
        ]:
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def _write_json(self, path: Path, model: BaseModel | dict[str, Any]) -> None:
        ensure_parent(path)
        if isinstance(model, BaseModel):
            payload = model.model_dump(mode="json")
        else:
            payload = model
        path.write_text(json_dumps(payload), encoding="utf-8")

    def _read_json(self, path: Path, model_type: type[ModelT]) -> ModelT:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))

    def _append_ndjson(self, path: Path, model: BaseModel) -> None:
        ensure_parent(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(model.model_dump(mode="json"), ensure_ascii=False))
            handle.write("\n")

    def _unlink_if_exists(self, path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            return

    def session_dir(self, session_id: str) -> Path:
        return self.root / "sessions" / session_id

    def session_json_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def session_messages_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "messages.ndjson"

    def turn_json_path(self, session_id: str, turn_id: str) -> Path:
        return self.session_dir(session_id) / "turns" / f"{turn_id}.json"

    def turn_events_path(self, session_id: str, turn_id: str) -> Path:
        return self.session_dir(session_id) / "turns" / f"{turn_id}.events.ndjson"

    def approval_path(self, approval_id: str) -> Path:
        return self.root / "sessions" / "_approvals" / f"{approval_id}.json"

    def evidence_path(self, evidence_id: str) -> Path:
        return self.root / "evidence" / f"{evidence_id}.json"

    def memory_path(self, memory_id: str) -> Path:
        return self.root / "memory" / f"{memory_id}.json"

    def memory_markdown_path(self) -> Path:
        return self.root / "memory" / "MEMORY.md"

    def memory_daily_path(self, day: str) -> Path:
        return self.root / "memory" / "daily" / f"{day}.md"

    def memory_index_path(self) -> Path:
        return self.root / "memory" / "index.json"

    def memory_wiki_path(self, entry_id: str) -> Path:
        return self.root / "memory" / "wiki" / f"{entry_id}.json"

    def artifact_json_path(self, artifact_id: str) -> Path:
        return self.root / "artifacts" / f"{artifact_id}.json"

    def artifact_blob_path(self, turn_id: str, artifact_id: str, suffix: str) -> Path:
        return self.root / "artifacts" / "blob" / turn_id / f"{artifact_id}{suffix}"

    def report_json_path(self, report_id: str) -> Path:
        return self.root / "reports" / f"{report_id}.json"

    def report_markdown_path(self, report_id: str) -> Path:
        return self.root / "reports" / f"{report_id}.md"

    def report_pdf_path(self, report_id: str) -> Path:
        return self.root / "reports" / f"{report_id}.pdf"

    def cve_raw_dir(self) -> Path:
        return self.root / "CVE" / "raw"

    def cve_normalized_dir(self) -> Path:
        return self.root / "CVE" / "normalized"

    def cve_index_dir(self) -> Path:
        return self.root / "CVE" / "index"

    def cve_state_path(self) -> Path:
        return self.root / "CVE" / "state.json"

    def cve_raw_page_path(self, start_index: int) -> Path:
        return self.cve_raw_dir() / f"cves_{start_index:08d}.json"

    def cve_normalized_path(self) -> Path:
        return self.cve_normalized_dir() / "cves.ndjson"

    def cve_index_path(self, name: str) -> Path:
        return self.cve_index_dir() / f"{name}.json"

    def create_session(
        self,
        title: str,
        root_agent_profile: str,
        scope: Scope,
        *,
        title_status: SessionTitleStatus = SessionTitleStatus.READY,
        title_source: SessionTitleSource = SessionTitleSource.MANUAL,
    ) -> SessionRecord:
        now = utc_now()
        session = SessionRecord(
            session_id=new_id("sess"),
            title=title,
            title_status=title_status,
            title_source=title_source,
            created_at=now,
            updated_at=now,
            root_agent_profile=root_agent_profile,
            scope=scope,
        )
        self.save_session(session)
        return session

    def save_session(self, session: SessionRecord) -> None:
        self._write_json(self.session_json_path(session.session_id), session)

    def load_session(self, session_id: str) -> SessionRecord:
        session = self._read_json(self.session_json_path(session_id), SessionRecord)
        if session.schema_version != "2.0":
            raise ValueError(f"Legacy session schema is not supported: {session_id}")
        return session

    def list_sessions(self) -> list[SessionRecord]:
        sessions: list[SessionRecord] = []
        for path in sorted(self.root.glob("sessions/*/session.json")):
            try:
                session = self._read_json(path, SessionRecord)
            except ValidationError:
                continue
            if session.schema_version != "2.0":
                continue
            sessions.append(session)
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def append_message(self, message: MessageRecord) -> None:
        self._append_ndjson(self.session_messages_path(message.session_id), message)
        session = self.load_session(message.session_id)
        session.updated_at = message.created_at
        if message.role.value == "user":
            session.last_user_message_id = message.message_id
        elif message.role.value == "assistant":
            session.last_agent_message_id = message.message_id
        self.save_session(session)

    def update_session(
        self,
        session_id: str,
        updater,
    ) -> SessionRecord:
        session = self.load_session(session_id)
        updated = updater(session) or session
        updated.updated_at = utc_now()
        self.save_session(updated)
        return updated

    def update_session_title_state(
        self,
        session_id: str,
        *,
        title_status: SessionTitleStatus,
        title_source: SessionTitleSource | None = None,
        title: str | None = None,
    ) -> SessionRecord:
        def updater(session: SessionRecord) -> SessionRecord:
            session.title_status = title_status
            if title_source is not None:
                session.title_source = title_source
            if title is not None:
                session.title = title
            return session

        return self.update_session(session_id, updater)

    def load_messages(self, session_id: str) -> list[MessageRecord]:
        path = self.session_messages_path(session_id)
        if not path.exists():
            return []
        messages: list[MessageRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                messages.append(MessageRecord.model_validate_json(line))
        return messages

    def archive_session(self, session_id: str) -> SessionRecord:
        session = self.load_session(session_id)
        session.status = SessionStatus.ARCHIVED
        session.archived_at = utc_now()
        self.save_session(session)
        return session

    def unarchive_session(self, session_id: str) -> SessionRecord:
        session = self.load_session(session_id)
        session.status = SessionStatus.IDLE
        session.archived_at = None
        self.save_session(session)
        return session

    def delete_session(self, session_id: str) -> None:
        session = self.load_session(session_id)
        turns = self.list_turns(session_id)
        approval_ids = set(session.pending_approval_ids)
        evidence_ids = set(session.evidence_refs)
        report_ids = set(session.report_refs)
        artifact_ids: set[str] = set()

        for turn in turns:
            approval_ids.update(turn.approval_ids)
            evidence_ids.update(turn.evidence_ids)
            artifact_ids.update(turn.artifact_ids)
            if turn.report_id:
                report_ids.add(turn.report_id)

        for evidence_id in evidence_ids:
            evidence_path = self.evidence_path(evidence_id)
            if not evidence_path.exists():
                continue
            evidence = self._read_json(evidence_path, EvidenceRecord)
            artifact_ids.update(evidence.artifact_refs)
            self._unlink_if_exists(evidence_path)

        for artifact_id in artifact_ids:
            artifact_json = self.artifact_json_path(artifact_id)
            if artifact_json.exists():
                artifact = self._read_json(artifact_json, ArtifactRecord)
                self._unlink_if_exists(Path(artifact.storage_path))
            self._unlink_if_exists(artifact_json)

        for report_id in report_ids:
            self._unlink_if_exists(self.report_json_path(report_id))
            self._unlink_if_exists(self.report_markdown_path(report_id))
            self._unlink_if_exists(self.report_pdf_path(report_id))

        for approval_id in approval_ids:
            self._unlink_if_exists(self.approval_path(approval_id))

        shutil.rmtree(self.session_dir(session_id), ignore_errors=True)

    def create_turn(
        self,
        session_id: str,
        profile_name: str,
        task: str,
        scope: Scope,
        budget,
        auto_approve: bool = False,
        trigger_message_id: str | None = None,
    ) -> TurnRecord:
        now = utc_now()
        turn = TurnRecord(
            turn_id=new_id("turn"),
            session_id=session_id,
            root_agent_id=profile_name,
            profile_name=profile_name,
            status="created",
            auto_approve=auto_approve,
            user_task=task,
            scope=scope,
            budget=budget,
            trigger_message_id=trigger_message_id,
            created_at=now,
            updated_at=now,
        )
        self.save_turn(turn)
        session = self.load_session(session_id)
        session.turn_ids.append(turn.turn_id)
        session.updated_at = now
        self.save_session(session)
        return turn

    def save_turn(self, turn: TurnRecord) -> None:
        turn.updated_at = utc_now()
        self._write_json(self.turn_json_path(turn.session_id, turn.turn_id), turn)

    def load_turn(self, session_id: str, turn_id: str) -> TurnRecord:
        return self._read_json(self.turn_json_path(session_id, turn_id), TurnRecord)

    def list_turns(self, session_id: str) -> list[TurnRecord]:
        turns_dir = self.session_dir(session_id) / "turns"
        turns: list[TurnRecord] = []
        if not turns_dir.exists():
            return turns
        for path in sorted(turns_dir.glob("*.json")):
            if path.name.endswith(".events.ndjson"):
                continue
            turns.append(self._read_json(path, TurnRecord))
        return sorted(turns, key=lambda item: item.created_at, reverse=True)

    def find_turn(self, turn_id: str) -> TurnRecord:
        for path in self.root.glob(f"sessions/*/turns/{turn_id}.json"):
            return self._read_json(path, TurnRecord)
        raise FileNotFoundError(turn_id)

    def save_evidence(self, evidence: EvidenceRecord) -> None:
        self._write_json(self.evidence_path(evidence.evidence_id), evidence)
        session = self.load_session(evidence.session_id)
        if evidence.evidence_id not in session.evidence_refs:
            session.evidence_refs.append(evidence.evidence_id)
            self.save_session(session)

    def load_evidence(self, evidence_id: str) -> EvidenceRecord:
        return self._read_json(self.evidence_path(evidence_id), EvidenceRecord)

    def save_memory(self, memory: MemoryRecord) -> None:
        self._write_json(self.memory_path(memory.memory_id), memory)
        session = self.load_session(memory.source_session_id)
        if memory.memory_id not in session.memory_refs:
            session.memory_refs.append(memory.memory_id)
            self.save_session(session)

    def load_memory(self, memory_id: str) -> MemoryRecord:
        return self._read_json(self.memory_path(memory_id), MemoryRecord)

    def list_memories(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for path in sorted(self.root.glob("memory/mem_*.json")):
            records.append(self._read_json(path, MemoryRecord))
        return sorted(records, key=lambda item: item.updated_at, reverse=True)

    def load_memory_markdown(self) -> str:
        path = self.memory_markdown_path()
        if not path.exists():
            return "# DigAgent Memory\n\n"
        return path.read_text(encoding="utf-8")

    def save_memory_markdown(self, content: str) -> None:
        self.memory_markdown_path().write_text(content, encoding="utf-8")

    def append_daily_memory(self, note: DailyMemoryNote) -> None:
        day = note.created_at[:10]
        path = self.memory_daily_path(day)
        ensure_parent(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"## {note.heading}\n\n")
            handle.write(f"source_session_id: {note.source_session_id}\n")
            handle.write(f"source_turn_id: {note.source_turn_id}\n\n")
            handle.write(note.body.strip() + "\n\n")
            if note.evidence_refs:
                handle.write("Evidence: " + ", ".join(f"`{ref}`" for ref in note.evidence_refs) + "\n\n")

    def load_daily_memory(self, day: str) -> str:
        path = self.memory_daily_path(day)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def save_memory_index(self, payload: dict[str, Any]) -> None:
        self._write_json(self.memory_index_path(), payload)

    def load_memory_index(self) -> dict[str, Any]:
        path = self.memory_index_path()
        if not path.exists():
            return {"items": []}
        return json.loads(path.read_text(encoding="utf-8"))

    def save_wiki_entry(self, entry: WikiEntry) -> None:
        self._write_json(self.memory_wiki_path(entry.entry_id), entry)

    def load_wiki_entry(self, entry_id: str) -> WikiEntry:
        return self._read_json(self.memory_wiki_path(entry_id), WikiEntry)

    def list_wiki_entries(self) -> list[WikiEntry]:
        entries: list[WikiEntry] = []
        for path in sorted((self.root / "memory" / "wiki").glob("*.json")):
            entries.append(self._read_json(path, WikiEntry))
        return sorted(entries, key=lambda item: item.updated_at, reverse=True)

    def save_approval(self, approval: ApprovalRecord) -> None:
        self._write_json(self.approval_path(approval.approval_id), approval)

    def load_approval(self, approval_id: str) -> ApprovalRecord:
        return self._read_json(self.approval_path(approval_id), ApprovalRecord)

    def list_approvals(self, *, turn_id: str | None = None, status: str | None = None) -> list[ApprovalRecord]:
        approvals_dir = self.root / "sessions" / "_approvals"
        approvals: list[ApprovalRecord] = []
        if not approvals_dir.exists():
            return approvals
        for path in sorted(approvals_dir.glob("*.json")):
            try:
                approval = self._read_json(path, ApprovalRecord)
            except ValidationError as exc:
                logger.warning("Skipping invalid approval record at %s: %s", path, exc)
                continue
            if turn_id and approval.turn_id != turn_id:
                continue
            if status and approval.status != status:
                continue
            approvals.append(approval)
        return sorted(approvals, key=lambda item: item.requested_at, reverse=True)

    def save_artifact(
        self,
        *,
        session_id: str,
        turn_id: str,
        kind: str,
        content: str | bytes,
        mime_type: str = "text/plain",
        suffix: str = ".txt",
    ) -> ArtifactRecord:
        artifact_id = new_id("art")
        blob_path = self.artifact_blob_path(turn_id, artifact_id, suffix)
        ensure_parent(blob_path)
        raw = content.encode("utf-8") if isinstance(content, str) else content
        blob_path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        artifact = ArtifactRecord(
            artifact_id=artifact_id,
            kind=kind,
            session_id=session_id,
            turn_id=turn_id,
            storage_path=str(blob_path),
            mime_type=mime_type,
            size_bytes=len(raw),
            sha256=digest,
            created_at=utc_now(),
        )
        self._write_json(self.artifact_json_path(artifact_id), artifact)
        return artifact

    def load_artifact(self, artifact_id: str) -> ArtifactRecord:
        return self._read_json(self.artifact_json_path(artifact_id), ArtifactRecord)

    def load_artifact_bytes(self, artifact_id: str) -> bytes:
        artifact = self.load_artifact(artifact_id)
        return Path(artifact.storage_path).read_bytes()

    def append_turn_event(self, session_id: str, event: TurnEvent) -> None:
        self._append_ndjson(self.turn_events_path(session_id, event.turn_id or "session"), event)

    def load_turn_events(self, session_id: str, turn_id: str) -> list[dict[str, Any]]:
        path = self.turn_events_path(session_id, turn_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append_audit(self, session_id: str, event: AuditEvent) -> None:
        self.append_turn_event(
            session_id,
            TurnEvent(
                event_id=event.event_id,
                session_id=session_id,
                turn_id=event.turn_id,
                type="audit",
                data=event.model_dump(mode="json"),
                created_at=event.timestamp,
            ),
        )

    def load_audit_events(self, session_id: str, turn_id: str) -> list[dict[str, Any]]:
        return self.load_turn_events(session_id, turn_id)

    def save_report(self, report: ReportRecord, markdown: str, pdf_bytes: bytes | None = None) -> None:
        self._write_json(self.report_json_path(report.report_id), report)
        self.report_markdown_path(report.report_id).write_text(markdown, encoding="utf-8")
        if pdf_bytes is not None:
            self.report_pdf_path(report.report_id).write_bytes(pdf_bytes)
        session = self.load_session(report.session_id)
        if report.report_id not in session.report_refs:
            session.report_refs.append(report.report_id)
        session.last_report_id = report.report_id
        session.latest_report_id = report.report_id
        session.updated_at = utc_now()
        self.save_session(session)

    def load_report(self, report_id: str) -> ReportRecord:
        return self._read_json(self.report_json_path(report_id), ReportRecord)

    def save_cve_state(self, state: CveSyncState) -> None:
        self._write_json(self.cve_state_path(), state)

    def load_cve_state(self) -> CveSyncState:
        path = self.cve_state_path()
        if not path.exists():
            state = CveSyncState()
            self.save_cve_state(state)
            return state
        return self._read_json(path, CveSyncState)

    def save_cve_raw_page(self, start_index: int, payload: dict[str, Any]) -> None:
        self._write_json(self.cve_raw_page_path(start_index), payload)

    def save_cve_records(self, records: list[CVERecord]) -> None:
        path = self.cve_normalized_path()
        ensure_parent(path)
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False))
                handle.write("\n")

    def load_cve_records(self) -> list[CVERecord]:
        path = self.cve_normalized_path()
        if not path.exists():
            return []
        records: list[CVERecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(CVERecord.model_validate_json(line))
        return records

    def save_cve_index(self, name: str, payload: dict[str, list[str]]) -> None:
        self._write_json(self.cve_index_path(name), payload)

    def load_cve_index(self, name: str) -> dict[str, list[str]]:
        path = self.cve_index_path(name)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
