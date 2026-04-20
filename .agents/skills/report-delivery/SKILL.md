---
name: report-delivery
description: Guide DigAgent to export markdown or PDF deliverables when the user asks for downloads or the response is too large for chat.
recommended_tools:
  - report_export
---

# Report Delivery

Use this skill when the user explicitly asks for a downloadable report, asks for
`pdf` or `markdown`, or when the material is too long to present cleanly in the
chat window.

## Trigger Rules

- The user asks for a downloadable file, export, report, attachment, `pdf`, or
  `markdown`.
- The content is long enough that a structured artifact is clearer than a long
  chat reply.
- The agent needs to hand over a formal summary, briefing, or evidence bundle.

## Export Rules

- Prefer `markdown` by default when the user did not specify a format.
- Use `pdf` when the user explicitly asks for it or when the task clearly calls
  for a formal report artifact.
- If a persisted DigAgent report already exists, export that first.
- If no persisted report exists but the agent already has a finalized markdown
  summary, export that summary directly.
- Keep failures visible. Do not claim an export exists unless the tool returned
  a concrete download target.

## Response Rules

- Tell the user what was exported and in which format.
- Always return the download link from the tool output.
- When markdown was exported from the current answer, say that it is an ad hoc
  export rather than a persisted DigAgent report.
