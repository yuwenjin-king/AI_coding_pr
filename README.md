# AI 软件研发 Agent：从工单到上线

当前实现：**Phase 2** Tool Agent —— 工单工作台 + 只读分析，新增 `git_status/git_diff/git_log`、`run_test`（真实执行靶场 pytest）、通用 Agent Loop 与 SSE 实时观测。靶场仓库为 `playground/shopai`。开发计划与各阶段进度见 [PLAN.md](PLAN.md)。

## 本地运行

1. 复制环境变量并填入 OpenAI 兼容密钥：

```bash
cp .env.example .env
```

2. 启动 MySQL：

```bash
docker compose up -d mysql
```

3. 启动后端（在 `backend/`）：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

4. 启动前端：

```bash
cd frontend
npm install
npm run dev
```

打开 [http://localhost:5173](http://localhost:5173)，进入 `BUG-1024`，点击「让 AI 处理」。

健康检查：`GET http://127.0.0.1:8000/api/health`

运行后端测试（无需真实 LLM key，使用 FakeGateway）：

```bash
cd backend
source .venv/bin/activate
pytest
```

Phase 3 向量库（暂不需要）：`docker compose --profile rag up -d`

---

这个项目的核心不是聊天机器人，而是一条完整的软件工程闭环：

**用户提交真实软件工单 → Agent 理解需求 → 查询知识库 → 分析代码 → 制定方案 → 修改代码 → 自动测试 → Code Review → 部署 → 回写工单。**

它相当于一个小型 AI 软件工程团队。

---

## 1. 什么才叫真实业务 Agent

很多学习项目其实是假 Agent：用户问「介绍一下 Redis」，模型回答一段百科，然后结束。那更像 LLM Chatbot。

真正的业务 Agent 应按目标闭环执行：

```text
用户提出业务目标
        ↓
Agent 理解目标
        ↓
获取业务上下文
        ↓
调用工具
        ↓
执行多个步骤
        ↓
观察执行结果
        ↓
根据结果继续决策
        ↓
最终完成业务目标
```

**Agent 的价值不是回答问题，而是完成任务。** 本项目要做的是任务型 Agent。

---

## 2. 推荐学习项目：CodePilot Agent

**定位：** 能够自主处理软件研发工单的 AI Agent 平台。

示例工单：

```text
# BUG-1024
用户反馈：订单支付成功之后，偶尔订单状态还是 pending。
环境：生产环境
影响：大约 1% 的订单
```

传统流程：产品经理 → 研发 → 查代码 → 查日志 → 定位 → 改代码 → 测试 → Review → 部署。

Agent 流程：

```text
                    ┌──────────────┐
                    │   工单系统    │
                    └──────┬───────┘
                           ↓
                    ┌──────────────┐
                    │ Task Agent   │
                    └──────┬───────┘
                           ↓
              ┌────────────┴────────────┐
              ↓                         ↓
        Requirement Agent          Knowledge Agent
              ↓                         ↓
          理解需求                  查询历史经验
              ↓                         ↓
        Coding Agent  ←────────→  RAG
              ↓
          修改代码
              ↓
        ┌─────┴──────┐
        ↓            ↓
   Test Agent    Review Agent
        ↓            ↓
        └──────┬─────┘
               ↓
         Deploy Agent
               ↓
             CI/CD
               ↓
          更新工单
```

---


## 4. 真实业务工单

### 4.1 工单 1：BUG

**现象：** 订单支付成功，但订单状态没有变成 `PAID`。

Agent 需要完成：

1. 理解问题
2. 查询订单服务、支付服务代码
3. 查数据库结构、Kafka 消息
4. 查询历史类似 Bug
5. 分析支付回调流程并定位问题
6. 修改代码、编写并执行测试
7. Code Review
8. 创建 Git Branch、Commit、PR

### 4.2 工单 2：产品需求

**需求：** 订单列表增加「取消订单」功能。

约束：

- 用户只能取消待支付订单
- 支付完成后不能取消
- 取消后需要恢复库存

Agent 自行拆解：

```text
需求 → 分析系统 → Order / Inventory Service
     → 分析数据库 → 设计 API → 改代码 / 改库
     → 写测试 → 测试 → Review → 部署
```

这里会覆盖 Agent 核心概念：Planning、Tool Calling、RAG、Code Agent、Memory、Multi-Agent、Workflow、Human-in-the-loop。

---

## 5. 系统六层架构

原文写「6 层」，但只展开了前 3 层。按后文内容补全为：

| 层 | 名称 | 职责 |
| --- | --- | --- |
| Layer 1 | 任务层 | 工单列表与「让 AI 处理」入口 |
| Layer 2 | Orchestrator | 理解任务、制定计划、调度 Agent / 工具 |
| Layer 3 | Multi-Agent | 需求 / 知识 / 编码 / 测试 / Review / 部署分工 |
| Layer 4 | Tools | 操作代码、Git、测试、部署等现实世界 |
| Layer 5 | Knowledge | RAG + Memory（文档、历史工单、经验） |
| Layer 6 | 执行与治理 | Sandbox、HITL 审批、CI/CD |

### 5.1 Layer 1：任务层

用户看到的工单列表，例如：

- `BUG-1024` 支付成功订单状态异常
- `REQ-1025` 增加取消订单功能
- `BUG-1026` 库存扣减偶发失败

用户点击「让 AI 处理」，Agent 开始工作。

### 5.2 Layer 2：Agent Orchestrator

核心是 **Task Agent**：理解任务 → 制定计划 → 选择 Agent → 调用工具 → 观察结果 → 调整计划。

```json
{
  "task": "解决订单支付成功后状态未更新问题",
  "plan": [
    "分析订单状态机",
    "分析支付回调",
    "分析 Kafka 消息",
    "查询历史 Bug",
    "定位问题",
    "修改代码",
    "运行测试",
    "代码 Review"
  ]
}
```

### 5.3 Layer 3：Multi-Agent

第一版不要做几十个 Agent，先做这 6 个：

| Agent | 职责 |
| --- | --- |
| Requirement Agent | 需求分析、拆解、生成 Acceptance Criteria |
| Knowledge Agent | RAG：技术/架构文档、历史工单与 Bug、库表说明、编码规范 |
| Coding Agent | 读代码、定位、改代码、创建测试 |
| Test Agent | unit / integration / API test |
| Review Agent | 质量、安全、性能、架构、潜在 Bug |
| Deploy Agent | Docker、CI/CD、测试环境部署 |

只有任务复杂度超过单 Agent 处理能力时才拆角色，不要为 Multi-Agent 而拆。

### 5.4 Layer 4：Tools

不要只学 Function Calling，重点是 **Agent 如何通过 Tool 操作现实世界**。

```python
tools = [
    search_code,
    read_file,
    write_file,
    search_database_schema,
    search_document,
    search_ticket,
    search_git_history,
    run_test,
    run_lint,
    create_branch,
    git_commit,
    create_pull_request,
    deploy_service,
]
```

典型循环：了解订单状态 → `search_code()` → 找到 `OrderService` → `read_file()` → 发现状态更新逻辑 → `search_code(payment)` → 发现支付回调 → ……

### 5.5 Layer 5：RAG 与 Memory

#### RAG

知识库覆盖技术文档、历史工单、代码文档、API、Bug 记录、架构说明，经 Vector DB → Retrieval → Rerank 后交给 Agent。

示例：遇到「库存扣减失败」，检索到 `BUG-387`：

- **原因：** Redis 库存和 MySQL 库存并发不一致
- **方案：** Redis Lua + MQ 最终一致性

这比「把 PDF 塞进 RAG 再问答」更有业务意义。

#### Memory

| 类型 | 内容 |
| --- | --- |
| Short-term | 当前任务上下文 |
| Long-term | 项目架构、历史 Bug 与方案、用户偏好、Agent 经验 |

闭环：Bug → 分析 → 解决 → Review → 部署 → 结果 → 写入 Memory。Agent 因此能积累经验（例如已知 Order Service 使用 Kafka，下次不必重新探索）。

### 5.6 Layer 6：Human-in-the-loop 与执行治理

第一版禁止：Agent 改生产代码后直接上线。

正确路径：改代码 → 测试 → 生成 PR → **Human Review** → 批准 → Deploy。

审批 UI 示意：

```text
┌─────────────────────────────────────┐
│ BUG-1024                            │
│ 支付成功后订单状态未更新             │
│                                     │
│ AI Analysis                         │
│ Root Cause: Kafka Consumer 异常重试  │
│ Modified: order_service.py          │
│           payment_consumer.py       │
│ Tests: ✓ 128 passed                 │
│ AI Confidence: 92%                  │
│                                     │
│ [查看 Diff] [批准] [拒绝]            │
└─────────────────────────────────────┘
```

---

## 6. 完整平台形态

最终产品可拆成工单系统、项目系统、Agent 系统：

```text
                 AI Software Engineer
                         │
        ┌────────────────┼────────────────┐
        ↓                ↓                ↓
     工单系统          项目系统          Agent系统
        ↓                ↓                ↓
       Task           Git Repo        Orchestrator
                         │         RAG / Memory / Tools
                         └───────────────┘
                                  ↓
                             Agent Runtime
                     Coding / Test / Review
                                  ↓
                                 PR
                                  ↓
                           Human Review
                                  ↓
                                Deploy
```

---

## 7. 与 Agent 核心技术的对应

| Agent 能力 | 项目中的体现 |
| --- | --- |
| LLM | Agent 大脑 |
| Prompt | Agent 行为控制 |
| Tool Calling | Git / DB / Shell / API |
| Planning | 任务拆解 |
| ReAct | 思考 → 行动 → 观察 |
| RAG / Rerank | 企业知识库与检索质量 |
| Memory | 长期经验 |
| Multi-Agent | 多角色协作 |
| Workflow | 任务状态机 |
| Sandbox | 安全执行代码 |
| Human-in-loop | 人工审批 |
| MCP | 外部工具接入 |
| Evaluation | 效果评估 |
| Observability | 运行监控 |
| Retry / Checkpoint | 失败恢复、任务恢复 |
| Guardrail | 安全控制 |
| LLM Gateway | 多模型管理 |

做完这个项目，对 Agent 的理解会比几个 Chatbot Demo 深很多。

---

## 8. 分阶段实施（不要一上来做超级 Agent）

### Phase 1：单 Agent

工单 → Agent → 查询代码 → 分析问题 → **输出方案（先不改代码）**。

技术：FastAPI、React、MySQL、LLM、Git。

### Phase 2：Tool Agent

加入 `read_file`、`search_code`、`run_test`、`git_diff`。

循环：Agent → Tool → Observation → Agent → Tool → …… 真正理解 Agent Loop。

### Phase 3：RAG Agent

接入历史工单、技术/架构文档、代码规范。流程：用户工单 → RAG → Agent → Coding。

可学：Embedding、Vector DB、Hybrid Search、Rerank、Agentic RAG。

### Phase 4：Coding Agent

在 Docker Sandbox 中真正改代码：Clone → 改 → 测 → 失败则分析再改 → 再测。

自主性体现在多次失败后仍能收敛（例如 3 failed → Mock 错误 → 1 failed → 最终 128 passed）。

### Phase 5：Multi-Agent

Orchestrator 调度 Requirement、Coding、Test、Review。仅在单 Agent 扛不住时再拆。

### Phase 6：平台化

```text
                    AI Dev Platform
                           │
        ┌──────────────────┼──────────────────┐
        ↓                  ↓                  ↓
     Workbench          Agent Hub          Knowledge
        ↓                  ↓                  ↓
     Tasks             Agents             RAG
                           ↓
                     Agent Runtime
              Sandbox / Memory / Tools
                           ↓
                        Executor
                           ↓
                     Git / CI / CD
```

此时已不只是学习 Demo，而是可当作 **Agent 平台作品集 / 开源项目 / 面试项目 / 创业 MVP**。
