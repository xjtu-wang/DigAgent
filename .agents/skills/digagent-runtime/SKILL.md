---
name: digagent-runtime
description: DigAgent runtime conventions for .agents-based skills, tools, and memory promotion.
---

# DigAgent Runtime

## Layout

- Root and specialist agent profiles live under `/.agents/subagents/*/agent.yaml`.
- Project skills live under `/.agents/skills/`.
- Project tools live under `/.agents/tools/*/{tool.yaml,script.py}`.
- MCP server configs live under `/.agents/mcp/*.yaml`.
- Long-term memory lives under `/.agents/memory/*.md`.

## Memory

- Temporary notes stay in session records so turns can resume after interruption.
- Promote durable user preferences, recurring repo conventions, and other high-value facts into `/.agents/memory/*.md`.
- Do not store secrets, access tokens, or noisy transient chat history in long-term memory.

## Tooling

- Prefer project tools when the capability already exists in `/.agents/tools`.
- `ctf_orchestrator_inventory` inspects the bundled CTF sandbox orchestrator assets.
- `vuln_kb_lookup` searches the local CVE knowledge base.
- `report_export` exports an existing DigAgent report artifact.

## MCP

- Prefer MCP only when built-in deepagents filesystem/shell tools and project tools are not enough.
- Prefer enabling only the specific MCP servers needed by the active agent profile.
