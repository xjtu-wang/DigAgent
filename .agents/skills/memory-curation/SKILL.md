---
name: memory-curation
description: Curate durable user and project memory by promoting stable facts from session records into .agents memory files.
---

# Memory Curation

## When To Use

- The user expresses a stable preference that should carry across sessions.
- The repo has a durable convention worth remembering.
- A session produced reusable knowledge that will reduce repeated work later.

## Promotion Rules

- Keep short, explicit bullet points.
- Prefer one topic per file under `/.agents/memory/`.
- Summarize the stable conclusion, not the transient debugging path.
- Leave temporary notes in session records unless they are worth promoting.

## Avoid

- Secrets or credentials.
- One-off execution noise.
- Volatile status updates that will go stale quickly.
