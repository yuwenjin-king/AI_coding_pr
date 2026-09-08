# CodePilot Agent 开发计划

> 本文件是 README 第 8 节「分阶段实施」的落地版，也是项目进度的唯一事实来源。
> 每个 Phase 包含：目标、任务清单、验收标准、状态。完成一个 Phase 后更新状态并在 README 同步一句话摘要。

## 状态总览

| Phase | 主题 | 核心能力 | 状态 |
| --- | --- | --- | --- |
| Phase 1 | 单 Agent 分析 | 工单工作台 + 只读工具 + 分析报告（不改代码） | ✅ 已完成 |
| Phase 2 | Tool Agent | git/run_test 真实工具、通用 Agent Loop、SSE 实时观测 | 🟡 代码完成，待真实 key 端到端 |
| Phase 3 | RAG Agent | Qdrant + Embedding、历史工单/文档检索进入上下文 | ⬜ 计划 |
| Phase 4 | Coding Agent | 分支上真实改代码、测试迭代收敛、Diff + HITL 审批 | ⬜ 计划 |
| Phase 5 | Multi-Agent | Orchestrator 调度 Requirement/Coding/Test/Review | ⬜ 计划 |
| Phase 6 | 平台化 | Memory、可观测性、评估、部署治理 | ⬜ 计划 |

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

- [ ] docker compose `--profile rag` 启 Qdrant；`qdrant-client` 入 requirements
- [ ] Embedding：OpenAI 兼容 embeddings 接口（可配本地备选）
- [ ] 入库流水线：`knowledge/seed/*.md` + 历史工单（tickets 表）切块 → 向量化 → upsert
- [ ] 检索工具 `search_document` / `search_ticket` 从占位改为真实检索（top-k + 分数）
- [ ] 可选进阶：Hybrid Search（BM25 + 向量）、Rerank
- [ ] 触发方式：工单启动时自动检索 + Agent 主动调用两种都支持

### 验收标准

1. BUG-1026（库存扣减）运行时，Agent 能检索到 BUG-387 的「Redis/MySQL 并发不一致」经验并在报告中引用。
2. 检索工具返回带来源与分数，报告中可追溯。

---

## Phase 4：Coding Agent（计划）

### 目标

Agent 在独立分支上真实修改代码：改 → 测 → 失败分析 → 再改 → 收敛，产出 Diff 供人工审批。

### 任务

- [ ] 运行前准备：`git worktree`/分支隔离（`agent/BUG-1024-runN`），失败可一键丢弃
- [ ] 开放 `write_file`（仅限工作区内、限定后缀、diff 尺寸上限）
- [ ] 修复循环：run_test 失败 → 读输出 → 改代码 → 再测，最多 N 轮，trace 记录每轮
- [ ] 修 BUG-1024 后把靶场 xfail 测试改为通过（去掉 xfail），新增回归测试
- [ ] 产出物结构化：修改文件列表、完整 diff、测试结果、置信度 → run 进入 `needs_review`
- [ ] HITL：批准 = merge 回主分支（或留 PR 说明）；拒绝 = 删除工作区
- [ ] 前端：Diff 视图（语法高亮）+ 批准/拒绝按钮启用

### 验收标准

1. BUG-1024 一键跑通：Agent 定位 → 改 `payment_consumer.py` → 测试由 1 xfailed 变 2 passed → 生成 Diff → 等待审批。
2. 审批前后靶场 main 分支零污染（改动只存在于 agent 分支）。
3. 多次失败后仍能收敛（体现自主性），或步数耗尽时给出失败分析而非静默。

---

## Phase 5：Multi-Agent（计划）

### 目标

单 Agent 上下文扛不住时拆角色：Orchestrator 调度 Requirement / Knowledge / Coding / Test / Review。

### 任务

- [ ] Orchestrator 从「直通 Task Agent」改为按计划调度子 Agent
- [ ] Requirement Agent：需求拆解 + 验收标准（REQ-1025 场景）
- [ ] Coding / Test / Review Agent 分工与消息传递（共享 run 上下文）
- [ ] REQ-1025 全流程：分析 → 设计 API → 改代码（订单状态机 + 库存恢复）→ 测试 → Review
- [ ] 角色间产物结构化传递（需求文档 → 编码指令 → 测试报告 → Review 意见）

### 验收标准

1. REQ-1025 跑通多 Agent 协作，各角色产物在 trace 中可见。
2. Review Agent 能对 Coding Agent 的 diff 提出具体意见（并驱动返工至少一轮）。

---

## Phase 6：平台化（计划）

### 目标

从 Demo 走向平台：经验沉淀（Memory）、可观测、可评估、部署治理。

### 任务（按优先级，可裁剪）

- [ ] Memory：run 结束后沉淀经验（项目结构认知、Bug→方案索引），跨 run 复用
- [ ] 可观测：run 级 token/耗时统计、成本看板
- [ ] Evaluation：固定工单集的回归评测（定位准确率、修复通过率）
- [ ] Retry/Checkpoint：LLM 超时重试、run 断点恢复
- [ ] Guardrail：危险操作黑名单、diff 尺寸限制、密钥扫描
- [ ] Deploy：HITL 批准后触发（本地 compose 模拟 CI/CD）
- [ ] Agent Hub：Agent 定义注册/版本化（6 个内置 + 自定义）

### 验收标准

1. 同类工单第二次运行明显少于第一次的探索步数（Memory 生效）。
2. 评测报告可对比两个版本 Agent 的成功率。
3. 全链路：工单 → 分析 → 检索 → 修复 → 测试 → Review → 审批 → 部署 → 回写工单状态。

---

## 维护约定

- 每完成一个任务勾选对应复选框；Phase 完成时更新状态总览与 README 首行。
- 新增依赖同步 `requirements.txt` / `package.json`，并在本文件「环境事实」记录影响。
- 每个 Phase 的验收标准全部满足才算完成；不满足就保持「开发中」并写明阻塞原因。
