from __future__ import annotations

from pathlib import Path

from digagent.deepagents_runtime.tools import build_custom_tools
from digagent.models import ReportRecord, RuntimeBudget, Scope


def _report_export_tool(test_settings):
    tools = build_custom_tools(test_settings)
    return next(tool for tool in tools if tool.name == "report_export")


def _activate_turn(storage) -> tuple[str, str]:
    session = storage.create_session("report-export", "sisyphus-default", Scope())
    turn = storage.create_turn(
        session.session_id,
        "sisyphus-default",
        "export report",
        Scope(),
        RuntimeBudget(),
    )
    session = storage.load_session(session.session_id)
    session.active_turn_id = turn.turn_id
    storage.save_session(session)
    return session.session_id, turn.turn_id


def test_report_export_generates_markdown_download_for_saved_report(test_settings, storage) -> None:
    session_id, turn_id = _activate_turn(storage)
    report = ReportRecord(
        report_id="rep_test_markdown",
        session_id=session_id,
        turn_id=turn_id,
        kind="brief",
        title="Test Report",
        scope={},
        summary="Summary body",
        generated_at="2026-04-20T00:00:00Z",
    )
    storage.save_report(report, "# Existing markdown\n")

    payload = _report_export_tool(test_settings).invoke({"report_id": report.report_id, "format": "markdown"})

    assert payload["mode"] == "report"
    assert payload["report_id"] == report.report_id
    assert payload["download_url"] == f"/api/reports/{report.report_id}/download?format=markdown"
    assert payload["path"] == str(storage.report_markdown_path(report.report_id))


def test_report_export_generates_pdf_for_saved_report_when_missing(test_settings, storage, monkeypatch) -> None:
    session_id, turn_id = _activate_turn(storage)
    report = ReportRecord(
        report_id="rep_test_pdf",
        session_id=session_id,
        turn_id=turn_id,
        kind="brief",
        title="PDF Report",
        scope={},
        summary="Summary body",
        generated_at="2026-04-20T00:00:00Z",
    )
    storage.save_report(report, "# Markdown body\n")

    def fake_export_pdf(self, html_path: Path, output_path: Path) -> bytes:
        assert html_path.exists()
        output_path.write_bytes(b"%PDF-test")
        return b"%PDF-test"

    monkeypatch.setattr("digagent.report.exporter.ReportExporter.export_pdf", fake_export_pdf)

    payload = _report_export_tool(test_settings).invoke({"report_id": report.report_id, "format": "pdf"})

    assert payload["mode"] == "report"
    assert payload["download_url"] == f"/api/reports/{report.report_id}/download?format=pdf"
    assert storage.report_pdf_path(report.report_id).read_bytes() == b"%PDF-test"


def test_report_export_supports_ad_hoc_markdown_artifact_export(test_settings, storage) -> None:
    session_id, turn_id = _activate_turn(storage)

    payload = _report_export_tool(test_settings).invoke(
        {"title": "Ad Hoc Export", "markdown": "# Notes\n", "format": "markdown", "include_content": True},
        config={"configurable": {"thread_id": session_id}},
    )

    assert payload["mode"] == "ad_hoc"
    assert payload["title"] == "Ad Hoc Export"
    assert payload["content"] == "# Notes\n"
    assert payload["download_url"].startswith("/api/artifacts/")
    artifact = storage.load_artifact(payload["artifact_id"])
    assert artifact.turn_id == turn_id
    turn = storage.load_turn(session_id, turn_id)
    assert payload["artifact_id"] in turn.artifact_ids


def test_report_export_ad_hoc_requires_session_turn_context(test_settings) -> None:
    tool = _report_export_tool(test_settings)
    try:
        tool.invoke({"title": "No Context", "markdown": "# Notes\n", "format": "markdown"})
    except ValueError as exc:
        assert "session context" in str(exc)
    else:
        raise AssertionError("expected ad hoc export to require session context")
