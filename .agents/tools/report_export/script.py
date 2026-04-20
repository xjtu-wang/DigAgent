from __future__ import annotations


def run(*, tool_context, report_id: str, format: str = "markdown", include_content: bool = False) -> dict[str, object]:
    report = tool_context.storage.load_report(report_id)
    if format == "markdown":
        path = tool_context.storage.report_markdown_path(report_id)
        payload: dict[str, object] = {
            "report_id": report_id,
            "format": format,
            "path": str(path),
            "title": report.title,
            "kind": report.kind,
        }
        if include_content:
            payload["content"] = path.read_text(encoding="utf-8")
        return payload
    if format == "pdf":
        path = tool_context.storage.report_pdf_path(report_id)
        return {
            "report_id": report_id,
            "format": format,
            "path": str(path),
            "title": report.title,
            "kind": report.kind,
        }
    raise ValueError("Unsupported format")
