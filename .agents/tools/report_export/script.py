from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from langchain_core.runnables import RunnableConfig

AD_HOC_KIND = "ad_hoc"
MARKDOWN_MIME = "text/markdown"
PDF_MIME = "application/pdf"
MARKDOWN_SUFFIX = ".md"
PDF_SUFFIX = ".pdf"


def run(
    *,
    tool_context,
    report_id: str | None = None,
    title: str | None = None,
    markdown: str | None = None,
    format: str = "markdown",
    include_content: bool = False,
    config: RunnableConfig | None = None,
) -> dict[str, object]:
    _validate_mode_inputs(report_id=report_id, title=title, markdown=markdown)
    if title is not None and markdown is not None:
        return _export_ad_hoc(
            tool_context,
            title=title,
            markdown=markdown,
            format=format,
            include_content=include_content,
            config=config,
        )
    resolved_report_id = _resolve_report_id(tool_context, report_id=report_id, config=config)
    return _export_saved_report(
        tool_context,
        report_id=resolved_report_id,
        format=format,
        include_content=include_content,
    )


def _validate_mode_inputs(*, report_id: str | None, title: str | None, markdown: str | None) -> None:
    if report_id and (title is not None or markdown is not None):
        raise ValueError("report_export accepts either report_id or title+markdown, not both.")
    if (title is None) ^ (markdown is None):
        raise ValueError("report_export ad hoc mode requires both title and markdown.")


def _export_ad_hoc(
    tool_context,
    *,
    title: str,
    markdown: str,
    format: str,
    include_content: bool,
    config: RunnableConfig | None,
) -> dict[str, object]:
    session = _load_session_from_config(tool_context, config)
    if session is None:
        raise ValueError("report_export ad hoc mode requires session context.")
    turn_id = _require_active_turn_id(session.active_turn_id)
    artifact = _save_ad_hoc_artifact(
        tool_context,
        session_id=session.session_id,
        turn_id=turn_id,
        title=title,
        markdown=markdown,
        format=format,
    )
    _record_turn_artifact(tool_context, session_id=session.session_id, turn_id=turn_id, artifact_id=artifact.artifact_id)
    payload: dict[str, object] = {
        "mode": AD_HOC_KIND,
        "artifact_id": artifact.artifact_id,
        "format": format,
        "path": artifact.storage_path,
        "download_url": f"/api/artifacts/{artifact.artifact_id}/content",
        "title": title,
        "kind": AD_HOC_KIND,
    }
    if include_content and format == "markdown":
        payload["content"] = markdown
    return payload


def _save_ad_hoc_artifact(tool_context, *, session_id: str, turn_id: str, title: str, markdown: str, format: str):
    if format == "markdown":
        return tool_context.storage.save_artifact(
            session_id=session_id,
            turn_id=turn_id,
            kind="report_export_markdown",
            content=markdown,
            mime_type=MARKDOWN_MIME,
            suffix=MARKDOWN_SUFFIX,
        )
    if format == "pdf":
        pdf_bytes = _render_pdf_bytes(tool_context, title=title, markdown=markdown)
        return tool_context.storage.save_artifact(
            session_id=session_id,
            turn_id=turn_id,
            kind="report_export_pdf",
            content=pdf_bytes,
            mime_type=PDF_MIME,
            suffix=PDF_SUFFIX,
        )
    raise ValueError("Unsupported format")


def _export_saved_report(tool_context, *, report_id: str, format: str, include_content: bool) -> dict[str, object]:
    report = tool_context.storage.load_report(report_id)
    markdown = _ensure_report_markdown(tool_context, report)
    pdf_bytes = None
    path = tool_context.storage.report_markdown_path(report.report_id)
    if format == "pdf":
        path, pdf_bytes = _ensure_report_pdf(tool_context, report, markdown)
    elif format != "markdown":
        raise ValueError("Unsupported format")
    report = _persist_report_export(tool_context, report, markdown=markdown, format=format, path=path, pdf_bytes=pdf_bytes)
    payload: dict[str, object] = {
        "mode": "report",
        "report_id": report.report_id,
        "format": format,
        "path": str(path),
        "download_url": f"/api/reports/{report.report_id}/download?format={format}",
        "title": report.title,
        "kind": report.kind,
    }
    if include_content and format == "markdown":
        payload["content"] = markdown
    return payload


def _persist_report_export(tool_context, report, *, markdown: str, format: str, path: Path, pdf_bytes: bytes | None):
    export_paths = dict(report.export_paths)
    export_paths[format] = str(path)
    updated_report = report.model_copy(update={"export_paths": export_paths})
    tool_context.storage.save_report(updated_report, markdown, pdf_bytes=pdf_bytes)
    return updated_report


def _ensure_report_markdown(tool_context, report) -> str:
    path = tool_context.storage.report_markdown_path(report.report_id)
    if path.exists():
        return path.read_text(encoding="utf-8")
    return tool_context.report_exporter.render_markdown(report)


def _ensure_report_pdf(tool_context, report, markdown: str) -> tuple[Path, bytes | None]:
    path = tool_context.storage.report_pdf_path(report.report_id)
    if path.exists():
        return path, None
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf_bytes = _render_pdf_bytes(tool_context, title=report.title, markdown=markdown, output_path=path)
    return path, pdf_bytes


def _render_pdf_bytes(tool_context, *, title: str, markdown: str, output_path: Path | None = None) -> bytes:
    with TemporaryDirectory(prefix="digagent-report-export-") as tmpdir:
        tmp_root = Path(tmpdir)
        html_path = tmp_root / "report.html"
        target_path = output_path or (tmp_root / "report.pdf")
        html = tool_context.report_exporter.render_html(markdown, title)
        html_path.write_text(html, encoding="utf-8")
        return tool_context.report_exporter.export_pdf(html_path, target_path)


def _resolve_report_id(tool_context, *, report_id: str | None, config: RunnableConfig | None) -> str:
    if report_id:
        return report_id
    session = _load_session_from_config(tool_context, config)
    if session is None:
        raise ValueError("report_export requires report_id or a session context with latest_report_id.")
    if not session.latest_report_id:
        raise ValueError("Current session has no persisted report to export.")
    return session.latest_report_id


def _load_session_from_config(tool_context, config: RunnableConfig | None):
    if not config:
        return None
    configurable = config.get("configurable") or {}
    session_id = configurable.get("thread_id")
    if not session_id:
        return None
    return tool_context.storage.load_session(str(session_id))


def _require_active_turn_id(turn_id: str | None) -> str:
    if not turn_id:
        raise ValueError("Current session has no active turn for ad hoc export.")
    return turn_id


def _record_turn_artifact(tool_context, *, session_id: str, turn_id: str, artifact_id: str) -> None:
    turn = tool_context.storage.load_turn(session_id, turn_id)
    if artifact_id in turn.artifact_ids:
        return
    turn.artifact_ids.append(artifact_id)
    tool_context.storage.save_turn(turn)
