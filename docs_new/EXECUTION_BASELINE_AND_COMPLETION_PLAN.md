# NewsRoom 执行基线与完成度实施计划

版本：v1.0-execution-baseline  
日期：2026-05-18  
适用仓库：`F:\github\NewsRoom`  
文档类型：执行基线 / Completion Plan / Roadmap  
状态：后续开发严格执行基线  

---

## 0. 文档定位

本文档不是总 PRD，也不是目标态架构文档。  
它的职责是：**基于当前仓库真实实现，给出 01-09 模块完成度基线，并把后续开发路线固化为唯一执行方案。**

本文件用于回答四件事：

1. 当前各模块完成到什么程度。
2. 哪些部分已经完成，哪些只是部分完成。
3. 每个未完成/部分完成模块接下来要怎么做。
4. 后续开发按什么顺序推进，做到什么标准算完成。

因此，今后：

- `docs/00-TOTAL_PRD_MATURE_DESIGN_BOOK.md` 继续负责总控 PRD 与架构边界。
- `docs/01-09` 继续负责各模块目标态架构。
- **本文件负责实现进度、执行路线、完成度基线、实施包和 DoD。**

---

## 1. 当前仓库完成度总表

| 模块 | 名称 | 当前完成度 | 判断 |
|---|---|---:|---|
| 01 | Workflow Runtime | **88%** | 高完成度，核心成熟 |
| 02 | Agent Loop | **84%** | 高完成度，主执行内核已成型 |
| 03 | Tool Runtime | **86%** | 高完成度，治理能力较完整 |
| 04 | LLM Layer | **74%** | 部分完成，需做生产治理收口 |
| 05 | Source Pipeline | **85%** | 高完成度，业务主链路成熟 |
| 06 | Evidence & Quality Gate | **69%** | 部分完成，需优先补齐 |
| 07 | Storage & Memory | **72%** | 部分完成，需平台化收口 |
| 08 | Worker Scheduler | **68%** | 部分完成，需生产化增强 |
| 09 | Interfaces (CLI/API/MCP) | **83%** | 主体较完整，Web 部分未到最终态 |
| 09-UI | Web Console 子项 | **58%** | 中等完成度，已有页面骨架和核心读路径 |

---

## 2. 评分口径说明

完成度不是“文件数量占比”，也不是“PRD 页数占比”，而是综合以下四项判断：

1. **代码落地程度**：是否已有真实实现，而不是空目录/空接口。
2. **主链路可运行程度**：是否已接入 workflow / runner / API / UI 主流程。
3. **测试覆盖程度**：是否已有 unit / integration / workflow tests。
4. **目标态差距**：距 01-09 架构文档定义的最终态还有多少核心能力差距。

因此：

- 80%+ 代表该模块已成型，可作为稳定底座。
- 70%-79% 代表主能力已具备，但还有关键收口工作。
- 60%-69% 代表能用，但还不能视为生产级完成。
- 60% 以下才属于明显早期阶段。

---

## 3. 当前仓库证据基础

### 3.1 主要文档锚点

- `docs/00-TOTAL_PRD_MATURE_DESIGN_BOOK.md`
- `docs/NEWS_INTELLIGENCE_SYSTEM_MASTER_PRD_V1_3_RUNNER.md`
- `docs/01-WORKFLOW_RUNTIME_TARGET_ARCHITECTURE.md`
- `docs/02-AGENT_LOOP_TARGET_ARCHITECTURE.md`
- `docs/03-TOOL_RUNTIME_TARGET_ARCHITECTURE.md`
- `docs/04-LLM_LAYER_TARGET_ARCHITECTURE.md`
- `docs/05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md`
- `docs/06-EVIDENCE_AND_QUALITY_GATE_TARGET_ARCHITECTURE.md`
- `docs/07-STORAGE_AND_MEMORY_TARGET_ARCHITECTURE.md`
- `docs/08-WORKER_SCHEDULER_TARGET_ARCHITECTURE.md`
- `docs/09-INTERFACES_CLI_API_MCP_TARGET_ARCHITECTURE.md`
- `docs/web-console.md`

### 3.2 主要实现锚点

- Workflow Runtime: `core/framework/runner.py`, `core/framework/workflow/*`
- Agent Loop: `core/framework/agent_loop/*`
- Tool Runtime: `core/framework/tools/*`
- LLM Layer: `core/framework/llm/*`
- Source Pipeline: `sources/*`, `workflows/daily_intelligence/*`
- Evidence / Quality: `evidence/*`, `quality/*`
- Storage / Memory: `storage/*`
- Worker / Scheduler: `core/framework/workers/*`
- Interfaces: `interfaces/cli/*`, `interfaces/api/*`, `interfaces/mcp/*`, `interfaces/services/*`
- Web Console: `apps/web/src/*`

### 3.3 主要测试锚点

- Workflow: `tests/core/framework/workflow/*`
- Agent Loop: `tests/core/framework/agent_loop/*`
- Tool Runtime: `tests/core/framework/tools/*`
- LLM: `tests/core/framework/llm/*`
- Quality: `tests/quality/*`
- Sources: `tests/sources/*`
- Workers: `tests/core/framework/workers/*`
- Storage: `tests/storage/*`
- Interfaces/API: `tests/interfaces/api/*`
- Daily workflow: `tests/workflows/daily_intelligence/*`

---

## 4. 模块总判断

### 4.1 已高完成度模块

这些模块当前不再作为“重建设计”的重点，而是作为稳定底座：

- **01 Workflow Runtime**
- **02 Agent Loop**
- **03 Tool Runtime**
- **05 Source Pipeline**
- **09 Interfaces 主体（CLI/API/MCP）**

对这些模块，后续主要做 hardening、契约补强、回归测试和接口稳定性提升。

### 4.2 部分完成且必须继续补齐的模块

这些模块是当前执行路线的重点：

- **04 LLM Layer**
- **06 Evidence & Quality Gate**
- **07 Storage & Memory**
- **08 Worker Scheduler**
- **09 Web Console 子项**

这些模块都有真实实现，但还未达到目标态要求，必须通过专门实施包推进完成。

### 4.3 当前最优先模块

按业务价值与依赖关系排序：

1. **06 Evidence & Quality Gate**
2. **04 LLM Layer**
3. **07 Storage & Memory**
4. **08 Worker Scheduler**
5. **09 Web Console**

---

## 5. 总执行顺序

后续开发**必须严格按下面顺序推进**：

1. **Package A — 06 Evidence & Quality 收口**
2. **Package B — 04 LLM Layer 生产治理收口**
3. **Package C — 07 Storage & Memory canonical 化**
4. **Package D — 08 Worker/Scheduler 生产化**
5. **Package E — 09 Web Console 深化与闭环验证**
6. **01/02/03/05 Hardening** 穿插在相邻依赖包收尾阶段执行

### 5.1 为什么必须按这个顺序

- 06 决定报告是否可信，是整个产品最核心的质量门槛。
- 04 会影响 02/06 的输出稳定性、fallback、成本和诊断一致性。
- 07 是 08 和 09 的状态与数据底座。
- 08 依赖 07 的稳定存储语义，以及 01/06 的状态边界。
- 09 Web Console 必须建立在 07/08/06 提供的稳定读模型之上。

禁止反过来先大做 Web Console，再回头补底层治理。

---

## 6. 分模块实施计划

---

## 6.1 模块 01 — Workflow Runtime

**当前完成度：88%**  
**状态：高完成度，后续只做 hardening**

### 已完成判断

- `WorkflowRunner` 已存在：`core/framework/runner.py`
- `WorkflowExecutor`、`StepRunnerRegistry`、状态机、artifact 发布已成型
- checkpoint / resume / replay / inspection 有完整实现痕迹
- 测试覆盖较强：`tests/core/framework/workflow/*`

### 后续只做的工作

#### 01-H1 Manifest schema evolution
**目标**：确保 manifest 版本升级不破坏 run inspection / replay / artifact consumption。

**重点文件**
- `core/framework/workflow/manifest.py`
- `tests/core/framework/workflow/test_manifest_contract.py`
- `tests/core/framework/workflow/test_manifest_hash.py`

**实施步骤**
1. 统一 manifest version / schema hash 表达方式。
2. 增加旧 manifest -> 当前 reader 的兼容测试。
3. 验证 diagnostics / inspection 对旧 manifest 不崩溃。

#### 01-H2 Checkpoint replay invariant
**重点文件**
- `core/framework/workflow/checkpointing.py`
- `tests/core/framework/workflow/test_checkpoint_resume_exact.py`
- `tests/core/framework/workflow/test_checkpoint_corruption.py`
- `tests/core/framework/workflow/test_checkpoint_partial_artifact_recovery.py`

**实施步骤**
1. 验证 checkpoint 数据缺失、部分损坏、artifact 缺失时的行为。
2. 明确 resume 是否必须 artifact 完整。
3. 保证 corruption 不会 silently produce wrong replay。

### Definition of Done
- manifest 升级不会破坏 replay / inspection
- checkpoint corruption / partial recovery 均有契约测试

---

## 6.2 模块 02 — Agent Loop

**当前完成度：84%**  
**状态：高完成度，后续只做 hardening**

### 已完成判断

- 主 loop：`core/framework/agent_loop/loop.py`
- judge / parser / prompt / trace / diagnostics / stall detection 已存在
- subagent、budget 也已接入
- 测试存在：`tests/core/framework/agent_loop/*`

### 后续只做的工作

#### 02-H1 中途恢复与 schema-key judge 细化
**重点文件**
- `core/framework/agent_loop/loop.py`
- `core/framework/agent_loop/judge.py`
- `tests/core/framework/agent_loop/test_loop_runner.py`
- `tests/core/framework/agent_loop/test_output_judge_boundaries.py`

#### 02-H2 Parser / Prompt 边界异常统一
**重点文件**
- `core/framework/agent_loop/parser.py`
- `core/framework/agent_loop/prompt.py`
- `tests/core/framework/agent_loop/test_parser_prompt.py`

#### 02-H3 Subagent default-off 回归
**重点文件**
- `core/framework/agent_loop/subagents.py`
- `tests/core/framework/agent_loop/test_loop_runner.py`

### Definition of Done
- parser/judge/retry/stop reason 在异常场景下稳定输出
- output judge 与 quality gate 语义边界继续清晰

---

## 6.3 模块 03 — Tool Runtime

**当前完成度：86%**  
**状态：高完成度，后续只做 hardening**

### 已完成判断

- Tool executor：`core/framework/tools/executor.py`
- registry、policy、approval、secrets、redaction、telemetry 已具备
- MCP adapter 已存在
- 测试较充分：`tests/core/framework/tools/*`

### 后续只做的工作

#### 03-H1 inspection/read-model 输出补强
**重点文件**
- `core/framework/tools/inspection.py`
- `tests/core/framework/tools/test_tool_inspection.py`

#### 03-H2 MCP adapter 边界与 policy 事件覆盖
**重点文件**
- `core/framework/tools/mcp_adapter.py`
- `tests/core/framework/tools/test_mcp_adapter.py`

#### 03-H3 large result spill / redaction 回归
**重点文件**
- `core/framework/tools/executor.py`
- `tests/core/framework/tools/test_tool_executor.py`
- `tests/core/framework/tools/test_w03_tool_runtime_contracts.py`

### Definition of Done
- inspection 输出能被 API/MCP 稳定消费
- spill / redaction / approval / policy 均有明确契约测试

---

## 6.4 模块 04 — LLM Layer

**当前完成度：74%**  
**状态：部分完成，必须做生产治理收口**

### 已完成判断

- `core/framework/llm/openai_compatible.py`
- `core/framework/llm/router.py`
- `core/framework/llm/structured_output.py`
- `core/framework/llm/streaming.py`
- `core/framework/llm/cost.py`
- 测试：`tests/core/framework/llm/*`

### 主要缺口

1. provider/model capability matrix 还不够统一。
2. router retry/fallback/cooldown 收口不够彻底。
3. structured output / streaming / tool schema 一致性仍需加强。
4. LLM diagnostics 还没有完整暴露给 interface 层。

### 实施包 04-A：provider capability matrix 固化

**目标**：让 provider/model 能力成为统一 source of truth。 

**重点文件**
- `core/framework/llm/capabilities.py`
- `core/framework/llm/models.py`
- `core/framework/llm/config.py`
- `tests/core/framework/llm/test_capabilities.py`
- `tests/core/framework/llm/test_model_config.py`

**具体步骤**
1. 为 structured output / streaming / tool calling / cache eligibility 建立统一 capability matrix。
2. 把 router、structured output、tool adapter 内部分散判断收拢到 capability 层。
3. 为 capability drift 增加 fixture-based tests。

### 实施包 04-B：router retry / fallback / cooldown 收口

**重点文件**
- `core/framework/llm/router.py`
- `core/framework/llm/openai_compatible.py`
- `core/framework/llm/cost.py`
- `tests/core/framework/llm/test_router.py`
- `tests/core/framework/llm/test_cost.py`

**具体步骤**
1. 明确 primary route -> retry -> fallback -> cooldown 的行为顺序。
2. 禁止 silent fallback。
3. 将 run-level budget 与 provider retry 做统一约束。
4. 增补 fallback exhausted 和 cooldown 生效测试。

### 实施包 04-C：structured output / streaming 一致性

**重点文件**
- `core/framework/llm/structured_output.py`
- `core/framework/llm/streaming.py`
- `core/framework/llm/tool_adapters.py`
- `tests/core/framework/llm/test_structured_output.py`
- `tests/core/framework/llm/test_streaming.py`
- `tests/core/framework/llm/test_tool_adapters.py`

**具体步骤**
1. 统一 schema validation error 映射。
2. 保证 streaming final response 与 non-streaming response shape 一致。
3. 统一 provider-native tool schema -> ToolRuntime contract 的映射。

### 实施包 04-D：diagnostics 暴露到 interfaces

**重点文件**
- `interfaces/services/diagnose_service.py`
- `interfaces/api/routers/runs.py`
- `interfaces/services/run_inspection_service.py`

**具体步骤**
1. 暴露 route chosen / retries / fallback / token / cost / redaction marker。
2. 让 CLI / API / Web Console 都能读取 LLM diagnostics。

### Definition of Done
- fallback/retry/cooldown 行为可预测、可追溯
- structured output / streaming / tool schema 在 provider 间一致
- `tests/core/framework/llm/*` 全绿
- workflow 级 smoke 可验证 LLM artifact / manifest 记录

---

## 6.5 模块 05 — Source Pipeline

**当前完成度：85%**  
**状态：高完成度，后续只做 hardening**

### 已完成判断

- `sources/pipeline.py`
- `sources/registry.py`
- `sources/connectors/*`
- `sources/processing/*`
- daily intelligence 已接主链路

### 后续只做的工作

#### 05-H1 source health 持久化与治理报表
**重点文件**
- `sources/health/manager.py`
- `sources/processing/health_report.py`
- `workflows/daily_intelligence/source_health_flow.py`

#### 05-H2 source fallback / error taxonomy 回归
**重点文件**
- `sources/errors/taxonomy.py`
- `sources/processing/error_policy.py`
- `tests/sources/errors/test_taxonomy.py`

#### 05-H3 connector coverage 增补
**重点文件**
- `tests/sources/connectors/*`
- `tests/sources/processing/test_processing.py`

### Definition of Done
- health/governance/fallback 路径与 runner artifacts 稳定对齐

---

## 6.6 模块 06 — Evidence and Quality Gate

**当前完成度：69%**  
**状态：部分完成，当前最高优先级模块**

### 已完成判断

- `evidence/models.py`
- `evidence/builder.py`
- `evidence/claim_verifier.py`
- `quality/citation_checker.py`
- `quality/editor_gate.py`
- `quality/scoring.py`
- `quality/support_matrix.py`
- `workflows/daily_intelligence/quality_evaluation.py`
- `workflows/daily_intelligence/quality_gate_step.py`
- `workflows/daily_intelligence/quality_result_builder.py`

### 主要缺口

1. citation failure 分类还不够 machine-parseable。
2. verified claim / support matrix / quality summary 之间还未彻底闭环。
3. rewrite / block / human review 的状态与输出还需统一。
4. quality artifacts 与 lineage 的可追溯性仍需加强。

### 实施包 06-A：citation coverage 分类与 section-level contract 收口

**重点文件**
- `quality/citation_checker.py`
- `quality/models.py`
- `workflows/daily_intelligence/quality_result_builder.py`
- `tests/quality/test_citation_editor.py`

**具体步骤**
1. 统一 citation failure categories。
2. 区分 unknown URL / unsupported URL / missing section sources / unsupported evidence IDs / rejected claim usage。
3. 让 quality result 和 blocked report metadata 输出同一分类结构。

### 实施包 06-B：support matrix 与 verified claim 闭环

**重点文件**
- `quality/support_matrix.py`
- `quality/scoring.py`
- `evidence/claim_verifier.py`
- `evidence/models.py`
- `tests/quality/test_support_scoring.py`

**具体步骤**
1. 统一 claim severity / support level / confidence score 语义。
2. 明确 accepted / rejected / uncertain claim 到 quality summary 的映射。
3. 为 high-severity unsupported claims 增加聚合字段。

### 实施包 06-C：editor gate / rewrite / block / human review 收口

**重点文件**
- `quality/editor_gate.py`
- `workflows/daily_intelligence/quality_gate_step.py`
- `workflows/daily_intelligence/quality_rewrite.py`
- `workflows/daily_intelligence/quality_evaluation.py`
- `tests/workflows/daily_intelligence/test_daily_agentic_rewrite_path.py`
- `tests/quality/test_citation_editor.py`

**具体步骤**
1. 固化 `PASS / REWRITE_REQUIRED / BLOCKED / HUMAN_REVIEW` 的决策门槛。
2. human review request 输出 remediation hints。
3. rewrite 后必须完整重跑 citation/support/quality summary。
4. final report / blocked report / human review request 的字段结构统一。

### 实施包 06-D：quality artifacts 与 lineage 可追溯性

**重点文件**
- `workflows/daily_intelligence/quality_result_builder.py`
- `storage/lineage/evidence.py`
- `interfaces/services/report_service.py`
- `tests/interfaces/api/test_run_lineage_api.py`

**具体步骤**
1. quality artifact 输出 evidence/claim/report 对照关系。
2. run inspection / report detail 能显示 quality gating 原因。

### Definition of Done
- 所有 quality 路径都可追溯到 evidence / claim
- pass/rewrite/block/human review 都有确定性测试
- blocked report 的原因、质量分、remediation 对用户可解释

---

## 6.7 模块 07 — Storage and Memory

**当前完成度：72%**  
**状态：部分完成，需平台化收口**

### 已完成判断

- `storage/repository.py`
- `storage/records.py`
- `storage/postgres/*`
- `storage/local_json/*`
- `storage/events/*`
- `storage/lineage/*`
- `storage/checkpoint/*`
- `storage/vector/*`
- `storage/memory/ingestion.py`
- `storage/hybrid_search.py`

### 主要缺口

1. canonical store contract 仍需统一。
2. migrations / retention / backup / recovery 还需系统化。
3. retrieval 层在 event/lineage/report 上仍需统一 contract。
4. memory ingestion / hybrid search / vector path 需要稳定闭环。

### 实施包 07-A：canonical store contract 收口

**重点文件**
- `storage/repository.py`
- `storage/records.py`
- `storage/postgres/repository.py`
- `storage/local_json/repository.py`
- `tests/storage/test_repository_factory.py`
- `tests/storage/test_persistence_records.py`

**具体步骤**
1. 明确 run/report/evidence/event/conversation/lineage 的持久化边界。
2. 清理重复 record shape 和隐式 adapter 转换。
3. 统一 local json 和 postgres factory 合同。

### 实施包 07-B：migrations / retention / backup / recovery

**重点文件**
- `storage/postgres/migrations.py`
- `storage/lifecycle/retention.py`
- `storage/lifecycle/backup.py`
- `tests/storage/postgres/test_migrations.py`
- `tests/storage/test_retention_policy.py`
- `tests/storage/test_check_scripts.py`

**具体步骤**
1. 为 schema evolution 定义稳定 migration path。
2. retention 覆盖 artifacts / events / reports / conversations。
3. backup/restore 至少覆盖 local + postgres 核心路径。

### 实施包 07-C：event / lineage / report retrieval 强化

**重点文件**
- `storage/events/*`
- `storage/lineage/*`
- `interfaces/services/run_inspection_service.py`
- `interfaces/services/report_service.py`
- `tests/storage/test_event_store.py`
- `tests/storage/test_lineage_store.py`

**具体步骤**
1. run inspection / report detail / lineage 查询依赖同一存储 contract。
2. 修复 retrieval 层潜在字段不一致问题。

### 实施包 07-D：memory ingestion + hybrid/vector retrieval 收口

**重点文件**
- `storage/memory/ingestion.py`
- `storage/vector/models.py`
- `storage/vector/qdrant_store.py`
- `storage/hybrid_search.py`
- `interfaces/services/memory_service.py`
- `tests/storage/memory/*`
- `tests/storage/vector/*`
- `tests/storage/test_hybrid_search.py`

**具体步骤**
1. 让 memory document 与 run/report lineage 双向关联。
2. 让 hybrid retrieval 输出 deterministic shape。
3. 确保 secrets/redacted 内容不会进入 memory index。

### Definition of Done
- local json / postgres / vector 均遵守同一逻辑边界
- migration / retention / backup / recovery 可测试、可执行
- memory search 对 run/report/evidence 查询闭环可用

---

## 6.8 模块 08 — Worker Scheduler

**当前完成度：68%**  
**状态：部分完成，需生产化增强**

### 已完成判断

- `core/framework/workers/models.py`
- `core/framework/workers/redis_queue.py`
- `core/framework/workers/worker_loop.py`
- `core/framework/workers/scheduler.py`
- `core/framework/workers/handlers.py`
- `core/framework/workers/heartbeat.py`
- `interfaces/services/worker_service.py`
- `interfaces/services/schedule_service.py`

### 主要缺口

1. lease / reclaim / idempotency 语义还需稳定。
2. DLQ / retry / misfire / catch-up 需要系统化。
3. approval pause / resume 端到端一致性仍需增强。
4. worker observability / queue read model 仍需固定。

### 实施包 08-A：lease / reclaim / idempotency 稳定化

**重点文件**
- `core/framework/workers/redis_queue.py`
- `core/framework/workers/worker_loop.py`
- `core/framework/workers/models.py`
- `tests/core/framework/workers/test_queue.py`
- `tests/core/framework/workers/test_worker_loop.py`

**具体步骤**
1. 固化 leased -> running -> succeeded/failed/retrying 的状态变换。
2. worker crash 时 reclaim 语义稳定化。
3. 固化 daily workflow task 的 dedup key。

### 实施包 08-B：DLQ / retry / misfire / catch-up

**重点文件**
- `core/framework/workers/scheduler.py`
- `core/framework/workers/handlers.py`
- `core/framework/workers/in_memory.py`
- `core/framework/workers/schedule_store.py`
- `tests/core/framework/workers/test_scheduler.py`
- `tests/core/framework/workers/test_schedule_store.py`

**具体步骤**
1. Task retry 仅处理基础设施失败。
2. misfire policy 与 catch-up policy 建立清晰测试矩阵。
3. 明确 dead-letter queue 的进入条件与人工介入点。

### 实施包 08-C：approval pause/resume 端到端收口

**重点文件**
- `core/framework/workers/approval.py`
- `core/framework/workers/worker_loop.py`
- `interfaces/services/approval_service.py`
- `interfaces/services/run_service.py`
- `interfaces/api/routers/approvals.py`
- `tests/core/framework/workers/test_approval.py`
- `tests/interfaces/api/test_approval_api.py`

**具体步骤**
1. 统一 approval decision -> resume context -> workflow resume 的状态映射。
2. 保证 approval record、checkpoint、task status 三者一致。

### 实施包 08-D：worker observability / queue read model 固化

**重点文件**
- `interfaces/services/worker_service.py`
- `interfaces/api/routers/workers.py`
- `interfaces/api/routers/schedules.py`
- `tests/interfaces/api/test_worker_status_api.py`
- `tests/interfaces/api/test_queue_status_api.py`

**具体步骤**
1. 标准化 stale worker / dead letter / backlog 指标。
2. 固化给 CLI / API / Web Console 的 read model shape。

### Definition of Done
- TaskStatus 与 WorkflowRunStatus 始终分离
- crash/retry/resume/approval 路径均有契约测试
- queue 深度、worker 状态、approval wait/release 可稳定展示

---

## 6.9 模块 09 — Interfaces / CLI / API / MCP / Web Console

**当前完成度：83%**  
**Web Console 子项：58%**

### 已完成判断

#### 非 Web 部分
- `interfaces/api/app.py`
- `interfaces/api/routers/*`
- `interfaces/services/*`
- `interfaces/cli/news.py`
- `interfaces/mcp/server.py`
- `interfaces/mcp/stdio_server.py`

#### Web 部分
已存在页面与组件：
- dashboard: `apps/web/src/app/page.tsx`
- runs list/detail: `apps/web/src/app/runs/page.tsx`, `apps/web/src/app/runs/[runId]/page.tsx`
- reports list/detail: `apps/web/src/app/reports/*`
- workers: `apps/web/src/app/workers/page.tsx`
- approvals: `apps/web/src/app/approvals/page.tsx`
- memory: `apps/web/src/app/memory/page.tsx`
- source health: `apps/web/src/app/sources/page.tsx`

### 非 Web 部分的后续 hardening

#### 09-H1 API response parity / audit / auth / rate-limit 边界补测
**重点文件**
- `interfaces/api/app.py`
- `interfaces/api/routers/*.py`
- `tests/interfaces/api/test_api_contracts.py`
- `tests/interfaces/api/test_api_router_parity.py`
- `tests/interfaces/api/test_openapi_contract.py`

#### 09-H2 CLI / API / MCP contract 对齐
**重点文件**
- `interfaces/services/*.py`
- `interfaces/mcp/*`
- `tests/interfaces/api/test_api_mcp.py`
- `tests/interfaces/api/test_api_mcp_sdk_surface.py`

### Web Console 实施包 09-WEB-A：page parity 与 view contract 固化

**重点文件**
- `apps/web/src/lib/types.ts`
- `apps/web/src/lib/api-client.ts`
- 对应页面与组件

**具体步骤**
1. 固定 runs / reports / workers / approvals / memory / sources 的 API view model。
2. 避免页面各自临时拼装字段。

### Web Console 实施包 09-WEB-B：run inspection / operations / approval flow 深化

**重点文件**
- `apps/web/src/components/runs/RunOperationPanel.tsx`
- `apps/web/src/components/runs/RunTimeline.tsx`
- `apps/web/src/components/runs/RunArtifacts.tsx`
- `apps/web/src/components/approvals/ApprovalTable.tsx`
- `interfaces/api/routers/runs.py`
- `interfaces/api/routers/approvals.py`

**具体步骤**
1. run detail 页面补齐 diagnostics / artifact / replay / operation 状态。
2. approvals 页面补 resume context / workflow resume 入口。
3. 对 run operation 增加错误态与 request_id 可见性。

### Web Console 实施包 09-WEB-C：diagnostics / filters / pagination / polling

**重点文件**
- `apps/web/src/app/runs/page.tsx`
- `apps/web/src/app/reports/page.tsx`
- `apps/web/src/app/workers/page.tsx`
- `apps/web/src/components/common/ErrorState.tsx`
- `apps/web/src/components/common/EmptyState.tsx`

**具体步骤**
1. 为列表页建立统一分页/过滤模式。
2. 对长运行任务增加 polling 或 SSE 消费。
3. 标准化展示 API error code / request_id / retry hint。

### Web Console 实施包 09-WEB-D：frontend verification harness

**重点任务**
1. 建立关键页面 smoke/test strategy。
2. 固化前端验证：
   - `npm run typecheck`
   - `npm run lint`
   - `npm run build`
3. 与 `docs/web-console.md` 保持同步。

### Definition of Done
- Web Console 只走 API，不绕过服务层
- 关键操作链 `run -> inspect -> approve/reject -> resume` 可完整走通
- 列表、详情、错误态、空状态、过滤/分页逻辑统一

---

## 7. 开发阶段硬约束

后续开发必须遵守以下规则：

### 7.1 不允许跳过执行顺序
不得直接开始 08 或 09 的深度开发，而不先完成 06 / 04 / 07 的关键收口。

### 7.2 不允许把执行进度写回总 PRD
`docs/00-TOTAL_PRD_MATURE_DESIGN_BOOK.md` 和 `docs/01-09` 继续是架构基准，不直接承载当前实现进度。

### 7.3 不允许脱离现有实现重写
本仓库已经有强 runtime 基础，后续应优先复用：
- `core/framework/workflow/*`
- `core/framework/agent_loop/*`
- `core/framework/tools/*`
- `core/framework/llm/*`
- `sources/*`
- `quality/*`
- `storage/*`
- `interfaces/*`
- `apps/web/src/*`

### 7.4 每个实施包都必须先补测试再扩行为
行为扩展不能先于 contract test / regression test。

### 7.5 所有状态边界必须分层清晰
必须持续维持：
- `TaskStatus` != `WorkflowRunStatus`
- `OutputJudge` != `Quality Gate`
- `MCP inbound interface` != `ToolRuntime MCP adapter`
- `Storage canonical model` != `business domain model`

---

## 8. 统一验收标准（DoD 总表）

一个模块或实施包只有满足以下全部条件才可标记完成：

1. 代码已落地到本文件指定目录。
2. 对应测试已新增或更新。
3. 不破坏相邻模块 contract。
4. API / CLI / Web 如有对外行为变化，必须同步更新 interface view model。
5. 必要时补 smoke 验证。
6. 能通过当前主链路场景验证，不只是 isolated unit test 通过。

---

## 9. 验证方案

### 9.1 Python 测试

```bash
pytest tests/quality
pytest tests/core/framework/llm
pytest tests/storage
pytest tests/core/framework/workers
pytest tests/interfaces/api
pytest tests/workflows/daily_intelligence
```

### 9.2 Workflow / Runtime 验证

必须验证：

- daily intelligence offline / agentic 相关 smoke
- final report / blocked report / quality artifacts / lineage outputs
- approval -> resume -> run status transitions

### 9.3 Web Console 验证

在 `apps/web` 下执行：

```bash
npm run typecheck
npm run lint
npm run build
```

并做关键页面手工验证：

- Dashboard
- Runs
- Run Detail
- Reports
- Workers
- Approvals
- Memory
- Sources

---

## 10. 本文档的维护规则

今后所有以下内容统一只维护在本文件：

- 完成度百分比变化
- 模块完成状态变化
- 实施包拆分调整
- 执行顺序调整
- DoD / 验收基线调整

其他文档如需引用，只放链接，不复制 roadmap 内容。

---

## 11. 下一步开始点

后续开发启动时，必须从以下顺序开始：

1. **先做 06-A / 06-B / 06-C / 06-D**
2. 再推进 **04-A / 04-B / 04-C / 04-D**
3. 再推进 **07-A / 07-B / 07-C / 07-D**
4. 再推进 **08-A / 08-B / 08-C / 08-D**
5. 最后推进 **09-WEB-A / 09-WEB-B / 09-WEB-C / 09-WEB-D**

这是当前仓库后续开发的**正式执行基线**。
