# DigAgent 15 分钟 PPT 主稿

## 使用方式

- 15 页主 deck，讲述节奏约 30 秒/页，总时长 13–15 分钟
- 每页固定四段：**页面目标 / 展示要点 / 口播词 / Challenge 抓手**
- 讲述顺序按运行链路展开，不按目录结构机械介绍
- 口播词控制在 80–120 字，Challenge 抓手以 Q/A 对呈现，单条答不超过 40 字

---

## 第 1 页：封面与结论先行

### 页面目标

定调：DigAgent 是受控的安全分析 agent，不是普通聊天机器人。

### 展示要点

- 项目名：DigAgent
- 一句话定位：可审计、可审批、可导出、可恢复的安全分析 agent
- 入口：CLI + WebUI
- 今日口径：已实现事实 / 设计思想 / 已知差距

### 口播词

DigAgent 的核心不是让模型会调工具，而是把一次安全分析任务做成可控运行时。它在 CLI 和 WebUI 上，都能把用户意图拆成任务图、工具调用、审批、证据、报告与记忆提交的完整链路。今天围绕三件事展开：已实现的工程事实、设计背后的取舍、仍然存在的差距。

### Challenge 抓手

- Q：和普通 agent 的区别？A：区别在 harness，不在聊天能力。
- Q：是不是就是 prompt engineering？A：不是，关键是 Session/Run 状态机、TaskGraph、权限审批与文件落盘。

---

## 第 2 页：要解决的问题

### 页面目标

说明为什么需要受控 agent，而不是让模型直连外部动作。

### 展示要点

- 安全分析场景天然高风险
- 普通 agent 的四个痛点：不可审计、不可恢复、边界模糊、结论不可追溯
- DigAgent 目标：受控执行、证据驱动、报告可导出

### 口播词

安全分析涉及 shell、网络、代码修改、外部资源和审批，每一步都可能影响结论和风险边界。普通 agent 把这些动作交给模型自由编排，出了问题无从复盘。DigAgent 的目标是把这几类高风险动作纳入统一的运行时框架，让每个动作都可追溯、可审批、可回滚。

### Challenge 抓手

- Q：为什么做得这么重？A：因为每一步都会影响结论的可信度。
- Q：轻量方案不行吗？A：轻量方案在出事那一刻会丢掉全部证据。

---

## 第 3 页：总体架构

### 页面目标

给出五层地图，后续所有页都回到这张图。

### 展示要点

- Prompt 层：角色与输出契约
- Context 层：阶段化最小必要事实
- Harness 层：状态机 / 图执行 / 权限 / 审批 / 审计
- Capability 层：tool / skill / plugin / MCP
- Persistence + API + WebUI

### 口播词

系统拆成五层。Prompt 定义角色和契约，Context 按当前阶段组装事实，Harness 真正执行并控制状态，Capability 汇聚工具与外部能力，Persistence 与前端负责落盘和呈现。分层的目的是让四件事分别可替换：换提示词、换执行骨架、换权限策略、换前端展示，彼此不互相污染。

### Challenge 抓手

- Q：为什么分这么细？A：为了让提示词、执行、权限、存储各自可替换。
- Q：这张图是宣传图还是真的这么写的？A：后面每一页都对应一个具体模块。

---

## 第 4 页：Prompt 设计

### 页面目标

讲清 Claude Code 范式下的 prompt 分层。

### 展示要点

- `config/agents/*.yaml` 定义 profile
- `config/prompts/**` 存放 system / runtime prompt
- `_shared` 片段集中共享契约
- `AgentBridge` 强制 JSON 输出 + schema 校验 + repair
- 角色矩阵：planner / worker / writer / curator

### 口播词

Prompt 不是硬编码字符串。profile 先声明角色、模型和 allowlist，prompts 目录再把共享片段和角色片段拼成完整 system prompt。planner、writer、curator、worker 各自独立，互不越界。结构化输出场景由 AgentBridge 强制约束：只输出原始 JSON，Pydantic 校验不过就 retry，再不过就 repair。

### Challenge 抓手

- Q：怎么保证模型不乱输出？A：不是信任模型，而是桥接层强制 JSON + schema 校验。
- Q：prompt 注入怎么办？A：共享契约把输入、HTML、日志全视为不可信数据。

---

## 第 5 页：Context 设计

### 页面目标

把 context 讲成"最小必要事实注入"，不是塞更多 token。

### 展示要点

- planner 注入：scope、allowlist、specialist、skill/plugin/MCP 目录、memory hits
- direct answer 注入：session/run 状态、最近证据、审批摘要
- subagent 注入：衰减后的 `DelegationGrant` 与 worker 历史
- skill 只作为知识层，不授予执行权

### 口播词

DigAgent 的 context 不是统一模板。planner 看到的是做决策所需的全部能力面，direct answer 看到的是当前状态快照，subagent 只看到衰减后的授权。这样做的代价是多写几条拼装代码，收益是大幅降低错位上下文和越权执行风险。

### Challenge 抓手

- Q：为什么不给 subagent 全量上下文？A：全量上下文会放大幻觉与越权。
- Q：skill 为什么不能直接执行？A：skill 属于知识层，执行权只在 tool 层授予。

---

## 第 6 页：Harness 核心

### 页面目标

把项目的工程壁垒讲清楚。

### 展示要点

- `SessionManager`：消息路由 + run 生命周期
- `GraphManager`：DAG 维护 + ready 集计算
- `AgentBridge`：模型契约 + JSON 约束
- `ToolRegistry`：manifest + adapter 目录
- `PermissionEngine`：ALLOW / CONFIRM / DENY
- `FileStorage`：真相落盘

### 口播词

Harness 是整个项目最重要的部分，它把模型输出变成受控的状态变更。六个核心组件各司其职：SessionManager 管消息和 run 生命周期，GraphManager 管 DAG，AgentBridge 管模型契约，ToolRegistry 管目录，PermissionEngine 管权限，FileStorage 管真相落盘。执行真相只承认文件，不承认模型上下文。

### Challenge 抓手

- Q：哪里是真正的执行真相？A：在 `data/` 下的 session / run / evidence / approval / report 文件。
- Q：模型说的算数吗？A：不算，文件落盘才算。

---

## 第 7 页：Session 与 Run 状态机

### 页面目标

说明为什么系统能"边聊天、边受控执行"。

### 展示要点

- Session 状态：`idle / active_run / awaiting_approval / awaiting_user_input / archived`
- Run 状态：`created → planning → running → aggregating → reporting → completed`
- 消息分流：direct_answer / clarification / approval / new_run_request / cancel
- 同一 Session 同一时刻只允许一个 active Run

### 口播词

系统把长期聊天容器 Session 和单次受控执行 Run 拆开。用户问"当前进度是什么"走 direct answer，不起新 run；回复审批或补充澄清走 continue；已有活跃 run 时，新独立任务会被 reject。这套分流逻辑让系统可以一边回答过程性问题，一边保留 run 的执行真相。

### Challenge 抓手

- Q：能并发多个 run 吗？A：当前设计不允许，run 内部才允许并行。
- Q：为什么不允许？A：并发 run 会让审批与证据语义互相污染。

---

## 第 8 页：TaskGraph、Scheduler 与重规划

### 页面目标

说明为什么是 DAG，不是普通步骤列表。

### 展示要点

- `TaskNodeKind`：`input / tool / skill / subagent / aggregate / report / export`
- ready 集按依赖关系实时计算
- 批次选择由 planner 决定，调度分发由 runtime 执行
- clarify 后走 `_replace_clarified_branch` supersede 旧分支

### 口播词

planner 输出的是结构化任务图。runtime 能判断哪些节点 ready、哪些在等审批、哪些已 superseded。clarify 之后不是简单追加步骤，而是把旧分支节点标为 deprecated、挂上 `superseded_by`、新分支接在 clarify 节点之后。这让重规划是图级别的分支替换，而不是文本级别的补充。

### Challenge 抓手

- Q：重规划是整图重来吗？A：不是，`GraphEditOp` 与 supersede 支持局部修补。
- Q：凭什么说是 DAG？A：`GraphManager` 每次刷新都做无环校验。

---

## 第 9 页：Multi-agent 设计

### 页面目标

把 oh-my-opencode 的 supervisor pattern 映射到本项目。

### 展示要点

- root supervisor：`sisyphus-default`
- planner：`prometheus-planner`
- workers：`hephaestus-deepworker` / `hackey-ctf`
- writer：`report-writer`
- curator：`memory-curator`
- `DelegationGrant`：工具交集 + 禁止二次委派 + 禁止写报告/记忆

### 口播词

只有 root supervisor 持有全局权力。subagent 必须由 planner 显式指定 `owner_profile_name`，runtime 不按关键词猜 specialist。subagent 执行时拿到的是衰减后的 DelegationGrant，工具取根 profile 与 worker profile 的交集，且明确排除 `delegate_subagent`、`report_export`、`skill_consult`，不允许继续委派、不允许写报告、不允许写长期记忆。

### Challenge 抓手

- Q：subagent 怎么防止乱调工具？A：每次 tool_call 仍要形成 ActionRequest 过 permission/approval/audit。
- Q：为什么叫受控 multi-agent？A：目标是切专项，不是让层级自治扩张。

---

## 第 10 页：Capability 分层

### 页面目标

讲清 tool / skill / plugin / MCP 的边界。

### 展示要点

- tool：manifest + adapter，统一执行入口
- skill：方法论与 references，纯知识层
- plugin：本地 capability bundle，命令进入 catalog
- MCP：stdio server，默认保守接入

### 口播词

项目刻意把知识层和执行层分开。skill 给方法和参考但不给权限；tool 是内置执行能力；plugin 是本地 bundle，命令会动态并入 catalog；MCP 是可选的 stdio 外部能力入口。四者最终统一纳入 permission 和 audit，不会因为来源不同而绕开管控。

### Challenge 抓手

- Q：skill 和 plugin 本质区别？A：skill 解决"知道怎么做"，plugin 解决"能执行什么"。
- Q：MCP 没接上是不是功能没做完？A：不是，是默认保守关闭以控制边界。

---

## 第 11 页：Permission、Approval、Audit

### 页面目标

把安全控制链讲透。

### 展示要点

- 决策三态：`ALLOW / CONFIRM / DENY`
- 触发 CONFIRM 的高风险标签：`filesystem_write / shell_exec / network / external_exploit / export_sensitive`
- 审批 = challenge-token + 双摘要
- `approval_digest`：动作身份指纹
- `policy_key`：策略等价键，支持 supersede

### 口播词

权限不是一个布尔值。高风险动作必须走审批链，而审批不是模型回一句"同意"，而是 challenge-token 机制。系统区分两种摘要：digest 记录动作身份，policy_key 记录策略等价性。动作变了但策略仍等价，digest 可以滚动更新；策略键也变了，就要 supersede 旧审批生成新的。

### Challenge 抓手

- Q：为什么要两种哈希？A：动作身份相同和策略等价不是一回事。
- Q：审批会被模型绕过吗？A：token 由 runtime 下发，模型没有签发权。

---

## 第 12 页：Evidence → Report → Export

### 页面目标

说明报告不是让模型写作文，而是证据驱动。

### 展示要点

- artifact / evidence 双层：原始产物 vs 可引用证据
- `ReportDossier` 汇总图/证据/产物/记忆命中
- writer 产 `ReportDraft`，validator 强制 `evidence_refs` 校验
- exporter 输出 Markdown，再导 PDF

### 口播词

tool 或 subagent 的输出先存为 artifact，再抽成 evidence。最终报告不是直接拼 Markdown，而是先由 runtime 构建 dossier，writer 生成 draft，validator 校验 kind / summary / evidence_refs 三件事，通过后 exporter 才导 Markdown 和 PDF。任何 finding 没有合法 evidence_refs 都会被拦截。

### Challenge 抓手

- Q：报告真实性怎么保证？A：validator 拦截无证据结论。
- Q：PDF 导出失败怎么办？A：显式失败，不走静默降级。

---

## 第 13 页：Layered Memory

### 页面目标

讲清 OpenClaw 风格分层记忆，且不夸大成向量平台。

### 展示要点

- 四层载体：`MEMORY.md` / memory records / wiki entries / daily notes
- `memory-curator` 产出 daily_note / memory_candidates / wiki_entries
- 只有 root agent 可提交长期记忆
- 检索 = BM25 + scope + sensitivity 过滤

### 口播词

memory 是分层、文件型、带 evidence 引用的记忆系统。run 完成后由 memory-curator 生成日报、长期记忆候选和 wiki 条目，再由 root runtime 落盘。检索不是向量库，而是 BM25 加上 scope 与 sensitivity 过滤。这样做的代价是没有语义召回，收益是每条记忆都能追溯到具体证据。

### Challenge 抓手

- Q：为什么不用 embedding？A：当前阶段优先可审计，BM25 文件索引足够支撑 scoped retrieval。
- Q：会不会记错？A：只有 root 能写，curator 只提候选。

---

## 第 14 页：API、WebUI 与可观测性

### 页面目标

说明这不是后端黑盒，而是完整可视化系统。

### 展示要点

- REST 路由组：health / catalog / session / run / approval / evidence / report / cve
- SSE 事件流：覆盖生命周期 / 图变更 / 审批 / 证据 / 终止
- 前端时间线、任务图画布、审批卡片、证据卡片、报告卡片
- 浏览器端本地设置存储

### 口播词

后端通过 REST 暴露 session、run、approval、evidence、report、cve 接口，通过 SSE 持续推送 plan、task_graph_updated、approval_required、evidence_added、report_ready 等事件。WebUI 通过 EventSource 订阅 session 级事件流，把每一次图变更、审批和证据实时映射到时间线、图谱和检查面板上。

### Challenge 抓手

- Q：怎么证明图谱不是静态页？A：前端订阅 SSE，图谱和时间线实时刷新。
- Q：SSE 掉线怎么办？A：前端重连后从 run 状态重建时间线。

---

## 第 15 页：测试证据与已知差距

### 页面目标

主动暴露事实，建立可信度。

### 展示要点

- 覆盖场景：acceptance / routing / security / memory / plugin / MCP / report
- 2026-04-18 本地验证：**37 通过 / 1 失败**
- 失败项：`test_non_exclusive_ready_nodes_run_in_parallel`，并行耗时约 1.50s，阈值 <0.55s
- 三条已知 gap：调度性能、依赖声明差异、MCP 默认关闭

### 口播词

系统有端到端测试覆盖，但我不会把"有设计"说成"已达标"。2026-04-18 的本地只读验证结果是 37 通过 1 失败。失败项是并行 ready 节点的端到端耗时约 1.50 秒，未达到阈值 0.55 秒。此外，pyproject 声明了 langchain 生态依赖，但主执行路径是自研 harness；MCP 默认 enabled 为 false，catalog 可见但不可静默执行。

### Challenge 抓手

- Q：为什么主动讲 gap？A：区分设计目标和实现现状，避免被动暴露。
- Q：调度性能什么时候能达标？A：调度语义已支持并行，性能优化待跟进。
