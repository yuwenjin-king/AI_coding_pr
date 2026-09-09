# CodePilot Agent 开发计划

> 本文件是 README 第 8 节「分阶段实施」的落地版，也是项目进度的唯一事实来源。
> 每个 Phase 包含：目标、任务清单、验收标准、状态。完成一个 Phase 后更新状态并在 README 同步一句话摘要。

## 状态总览

| Phase | 主题 | 核心能力 | 状态 |
| --- | --- | --- | --- |
| Phase 1 | 单 Agent 分析 | 工单工作台 + 只读工具 + 分析报告（不改代码） | ✅ 已完成 |
| Phase 2 | Tool Agent | git/run_test 真实工具、通用 Agent Loop、SSE 实时观测 | 🟡 代码完成，待真实 key 端到端 |
| Phase 3 | RAG Agent | Qdrant + Embedding、历史工单/文档检索进入上下文 | 🟡 代码完成，待真实 key 入库与端到端 |
| Phase 4 | Coding Agent | 分支上真实改代码、测试迭代收敛、Diff + HITL 审批 | 🟡 代码完成（31 测试全绿），待真实 key 端到端 |
| Phase 5 | Multi-Agent | Requirement/Review Agent 编排 + 返工循环 | 🟡 代码完成（36 测试全绿），待真实 key 端到端 |
| Phase 6 | 平台化 | Memory、可观测性、Guardrail、LLM 重试已交付；评估/断点恢复/部署治理计划中 | 🟡 核心四件套完成（49 测试全绿），待端到端 |

## 环境事实（随时更新）

- MySQL：`docker compose up -d mysql`（已运行）。
- 后端 `uvicorn app.main:app --reload --port 8000`，前端 `npm run dev`（5173）。
- **`.env` 的 `OPENAI_API_KEY` 目前仍是占位符**：LLM 端到端流程会失败，但单测使用 FakeLLM 不受影响。
- 靶场仓库 `playground/shopai` 是独立 git 仓库（Phase 4 做 clone/branch/commit 的基础）。

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
2. ⏳ 打开 BUG-1024 → 让 AI 处理 → 前端能实时看到每步工具调用与 Observation —— **阻塞：`.env` 仍是占位 key**，SSE 通道已实测可用。
3. ⏳ Agent 在分析中能调用 `git_log`/`run_test` 并把测试结果（1 passed, 1 xfailed）写进根因分析 —— 同上，工具层已单测验证（真实跑出 `1 passed, 1 xfailed`）。
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

1. ⏳ BUG-1026（库存扣减）运行时，Agent 能检索到 BUG-387 的「Redis/MySQL 并发不一致」经验并在报告中引用 —— 代码与单测就绪，**阻塞：真实 key 入库**。
2. ✅ 检索工具返回带来源与分数，报告中可追溯。

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

1. ⏳ BUG-1024 一键跑通：Agent 定位 → 改 `payment_consumer.py` → 测试由 1 xfailed 变 2 passed → 生成 Diff → 等待审批 —— FakeLLM 版已在单测中完整验证，**待真实 key E2E**。
2. ✅ 审批前后靶场 main 分支零污染（单测断言主 checkout 未被改动；worktree 隔离）。
3. ⏳ 多次失败后仍能收敛 —— 依赖真实模型行为，E2E 观察。

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

1. ⏳ REQ-1025 真实跑通多 Agent 协作 —— FakeLLM 版已验证，待真实 key E2E。
2. ⏳ Review Agent 对真实 diff 提出具体意见并驱动返工 —— 同上。

---

## Phase 6：平台化（核心四件套完成，待端到端）

### 目标

从 Demo 走向平台：经验沉淀（Memory）、可观测、可评估、部署治理。

### 任务（按优先级，可裁剪）

- [x] Memory：run 成功后沉淀经验（分析 run 完成即沉淀；coding run 以 HITL 批准为准），新工单启动时召回 top-3 注入上下文（关键词重叠 + 新近度排序，`MEMORY_ENABLED` 可关）
- [x] 可观测：run 级 token/耗时/工具统计（`agent_runs.stats_json`，随 trace 实时更新），前端运行页统计行（LLM 调用 / tokens↑↓ / LLM 耗时 / 工具调用 / 步数）
- [x] Retry：LLM 瞬时错误（连接/超时/429/5xx）指数退避重试（`LLM_MAX_RETRIES`、`LLM_RETRY_BASE_SECONDS`），鉴权/参数错误不重试快速失败
- [x] Guardrail：write_file 密钥扫描（sk-/AKIA/私钥/ghp_/xox 命中即拦截）、diff 变更行数上限（`AGENT_MAX_DIFF_LINES`，超限 run 失败并丢弃工作区）
- [ ] Evaluation：固定工单集的回归评测（定位准确率、修复通过率）
- [ ] Checkpoint：run 断点恢复
- [ ] Deploy：HITL 批准后触发（本地 compose 模拟 CI/CD）
- [ ] Agent Hub：Agent 定义注册/版本化（6 个内置 + 自定义）

### 验收标准

1. ⏳ 同类工单第二次运行明显少于第一次的探索步数（Memory 生效）—— FakeLLM 版已验证召回注入，真实效果待 E2E。
2. ⬜ 评测报告可对比两个版本 Agent 的成功率。
3. ⬜ 全链路：工单 → 分析 → 检索 → 修复 → 测试 → Review → 审批 → 部署 → 回写工单状态。

---

## 维护约定

- 每完成一个任务勾选对应复选框；Phase 完成时更新状态总览与 README 首行。
- 新增依赖同步 `requirements.txt` / `package.json`，并在本文件「环境事实」记录影响。
- 每个 Phase 的验收标准全部满足才算完成；不满足就保持「开发中」并写明阻塞原因。
