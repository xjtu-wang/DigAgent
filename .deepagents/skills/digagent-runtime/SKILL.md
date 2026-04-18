---
name: digagent-runtime
description: DigAgent runtime conventions, including how to maintain long-term memory and how MCP/tools are wired in this project.
---

# DigAgent Runtime

## Long-Term Memory

- Long-term memory lives in `/.deepagents/AGENTS.md`.
- Session-scoped notes live in `/.deepagents/memories/`.
- When the user asks you to remember a durable project rule or preference, update those files with `edit_file` immediately.

## MCP

- Prefer MCP only when built-in deepagents filesystem and shell tools are not enough.
- Start by listing servers and tools before calling an MCP tool blindly.

## Custom Tools

- `web_search` is for finding candidate URLs.
- `web_fetch` is for fetching a concrete URL.
- `vuln_kb_lookup` is for the local CVE knowledge base.
- `run_plugin_command` is for project plugin commands that are not covered by deepagents built-ins.
