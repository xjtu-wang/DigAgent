# DigAgent

DigAgent is a controlled security-analysis agent that can run from CLI or WebUI.

Current MVP includes:

- CLI entrypoints for chat, run, approval, and API serving
- FastAPI backend with REST + SSE streaming
- React + Vite WebUI
- File-backed sessions, runs, evidence, reports, artifacts, approvals, and audit logs
- Agent profiles, local skill loading, permission decisions, and structured report export
- Markdown and PDF export

## Quick start

1. Install Python deps: `uv sync --all-extras`
2. Install WebUI deps: `cd webui && npm install`
3. Build frontend: `cd webui && npm run build`
4. Run API/UI: `python -m digagent serve`
5. Run CLI task: `python -m digagent run --task "分析当前项目源码"`

## Environment

Copy `.env.example` to `.env` and provide:

- `OPENAI_API_KEY`
- `BASE_URL`
- `MODEL`

For offline tests, set `DIGAGENT_USE_FAKE_MODEL=1`.

Optional integrations:

- `GITHUB_PERSONAL_ACCESS_TOKEN` for the GitHub MCP server
- `SHODAN_API_KEY` for the Shodan MCP server
