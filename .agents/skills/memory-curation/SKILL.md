---
name: memory-curation
description: Manage OpenClaw-style short-term and long-term memory, keeping durable knowledge in .agents/memory/.
---

# Memory Curation

## When To Use

- A session produced reusable knowledge that should survive future runs.
- The user expressed a stable preference, workflow, or constraint.
- The repo gained a durable convention, capability contract, or operating rule.

## Memory Layers

- Short-term memory stays in session records, daily notes, and runtime-local
  working context.
- Long-term memory lives under `/.agents/memory/`.
- Keep high-signal summaries in `/.agents/memory/active.md`.
- Store detailed, reusable long-term knowledge in `/.agents/memory/archive/*.md`.

## Promotion Rules

- Summarize stable conclusions, not transient debugging paths.
- Keep `active.md` short and decision-oriented.
- Promote detailed knowledge into one topic per archive file when the summary
  would otherwise become too long.
- Prefer explicit bullets with clear scope and reuse value.

## Avoid

- Secrets or credentials.
- One-off execution noise.
- Volatile status updates that will go stale quickly.
- Dumping whole transcripts into long-term memory.
