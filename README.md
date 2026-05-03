# DigAgent

DigAgent 是一个受控安全分析 Agent 运行时，支持 CLI 和 WebUI 两种使用方式。项目目标是让长链安全分析任务具备可审计执行、显式权限审批、多 Agent 协作、证据沉淀和结构化报告导出能力。

## 当前能力

- CLI 入口：支持 `chat`、`run`、审批处理和 API 服务启动。
- FastAPI 后端：提供 REST API 与 SSE 流式输出。
- React + Vite WebUI：支持会话、运行过程、审批、附件和报告查看。
- 文件持久化：记录 session、turn、evidence、report、artifact、approval 和 audit log。
- 精简事件历史：默认不持久化原始 `langgraph_*` 事件与 `assistant_chunk`，Inspector 按需读取任务图。
- Agent profiles 与本地 skills：支持角色化执行、权限决策和结构化报告导出。
- 多 Agent workspace：在应用层按 `cwd`、`FilesystemBackend`、scope 和附件上下文隔离工作区。
- 项目工具集：包含 shell、web、CVE、report 相关工具，以及使用项目 `.venv` 的 `python_exec`。
- 附件上传：上传文件会作为 artifact 保存，并关联到 message、turn 和当前 agent workspace。
- 多 Agent 协作提示词：强化 planner、deepworker、report-writer、memory-curator 等角色分工。
- Markdown 与 PDF 导出：支持将分析结果交付为可保存的报告。

## 快速开始

1. 安装 Python 依赖：`uv sync --all-extras`
2. 安装 WebUI 依赖：`cd webui && npm install`
3. 构建前端：`cd webui && npm run build`
4. 启动 API/UI：`python -m digagent serve`
5. 运行 CLI 任务：`python -m digagent run --task "分析当前项目源码"`

## 环境变量

复制 `.env.example` 为 `.env`，并按使用的模型服务配置：

- `OPENAI_API_KEY`
- `BASE_URL`
- `MODEL`

离线测试可设置：

- `DIGAGENT_USE_FAKE_MODEL=1`

可选集成：

- `GITHUB_PERSONAL_ACCESS_TOKEN`：用于 GitHub MCP server
- `SHODAN_API_KEY`：用于 Shodan MCP server

## 运行时说明

- workspace 是应用层隔离，不等同于 OS 沙盒或容器隔离。
- 原始 LangGraph stream event 默认不持久化，避免事件模型膨胀。
- 上传附件会作为 artifacts 存储，并物化到当前 turn 或 agent workspace。
- Debug-first：运行错误应显式暴露，避免用静默 fallback 掩盖真实问题。

## 验证

后端测试建议使用 60 秒超时：

```bash
TMPDIR=/tmp timeout 60 ./.venv/bin/python -m pytest -q -p no:cacheprovider
```

前端测试与构建：

```bash
cd webui && npm test
cd webui && npm run build
```
