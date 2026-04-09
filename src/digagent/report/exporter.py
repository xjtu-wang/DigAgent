from __future__ import annotations

import subprocess
from pathlib import Path

from jinja2 import Template
from markdown_it import MarkdownIt

from digagent.config import AppSettings, get_settings
from digagent.models import ReportRecord

REPORT_TEMPLATE = Template(
    """<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <title>{{ title }}</title>
    <style>
      body { font-family: "Noto Sans CJK SC", "PingFang SC", sans-serif; margin: 40px; color: #111827; }
      h1,h2,h3 { color: #0f172a; }
      code, pre { font-family: "JetBrains Mono", monospace; }
      pre { background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; overflow: auto; }
      table { width: 100%; border-collapse: collapse; }
      th, td { border: 1px solid #cbd5e1; padding: 8px; text-align: left; vertical-align: top; }
      .muted { color: #64748b; }
    </style>
  </head>
  <body>
    {{ html | safe }}
  </body>
</html>"""
)


class ReportExporter:
    def __init__(self, settings: AppSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.md = MarkdownIt("commonmark", {"html": True, "linkify": True, "typographer": True})

    def render_markdown(self, report: ReportRecord) -> str:
        lines = [
            f"# {report.title}",
            "",
            f"> 生成时间: {report.generated_at}",
            "",
            "## 摘要",
            report.summary,
            "",
        ]
        if report.writer_summary:
            lines.extend(["## 写作说明", report.writer_summary, ""])
        if report.evidence_refs:
            lines.extend(["## 关键证据", *[f"- `{ref}`" for ref in report.evidence_refs], ""])
        lines.append("## 发现")
        if report.findings:
            for finding in report.findings:
                lines.extend(
                    [
                        f"### {finding.title}",
                        f"- Severity: `{finding.severity}`",
                        f"- Confidence: `{finding.confidence:.2f}`",
                        f"- Claim: {finding.claim}",
                        f"- Evidence: {', '.join(f'`{ref}`' for ref in finding.evidence_refs)}",
                        f"- Reproduction: {'；'.join(finding.reproduction_steps)}",
                        f"- Remediation: {finding.remediation}",
                        "",
                    ]
                )
        else:
            lines.extend(["- 无高置信度风险发现，输出以结构和证据总结为主。", ""])
        if report.limitations:
            lines.extend(["## 限制", *[f"- {item}" for item in report.limitations], ""])
        return "\n".join(lines).strip() + "\n"

    def render_html(self, markdown: str, title: str) -> str:
        html = self.md.render(markdown)
        return REPORT_TEMPLATE.render(title=title, html=html)

    def export_pdf(self, html_path: Path, output_path: Path) -> bytes:
        script = self.settings.pdf_renderer_script
        chrome_bin = self.settings.chrome_bin
        if script.exists():
            cmd = ["node", str(script), str(html_path), str(output_path), chrome_bin]
        else:
            cmd = [
                chrome_bin,
                "--headless",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                f"--print-to-pdf={output_path}",
                str(html_path),
            ]
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
        if not output_path.exists():
            raise RuntimeError(f"PDF renderer completed without creating output: {output_path}")
        return output_path.read_bytes()
