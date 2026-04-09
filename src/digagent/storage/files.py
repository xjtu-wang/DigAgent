from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from digagent.config import AppSettings, get_settings
from digagent.models import (
    CveSyncState,
    CVERecord,
    ApprovalRecord,
    ArtifactRecord,
    AuditEvent,
    DailyMemoryNote,
    EvidenceRecord,
    MemoryRecord,
    MessageRecord,
    ReportRecord,
    RunRecord,
    Scope,
    SessionRecord,
    SessionStatus,
    WikiEntry,
)
from digagent.utils import ensure_parent, json_dumps, new_id, utc_now

ModelT = TypeVar("ModelT", bound=BaseModel)


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
            "tools",
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

    def session_dir(self, session_id: str) -> Path:
        return self.root / "sessions" / session_id

    def session_json_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def session_messages_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "messages.ndjson"

    def run_json_path(self, session_id: str, run_id: str) -> Path:
        return self.session_dir(session_id) / "runs" / f"{run_id}.json"

    def audit_path(self, session_id: str, run_id: str) -> Path:
        return self.session_dir(session_id) / "runs" / f"{run_id}.audit.ndjson"

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

    def artifact_blob_path(self, run_id: str, artifact_id: str, suffix: str) -> Path:
        return self.root / "artifacts" / "blob" / run_id / f"{artifact_id}{suffix}"

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

    def create_session(self, title: str, root_agent_profile: str, task_type: str, scope: Scope) -> SessionRecord:
        now = utc_now()
        session = SessionRecord(
            session_id=new_id("sess"),
            title=title,
            created_at=now,
            updated_at=now,
            root_agent_profile=root_agent_profile,
            task_type=task_type,
            scope=scope,
        )
        self.save_session(session)
        return session

    def save_session(self, session: SessionRecord) -> None:
        self._write_json(self.session_json_path(session.session_id), session)

    def load_session(self, session_id: str) -> SessionRecord:
        return self._read_json(self.session_json_path(session_id), SessionRecord)

    def list_sessions(self) -> list[SessionRecord]:
        sessions: list[SessionRecord] = []
        for path in sorted(self.root.glob("sessions/*/session.json")):
            sessions.append(self._read_json(path, SessionRecord))
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

    def create_run(
        self,
        session_id: str,
        profile_name: str,
        task: str,
        task_type: str,
        scope: Scope,
        budget,
        trigger_message_id: str | None = None,
    ) -> RunRecord:
        now = utc_now()
        run = RunRecord(
            run_id=new_id("run"),
            session_id=session_id,
            root_agent_id=profile_name,
            profile_name=profile_name,
            status="created",
            task_type=task_type,
            user_task=task,
            scope=scope,
            budget=budget,
            trigger_message_id=trigger_message_id,
            created_at=now,
            updated_at=now,
        )
        self.save_run(run)
        session = self.load_session(session_id)
        session.run_ids.append(run.run_id)
        session.updated_at = now
        self.save_session(session)
        return run

    def save_run(self, run: RunRecord) -> None:
        run.updated_at = utc_now()
        self._write_json(self.run_json_path(run.session_id, run.run_id), run)

    def load_run(self, session_id: str, run_id: str) -> RunRecord:
        return self._read_json(self.run_json_path(session_id, run_id), RunRecord)

    def list_runs(self, session_id: str) -> list[RunRecord]:
        runs_dir = self.session_dir(session_id) / "runs"
        runs: list[RunRecord] = []
        if not runs_dir.exists():
            return runs
        for path in sorted(runs_dir.glob("*.json")):
            if path.name.endswith(".audit.ndjson"):
                continue
            runs.append(self._read_json(path, RunRecord))
        return sorted(runs, key=lambda item: item.created_at, reverse=True)

    def find_run(self, run_id: str) -> RunRecord:
        for path in self.root.glob(f"sessions/*/runs/{run_id}.json"):
            return self._read_json(path, RunRecord)
        raise FileNotFoundError(run_id)

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

    def save_artifact(
        self,
        *,
        session_id: str,
        run_id: str,
        kind: str,
        content: str | bytes,
        mime_type: str = "text/plain",
        suffix: str = ".txt",
    ) -> ArtifactRecord:
        artifact_id = new_id("art")
        blob_path = self.artifact_blob_path(run_id, artifact_id, suffix)
        ensure_parent(blob_path)
        raw = content.encode("utf-8") if isinstance(content, str) else content
        blob_path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        artifact = ArtifactRecord(
            artifact_id=artifact_id,
            kind=kind,
            session_id=session_id,
            run_id=run_id,
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

    def append_audit(self, session_id: str, event: AuditEvent) -> None:
        self._append_ndjson(self.audit_path(session_id, event.run_id), event)

    def load_audit_events(self, session_id: str, run_id: str) -> list[dict[str, Any]]:
        path = self.audit_path(session_id, run_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

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
