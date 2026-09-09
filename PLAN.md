# CodePilot Agent 开发计划

> 本文件是 README 第 8 节「分阶段实施」的落地版，也是项目进度的唯一事实来源。
> 每个 Phase 包含：目标、任务清单、验收标准、状态。完成一个 Phase 后更新状态并在 README 同步一句话摘要。

## 状态总览

| Phase | 主题 | 核心能力 | 状态 |
| --- | --- | --- | --- |
| Phase 1 | 单 Agent 分析 | 工单工作台 + 只读工具 + 分析报告（不改代码） | ✅ 已完成 |
| Phase 2 | Tool Agent | git/run_test 真实工具、通用 Agent Loop、SSE 实时观测 | ✅ E2E 验证通过（2026-09-09） |
| Phase 3 | RAG Agent | Qdrant + Embedding、历史工单/文档检索进入上下文 | ✅ E2E 验证通过：BUG-1026 引用 BUG-387 并合并（2026-09-10） |
| Phase 4 | Coding Agent | 分支上真实改代码、测试迭代收敛、Diff + HITL 审批 | ✅ E2E 验证通过：BUG-1024 闭环+合并（2026-09-09） |
| Phase 5 | Multi-Agent | Requirement/Review Agent 编排 + 返工循环 | ✅ E2E 验证通过：REQ-1025 闭环+合并（2026-09-10） |
| Phase 6 | 平台化 | Memory、可观测性、Guardrail、LLM 重试已交付；评估/断点恢复/部署治理计划中 | 🟡 核心五项完成（53 测试全绿），Memory/HITL 已在真实 run 中生效 |

## 环境事实（随时更新）

- MySQL：`docker compose up -d mysql`（已运行）。
- 后端 `uvicorn app.main:app --reload --port 8000`，前端 `npm run dev`（5173）。
- LLM：`.env` 已配置真实 key（`LLM_API_KEY`，qwen3.7-flash @ 阿里云 MaaS 专用端点），RAG 入库完成（Qdrant 5 chunks）。
- **`playground/shopai` 不是独立 git 仓库**，是主仓库的普通目录：worktree/分支/HITL 合并都发生在主仓库上（2026-09-09 实测，agent 分支 `agent/BUG-1024-run2` 已合并，BUG-1024 修复已进 main）。
- **注意**：BUG-1024 的缺陷已在 main 修复（xfail 已移除、测试 3 passed），重跑该场景会因「无变更」而失败，属预期。

---

## Phase 1：单 Agent 分析（已完成）

交付内容：

- FastAPI + MySQL + React 工单工作台：工单列表 / 详情 / 「让 AI 处理」入口。
- `AgentRun` 状态机：queued → running → succeeded/failed。
- Task Agent（ReAct 循环）：只读工具 `list_dir` / `read_file` / `search_code`，输出中文 Markdown 报告（问题理解、Root Cause、建议文件、修复步骤、测试建议、置信度）。
- 工具沙箱：路径逃逸检查（`_safe_path`），写类工具全部注册为 blocked 占位。
- 种子工单 BUG-1024 / REQ-1025 / BUG-1026；靶场含 BUG-1024 复现（重投递被误判为重复消息）与 xfail 测试。

---

## Phase 2：Tool Agent（开发中）

### 目标

README 的定义：加入 `run_test`、`git_diff`，跑通「Agent → Tool → Observation → Agent → …」的真正 Agent Loop，并让人能实时观察到每一步。

### 任务

- [x] 计划文档 PLAN.md
- [x] 工具注册表按 Phase 门控：`schemas_for_phase(phase=N)` 只暴露 `phase <= N` 的工具，`AGENT_PHASE` 可配置
- [x] 真实 git 工具：`git_status` / `git_diff` / `git_log`（子进程执行，限定靶场仓库）
- [x] `run_test` 工具：在靶场以子进程执行 pytest，带超时，回传结构化输出（exit code + stdout 摘要）
- [x] 通用 Agent Loop：抽出 `runtime/agent_loop.py`（ReAct 循环、步数预算、工具异常转 Observation、trace 事件流），task_agent 只负责提示词与报告契约
- [x] SSE 实时事件：`GET /api/runs/{run_id}/events`，运行中逐步推送 run 快照，终态后关闭
- [x] 前端 Trace 观测：EventSource 订阅、工具调用与 Observation 输出可展开
- [x] 后端单测：FakeLLM 驱动 loop、工具沙箱、Phase 门控、SSE 端点（20 个用例，sqlite + FakeGateway，不碰 MySQL/真实 LLM）
- [x] README 同步（当前实现 Phase 2、测试命令）

### 验收标准

1. ✅ `cd backend && pytest` 全绿（20 passed，不依赖真实 LLM key）。
2. ✅ 打开 BUG-1024 → 让 AI 处理 → 前端能实时看到每步工具调用与 Observation（SSE 通道实测，真实 run 51s 内 11 次 LLM + 工具调用全程推送）。
3. ✅ Agent 能调用 `git_log`/`run_test` 并把测试结果写进根因分析（真实 run 的 trace 中 git/run_test 调用可见，测试结果进入报告）。
4. ✅ `AGENT_PHASE=1` 时 run_test/git 工具对模型不可见（有单测锁定）。

---

## Phase 3：RAG Agent（计划）

### 目标

接入知识库：技术/架构文档、历史工单（BUG-387 等）、编码规范，检索结果进入 Agent 上下文。

### 任务

- [x] docker compose `--profile rag` 启 Qdrant；`qdrant-client` 入 requirements
- [x] Embedding：OpenAI 兼容 embeddings 接口（DashScope text-embedding-v4，gateway.embed 批量分片）
- [x] 入库流水线：`python -m app.knowledge.ingest`（knowledge/seed/*.md + tickets 表切块 → 向量化 → upsert）
- [x] 检索工具 `search_document` / `search_ticket` 从占位改为真实检索（top-k + 分数 + 来源）
- [ ] 可选进阶：Hybrid Search（BM25 + 向量）、Rerank（暂缓，向量检索够用）
- [x] 触发方式：工单启动时自动检索注入（top-3）+ Agent 主动调用两种都支持
- [x] LLM 配置：`LLM_API_KEY/LLM_BASE_URL/LLM_MODEL` 为标准命名（兼容旧 `OPENAI_*`），qwen 模型自动使用 DashScope endpoint

### 验收标准

1. ✅ BUG-1026（库存扣减）运行时，Agent 检索到 BUG-387 经验并在报告中实质性引用：「与 BUG-387 描述的 Redis/MySQL 并发不一致本质相同」（读-改-写竞态丢失更新），据此定位并加锁修复 + 并发回归测试（19 passed），HITL 批准合并（真实 LLM，110s / 15 次调用 / 79452+6424 tokens，2026-09-10）。
2. ✅ 检索工具返回带来源与分数，报告中可追溯。
3. ⚠️ 评测记录：该场景在 24 步预算下两轮未收敛（偶发并发类难题，探索成本高），32 步预算收敛——复杂工单预算需按难度配置。

---

## Phase 4：Coding Agent（代码完成，待端到端）

### 目标

Agent 在独立分支上真实修改代码：改 → 测 → 失败分析 → 再改 → 收敛，产出 Diff 供人工审批。

### 任务

- [x] 运行前准备：`git worktree` + 分支隔离（`agent/<工单号>-run<N>`，`.agent-workspaces/`），拒绝可一键丢弃
- [x] 开放 `write_file`（仅限工作区内、后缀白名单、64KB 上限；phase<4 调用即 blocked）
- [x] 修复循环：agent loop 内 run_test ↔ write_file 自主迭代（coding 模式步数 +12）
- [x] run 结束系统自动：提交 agent 分支 → 复跑测试 → 采集 diff/test_summary → `needs_review`
- [x] HITL 落地：批准 = merge 回主分支（主工作区脏则 409 提示）+ 工单置 resolved；拒绝 = 删工作区/分支 + 工单回 open
- [x] 前端：Diff/测试输出面板、needs_review 审批盒（批准并合并 / 拒绝并丢弃）
- [x] 数据模型：agent_runs 新增 mode/branch/workspace/diff_md/test_summary（启动时自动 ALTER 迁移）
- [x] 测试：worktree 生命周期、写沙箱门控、coding 闭环到 needs_review、批准合并、拒绝丢弃（tmp git 仓库隔离，不碰真实仓库）

### 验收标准

1. ✅ BUG-1024 一键跑通：Agent 定位 → 改 `payment_consumer.py` → 移除 xfail → 自主补回归测试 → 测试 3 passed → 生成 Diff → needs_review → **HITL 批准合并进 main**（真实 LLM，51s / 11 次 LLM 调用 / 37936+3624 tokens，2026-09-09）。
2. ✅ 审批前后靶场 main 分支零污染（worktree 隔离；合并仅在批准后发生）。
3. ✅ 迭代收敛（真实 run 中 run_test↔write_file 自主循环后测试全绿）。

---

## Phase 5：Multi-Agent（代码完成，待端到端）

### 目标

单 Agent 上下文扛不住时拆角色：Orchestrator 调度 Requirement / Coding / Test / Review。

### 任务

- [x] Orchestrator 按工单类型编排：BUG → Coding(+Review)；REQ → Requirement → Coding(+Review)；phase<5 回退单 Agent
- [x] Requirement Agent：需求拆解 JSON 契约（理解/验收标准/模块/风险/测试计划），产出注入 Coding 提示词并保留在报告顶部
- [x] Review Agent：审查 diff+测试输出（blocker/major/minor 分级），`request_changes` 驱动**恰好一轮**返工（意见回灌 Coding Agent，返工后重测；人工是最终门）
- [x] 角色产物结构化传递 + trace 记录 `agent` 事件（前端可展开查看）
- [x] trace 跨轮续写（rework 不清空前序事件）
- [x] 测试：需求/审查 JSON 契约（含 ```json 围栏容错）、REQ 全流水线含返工、BUG 直通 Review 不返工

### 验收标准

1. ✅ REQ-1025 真实跑通多 Agent 协作：Requirement（验收标准）→ Coding（171s 交付取消订单，diff 限 order_service/main/test 三文件）→ Review → needs_review → **HITL 批准合并**（真实 LLM，24 次调用 / 201756+9549 tokens，2026-09-10）。
2. ✅ Review Agent 对真实 diff 出具意见：第一轮 request_changes 驱动返工（返工启动后死于 trace 超长 bug，已修复并回归）；第二轮直接 approve —— 两种裁决路径都实测过。

---

## Phase 6：平台化（核心四件套完成，待端到端）

### 目标

从 Demo 走向平台：经验沉淀（Memory）、可观测、可评估、部署治理。

### 任务（按优先级，可裁剪）

- [x] Memory：run 成功后沉淀经验（分析 run 完成即沉淀；coding run 以 HITL 批准为准），新工单启动时召回 top-3 注入上下文（关键词重叠 + 新近度排序，`MEMORY_ENABLED` 可关）
- [x] 可观测：run 级 token/耗时/工具统计（`agent_runs.stats_json`，随 trace 实时更新），前端运行页统计行（LLM 调用 / tokens↑↓ / LLM 耗时 / 工具调用 / 步数）
- [x] Retry：LLM 瞬时错误（连接/超时/429/5xx）指数退避重试（`LLM_MAX_RETRIES`、`LLM_RETRY_BASE_SECONDS`），鉴权/参数错误不重试快速失败
- [x] Guardrail：write_file 密钥扫描（sk-/AKIA/私钥/ghp_/xox 命中即拦截）、diff 变更行数上限（`AGENT_MAX_DIFF_LINES`，超限 run 失败并丢弃工作区）
- [x] Evaluation：固定工单集回归评测框架（`python -m app.eval.run_eval`：BUG-1024 修复闭环 / BUG-1026 RAG 引用 / REQ-1025 多 Agent，逐项检查输出 Markdown + JSON 报告；评分器纯逻辑单测覆盖）—— 真实模型跑分待 E2E
- [ ] Checkpoint：run 断点恢复
- [ ] Deploy：HITL 批准后触发（本地 compose 模拟 CI/CD）
- [ ] Agent Hub：Agent 定义注册/版本化（6 个内置 + 自定义）

### 验收标准

1. ✅ Memory 生效：HITL 批准的修复自动沉淀经验（3 条：BUG-1024/REQ-1025/BUG-1026），新 run 启动即召回注入（BUG-1026 第三轮 15 步收敛 vs 前两轮 24 步耗尽，方向性证据）。
2. ✅ 评测报告：`python -m app.eval.run_eval`（三轮实测，报告含 token/耗时/通过率；BUG-1026 记录了预算敏感性）。
3. 🟡 全链路：工单 → 分析 → 检索 → 修复 → 测试 → Review → 审批 → 回写工单状态 ✅（三张工单全流程实测）——「部署」环节未实现（Phase 6 剩余项）。

---

## 维护约定

- 每完成一个任务勾选对应复选框；Phase 完成时更新状态总览与 README 首行。
- 新增依赖同步 `requirements.txt` / `package.json`，并在本文件「环境事实」记录影响。
- 每个 Phase 的验收标准全部满足才算完成；不满足就保持「开发中」并写明阻塞原因。
