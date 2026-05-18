# NewsRoom 执行基线与 Sprint Issue Checklist 总计划

版本：v2.0-sprint-checklist  
日期：2026-05-18  
适用仓库：`F:\github\NewsRoom`  
文档类型：执行基线 / Sprint 计划 / Issue Checklist 总文档  
状态：后续开发严格执行  

---

## 0. 文档定位

本文档替代原先的执行基线总览版，升级为 **下一阶段开发唯一执行文档**。

它同时承担三层职责：

1. **执行基线**：定义当前代码相对 PRD 的主判断。
2. **Sprint 计划**：定义后续 6 个 Sprint 的目标、依赖和顺序。
3. **Issue Checklist**：把每个 Sprint 的 issue 进一步拆成可执行的 subtasks checklist。

从现在开始：

- `docs/00-TOTAL_PRD_MATURE_DESIGN_BOOK.md` 继续负责总控 PRD 与架构边界。
- `docs/01-09` 继续负责目标态架构设计。
- **本文档负责后续开发执行、issue 拆分、验收和推进顺序。**

---

## 1. 当前阶段结论

当前主线执行基线中的 5 个主包已经完成一轮落地并通过主回归：

- Package A — 06 Evidence & Quality
- Package B — 04 LLM Layer
- Package C — 07 Storage & Memory
- Package D — 08 Worker / Scheduler
- Package E — 09 Web Console

当前代码和 PRD 的主要差距已经从“主功能缺失”转为“目标态生产化差距”。

后续阶段重点不是再扩主链路，而是：

1. Workflow Runtime hardening
2. Worker lease/reclaim/long-running semantics
3. LLM route/deployment configuration-driven routing
4. Tool inspection and operator diagnostics
5. Quality reviewer workflow + report query surface
6. Web Console realtime + frontend verification

---

## 2. 开发总规则

### 2.1 必须遵守的执行原则

1. **一次只推进一个 Sprint 主目标**，不要同时跨 Sprint 大规模混做。
2. **基础 issue 优先**。每个 Sprint 的基础 issue 未完成前，其余 issue 不进入正式开发。
3. **先平台稳定，再扩产品面**。运行时、worker、存储、质量契约优先于 UI 扩展。
4. **每个 issue 都必须带测试与验收门**。
5. **所有状态边界继续严格分层**：
   - `TaskStatus != WorkflowRunStatus`
   - `OutputJudge != QualityGate`
   - `Inbound MCP != ToolRuntime MCP adapter`
   - `Storage canonical model != business model`

### 2.2 每个 Sprint 统一退出门

每个 Sprint 结束前必须满足：

- 代码落地
- checklist 全部打勾
- 对应测试集通过
- `.venv/Scripts/python -m scripts.dev compile` 通过
- 没有已知失败项被“留到以后再说”

---

## 3. Sprint 总图

### Sprint 1 — Workflow Runtime hardening
### Sprint 2 — Worker lease / reclaim / long-running semantics
### Sprint 3 — LLM route/deployment configuration-driven routing
### Sprint 4 — Tool inspection and operator diagnostics
### Sprint 5 — Quality reviewer workflow + report query surface
### Sprint 6 — Web Console realtime + frontend verification

---

## 4. Sprint 1 — Workflow Runtime hardening

### 目标
把运行时从“稳定可跑”推进到“长期可回放、可恢复、可兼容演进”。

### Issue S1-1 Manifest schema evolution compatibility
**背景**  
manifest 已经是 replay/inspection 的核心入口，但 schema/version 演进兼容性尚未被正式锁住。

**范围文件**
- `core/framework/workflow/manifest.py`
- `core/framework/workflow/inspection.py`
- `interfaces/services/run_inspection_service.py`
- `tests/core/framework/workflow/test_manifest.py`
- `tests/core/framework/workflow/test_manifest_contract.py`
- `tests/core/framework/workflow/test_manifest_hash.py`

**Subtasks checklist**
- [ ] 列出当前 manifest 的核心字段、可选字段、派生字段
- [ ] 标记 replay/inspection 的必需字段
- [ ] 标记 diagnostics/UI 辅助字段
- [ ] 梳理 manifest version / schema version / hash 使用面
- [ ] 明确旧 manifest 缺失哪些字段可兼容读取
- [ ] 明确哪些字段缺失必须报错
- [ ] 明确哪些字段参与 hash，哪些不参与
- [ ] 在 `core/framework/workflow/manifest.py` 中实现兼容读取逻辑
- [ ] 在 `core/framework/workflow/inspection.py` 中适配 legacy manifest
- [ ] 在 `interfaces/services/run_inspection_service.py` 中保持 service 层兼容一致
- [ ] 增加旧 manifest fixture compatibility case
- [ ] 增加缺少非关键字段但可读取的 case
- [ ] 增加缺少关键字段必须报错的 case
- [ ] 增加 hash 不因非 contract 字段漂移的 case
- [ ] 确保 replay/inspection/diagnostics 统一使用同一 manifest reader

**验收标准**
- [ ] 旧版 manifest 可被当前 inspection 路径读取
- [ ] 旧版 manifest 可被当前 replay 路径读取
- [ ] 缺失兼容字段时不无提示崩溃
- [ ] manifest hash 对非 contract 字段变化保持稳定
- [ ] 测试全部通过

---

### Issue S1-2 Checkpoint corruption detection and strict resume behavior
**背景**  
checkpoint 已能运行，但 corruption、checksum、strict/lenient resume 的行为还需要正式契约化。

**范围文件**
- `core/framework/workflow/checkpointing.py`
- `core/framework/workflow/executor.py`
- `tests/core/framework/workflow/test_checkpoint_corruption.py`
- `tests/core/framework/workflow/test_checkpoint_write_read.py`
- `tests/core/framework/workflow/test_checkpoint_resume_exact.py`

**Subtasks checklist**
- [ ] 列出 checkpoint corruption 场景（checksum mismatch、payload 篡改、缺字段、partial write）
- [ ] 区分真正 corruption 与可兼容元数据变化
- [ ] 定义 strict resume 必须失败的情况
- [ ] 定义 lenient 路径允许继续的情况
- [ ] 定义错误信息和诊断输出格式
- [ ] 在 `checkpointing.py` 中完善 corruption 检测
- [ ] 检查 `executor.py` 中 resume 错误传播行为
- [ ] 确保 migration 后 checkpoint 仍能生成有效 checksum
- [ ] 增加 payload 篡改失败 case
- [ ] 增加 envelope 缺字段 case
- [ ] 增加 checksum mismatch case
- [ ] 增加 legacy checkpoint migration case
- [ ] 增加 strict/lenient 行为差异 case
- [ ] 确保 corruption 不会 silent resume

**验收标准**
- [ ] strict resume 下损坏 checkpoint 明确失败
- [ ] checksum 行为稳定
- [ ] strict/lenient 有明确测试覆盖

---

### Issue S1-3 Replay/inspection compatibility for partial artifacts
**背景**  
真实长期运行中，artifact 不完整是高概率事件，系统必须保持“可诊断”。

**范围文件**
- `core/framework/workflow/inspection.py`
- `core/framework/workflow/checkpointing.py`
- `interfaces/services/run_inspection_service.py`
- `tests/core/framework/workflow/test_checkpoint_partial_artifact_recovery.py`
- `tests/core/framework/workflow/test_run_replay_bundle.py`
- `tests/core/framework/workflow/test_diagnostics_replay.py`
- `tests/core/framework/workflow/test_run_health_report.py`

**Subtasks checklist**
- [ ] 列出 replay 最小依赖 artifact 集
- [ ] 列出 report/events/step_results/llm/tool artifact 缺失场景
- [ ] 区分可降级查看与必须报错场景
- [ ] 明确 partial artifact 时 inspection 返回结构
- [ ] 明确 replay bundle 如何表达 integrity 状态
- [ ] 明确 run health 报告如何标记 missing artifacts
- [ ] 在 `inspection.py` 中统一 partial artifact 读取逻辑
- [ ] 在 `checkpointing.py` 中补充 artifact 恢复结构化结果
- [ ] 在 `run_inspection_service.py` 中透传 integrity / missing 信息
- [ ] 增加缺 report artifact 的 case
- [ ] 增加缺 events artifact 的 case
- [ ] 增加 artifact 内容损坏 case
- [ ] 增加 health report partial artifact case
- [ ] 增加 API/service partial artifact case
- [ ] 验证 partial run 不会被误判为完整 replay

**验收标准**
- [ ] partial artifact 行为稳定可诊断
- [ ] integrity 结果可信
- [ ] service 层与底层 contract 一致

---

### Issue S1-4 Resume/operation metadata continuity
**背景**  
resume/rerun/patch/cancel 等操作需要在 manifest、inspection、replay 中保留连续元数据，支撑 operator 审计。

**范围文件**
- `core/framework/workflow/operations.py`
- `core/framework/workflow/executor.py`
- `core/framework/workflow/inspection.py`
- `tests/core/framework/workflow/test_run_operations_resume_patch.py`
- `tests/core/framework/workflow/test_run_operations_rerun.py`
- `tests/core/framework/workflow/test_run_operations_audit.py`
- `tests/core/framework/workflow/test_checkpoint_resume_e2e.py`

**Subtasks checklist**
- [ ] 盘点当前 operation 类型：cancel / rerun / resume / patch / skip-step / mark-blocked-resolved
- [ ] 盘点它们现在写入的位置（manifest / events / replay / inspection）
- [ ] 标记字段命名不一致处
- [ ] 定义 operation metadata 的统一字段结构
- [ ] 定义每种 operation 至少必须记录的字段
- [ ] 在 `operations.py` 中统一 metadata 结构
- [ ] 在 `executor.py` 中保证 operation 信息稳定写入
- [ ] 在 `inspection.py` 中统一读取 operation trace
- [ ] 增加 resume-with-patch continuity case
- [ ] 增加 rerun-from-step continuity case
- [ ] 增加 skip-step / cancel / blocked-resolved case
- [ ] 增加 operation audit trail 可见性 case
- [ ] 验证 manifest / replay / inspection 字段一致

**验收标准**
- [ ] operation metadata 在 manifest / replay / inspection 中连续可追踪
- [ ] operator 能解释 run continuation 历史
- [ ] operation 测试通过

---

### Sprint 1 退出门
- [ ] `tests/core/framework/workflow/test_manifest.py`
- [ ] `tests/core/framework/workflow/test_manifest_contract.py`
- [ ] `tests/core/framework/workflow/test_manifest_hash.py`
- [ ] `tests/core/framework/workflow/test_checkpoint_corruption.py`
- [ ] `tests/core/framework/workflow/test_checkpoint_write_read.py`
- [ ] `tests/core/framework/workflow/test_checkpoint_resume_exact.py`
- [ ] `tests/core/framework/workflow/test_checkpoint_partial_artifact_recovery.py`
- [ ] `tests/core/framework/workflow/test_run_replay_bundle.py`
- [ ] `tests/core/framework/workflow/test_diagnostics_replay.py`
- [ ] `tests/core/framework/workflow/test_run_operations_resume_patch.py`
- [ ] `tests/core/framework/workflow/test_run_operations_rerun.py`
- [ ] `tests/core/framework/workflow/test_run_operations_audit.py`

---

## 5. Sprint 2 — Worker lease / reclaim / long-running semantics

### 目标
把 Worker 从“可用”推进到“更接近生产级长期运行”。

### Issue S2-1 Redis lease lifecycle hardening
**范围文件**
- `core/framework/workers/redis_queue.py`
- `interfaces/services/worker_service.py`
- `core/framework/workers/models.py`
- `tests/core/framework/workers/test_queue.py`
- `tests/interfaces/services/test_worker_app_service.py`

**Subtasks checklist**
- [ ] 梳理当前 leased/ack/fail 主状态流
- [ ] 明确 Redis lease 生命周期中的 required metadata
- [ ] 统一 enqueue 后 status/leased_by/lease_expires_at 初始化
- [ ] 统一 success/fail/ack 后的 task cleanup 语义
- [ ] 在 `redis_queue.py` 中补齐 lease lifecycle 状态收口
- [ ] 在 `worker_service.py` 中保证 run_once 读模型与状态流一致
- [ ] 增加 leased → success 主路径测试
- [ ] 增加 leased → fail → retry / DLQ 路径测试
- [ ] 增加 queue 读模型契约测试

**验收标准**
- [ ] lease / ack / fail 顺序 deterministic
- [ ] queue 读模型能准确反映主状态流
- [ ] 测试通过

---

### Issue S2-2 Stale reclaim semantics and ownership transfer
**范围文件**
- `core/framework/workers/redis_queue.py`
- `interfaces/services/worker_service.py`
- `core/framework/workers/heartbeat.py`
- `tests/core/framework/workers/test_queue.py`
- `tests/core/framework/workers/test_heartbeat.py`

**Subtasks checklist**
- [ ] 定义 stale pending 的判定标准
- [ ] 定义 reclaim 后 leased_by / updated_at / lease_expires_at 规则
- [ ] 区分 fresh pending 与 stale pending
- [ ] 补齐 reclaim 事件输出结构
- [ ] 在 `redis_queue.py` 中稳定 reclaim 语义
- [ ] 在 heartbeat / service 层透出 reclaimed 语义
- [ ] 增加 fresh pending 不被误 reclaim case
- [ ] 增加 stale pending reclaim case
- [ ] 增加 reclaimed 读模型 / API case

**验收标准**
- [ ] reclaim 只作用于 stale tasks
- [ ] ownership metadata 稳定
- [ ] reclaim 测试通过

---

### Issue S2-3 Dedup/idempotency semantics
**范围文件**
- `core/framework/workers/in_memory.py`
- `interfaces/services/worker_service.py`
- `core/framework/workers/models.py`
- `tests/core/framework/workers/test_queue.py`
- `tests/interfaces/services/test_worker_app_service.py`

**Subtasks checklist**
- [ ] 定义 unfinished dedup_key 的统一行为
- [ ] 区分 manual requeue / operator retry / replay 场景
- [ ] 明确哪些任务允许相同 key 重放，哪些禁止
- [ ] 在 in-memory / service 层保持 dedup 一致
- [ ] 给 daily task 统一 dedup_key 生成语义
- [ ] 增加 duplicate task rejection 测试
- [ ] 增加 requeue reason / retry reason 元数据测试

**验收标准**
- [ ] dedup 行为跨路径一致
- [ ] duplicate unfinished task 稳定拒绝
- [ ] 相关测试通过

---

### Issue S2-4 Retry/DLQ and TaskStatus vs RunStatus boundaries
**范围文件**
- `core/framework/workers/redis_queue.py`
- `core/framework/workers/worker_loop.py`
- `core/framework/workers/handlers.py`
- `tests/core/framework/workers/test_worker_loop.py`
- `tests/core/framework/workers/test_queue.py`

**Subtasks checklist**
- [ ] 定义 retry 只处理基础设施/可恢复失败
- [ ] 定义 quality blocked / waiting_for_human 等业务状态映射
- [ ] 明确 DLQ 记录必须包含的 error/event 字段
- [ ] 在 `worker_loop.py` 中稳定 success/fail/pause 分支
- [ ] 在 `handlers.py` 中维持 TaskStatus 与 RunStatus 分离
- [ ] 增加 QualityGateBlocked 不重试 case
- [ ] 增加 WAITING_FOR_APPROVAL / PAUSED contract case
- [ ] 增加 DLQ structured record case

**验收标准**
- [ ] TaskStatus 与 WorkflowRunStatus 不混淆
- [ ] retry/DLQ 行为稳定
- [ ] worker 测试通过

---

### Sprint 2 退出门
- [ ] `tests/core/framework/workers/test_queue.py`
- [ ] `tests/core/framework/workers/test_worker_loop.py`
- [ ] `tests/core/framework/workers/test_heartbeat.py`
- [ ] `tests/interfaces/services/test_worker_app_service.py`

---

## 6. Sprint 3 — LLM route/deployment configuration-driven routing

### 目标
把 LLM Layer 从“已有能力契约”推进到“配置驱动运行层”。

### Issue S3-1 Normalize config schema for deployments/routes/capabilities
**范围文件**
- `configs/models.yaml`
- `configs/models.example.yaml`
- `core/framework/llm/config.py`
- `core/framework/llm/models.py`
- `tests/core/framework/llm/test_model_config.py`

**Subtasks checklist**
- [ ] 梳理当前 config 支持的 deployment / route / capability 字段
- [ ] 统一 route/deployment/capabilities 配置结构
- [ ] 定义 required_capabilities 的配置表示
- [ ] 定义 fallback chain 的配置表示
- [ ] 定义 budget/cooldown 预留表达方式
- [ ] 在 `config.py` 中补齐解析和校验逻辑
- [ ] 更新 `models.yaml` / `models.example.yaml`
- [ ] 增加非法 capability / route config / fallback config 测试

**验收标准**
- [ ] config 能正确解析 deployment / route / capabilities
- [ ] 相关 config tests 通过

---

### Issue S3-2 Capability-gated route resolution
**范围文件**
- `core/framework/llm/router.py`
- `core/framework/llm/capabilities.py`
- `tests/core/framework/llm/test_router.py`
- `tests/core/framework/llm/test_capabilities.py`

**Subtasks checklist**
- [ ] route resolution 前显式检查 required capabilities
- [ ] incompatible deployment 进入 routing events
- [ ] fallback 不会落到 capability 不匹配 deployment
- [ ] 增加 capability-gated pass case
- [ ] 增加 incompatible deployment reject/skip case
- [ ] 增加 capability alias 正规化测试

**验收标准**
- [ ] incompatible deployment 不会被实际调用
- [ ] routing events 清楚表达 missing capabilities
- [ ] router tests 通过

---

### Issue S3-3 Config-driven retry/fallback/cooldown behavior
**范围文件**
- `core/framework/llm/router.py`
- `core/framework/llm/openai_compatible.py`
- `core/framework/llm/cost.py`
- `tests/core/framework/llm/test_router.py`
- `tests/core/framework/llm/test_cost.py`

**Subtasks checklist**
- [ ] 梳理现有 retryable / non-retryable provider error 分类
- [ ] 明确 fallback exhausted 行为
- [ ] 明确 cooldown 生效与失效条件
- [ ] 确保 route manifest 写出 fallback / cooldown 证据
- [ ] 增加 cooldown 行为测试
- [ ] 增加 exhausted fallback 测试
- [ ] 增加 retryable / non-retryable 差异测试

**验收标准**
- [ ] retry / fallback / cooldown 行为 deterministic
- [ ] manifest 和 metadata 里有足够证据
- [ ] 相关测试通过

---

### Issue S3-4 Route/deployment decisions into diagnostics and manifests
**范围文件**
- `core/framework/workflow/manifest.py`
- `interfaces/services/run_inspection_service.py`
- `interfaces/services/diagnose_service.py`
- `interfaces/api/routers/runs.py`

**Subtasks checklist**
- [ ] 定义 diagnostics 中 route / deployment / token / cost 的标准字段
- [ ] 让 manifest/inspection 返回统一的 LLM trace 摘要
- [ ] expose selected route / fallback / attempted deployments
- [ ] expose required_capabilities / capabilities
- [ ] expose budget/cooldown 相关信息
- [ ] 增加 API / diagnostics surface 测试

**验收标准**
- [ ] CLI/API/Web 能看到结构化 LLM diagnostics
- [ ] inspection 与 diagnose surface 保持一致
- [ ] 相关测试通过

---

### Sprint 3 退出门
- [ ] `tests/core/framework/llm/test_model_config.py`
- [ ] `tests/core/framework/llm/test_capabilities.py`
- [ ] `tests/core/framework/llm/test_router.py`
- [ ] `tests/core/framework/llm/test_cost.py`

---

## 7. Sprint 4 — Tool inspection and operator diagnostics

### 目标
把 ToolRuntime 和 operator diagnostics 做成统一、可消费、可审计的观测层。

### Issue S4-1 Consolidate ToolRuntime inspection read model
**范围文件**
- `core/framework/tools/inspection.py`
- `core/framework/tools/models.py`
- `tests/core/framework/tools/test_tool_inspection.py`

**Subtasks checklist**
- [ ] 盘点现有 inspection payload 字段
- [ ] 标记 operator-facing 必需字段
- [ ] 统一 success / failure / blocked / approval wait 的 inspection 表达
- [ ] 收口 serialization contract
- [ ] 增加 inspection 契约测试

**验收标准**
- [ ] inspection payload 稳定
- [ ] redaction 后保留 operator 所需信息
- [ ] 测试通过

---

### Issue S4-2 Operator-facing diagnostics from tool execution
**范围文件**
- `core/framework/tools/executor.py`
- `core/framework/tools/telemetry.py`
- `core/framework/tools/approval.py`
- `tests/core/framework/tools/test_tool_executor.py`
- `tests/core/framework/tools/test_tool_approval.py`

**Subtasks checklist**
- [ ] 区分 policy block / runtime error / approval wait
- [ ] 标记 spill / redaction / secret handling 结果
- [ ] 保留 correlation / execution metadata
- [ ] 补 operator-facing diagnostics 测试

**验收标准**
- [ ] operator 能区分不同失败/等待类型
- [ ] spill/redaction 可见
- [ ] 测试通过

---

### Issue S4-3 MCP adapter diagnostics parity
**范围文件**
- `core/framework/tools/mcp_adapter.py`
- `tests/core/framework/tools/test_mcp_adapter.py`
- `tests/core/framework/tools/test_w03_tool_runtime_contracts.py`

**Subtasks checklist**
- [ ] 盘点 MCP path 与 native path 的 diagnostics 差异
- [ ] 统一 MCP adapter 输出结构
- [ ] 保证 policy/approval/redaction 在 MCP path 上可见
- [ ] 增加 parity regression tests

**验收标准**
- [ ] MCP/native diagnostics shape 一致
- [ ] 测试通过

---

### Issue S4-4 Diagnostics surface through run inspection and diagnose APIs
**范围文件**
- `interfaces/services/run_inspection_service.py`
- `interfaces/services/diagnose_service.py`
- `interfaces/api/routers/runs.py`

**Subtasks checklist**
- [ ] 定义 API 层 tool diagnostics 输出字段
- [ ] run inspection 增加 tool diagnostics summary
- [ ] diagnose service 增加 operator 消费字段
- [ ] 增加 API surface 测试

**验收标准**
- [ ] API 能返回结构化 tool diagnostics
- [ ] CLI/Web 无需临时拼 JSON
- [ ] 测试通过

---

### Issue S4-5 End-to-end diagnostics contract tests
**范围文件**
- `tests/core/framework/tools/test_tool_inspection.py`
- `tests/core/framework/tools/test_tool_executor.py`
- `tests/interfaces/api/test_worker_status_api.py`
- `tests/interfaces/api/test_queue_status_api.py`

**Subtasks checklist**
- [ ] 增加 operator 视角 end-to-end contract tests
- [ ] 覆盖 tool failure / approval wait / redaction / spill
- [ ] 覆盖 queue/worker/operator 诊断读取
- [ ] 确保 contract drift 会被测试及时拦住

**验收标准**
- [ ] diagnostics contract 被测试锁住
- [ ] 相关测试通过

---

### Sprint 4 退出门
- [ ] `tests/core/framework/tools/test_tool_inspection.py`
- [ ] `tests/core/framework/tools/test_tool_executor.py`
- [ ] `tests/core/framework/tools/test_tool_approval.py`
- [ ] `tests/core/framework/tools/test_mcp_adapter.py`
- [ ] `tests/core/framework/tools/test_w03_tool_runtime_contracts.py`
- [ ] `tests/interfaces/api/test_worker_status_api.py`
- [ ] `tests/interfaces/api/test_queue_status_api.py`

---

## 8. Sprint 5 — Quality reviewer workflow + report query surface

### 目标
把 human review 真正变成完整 reviewer workflow，并统一 report detail 查询面。

### Issue S5-1 Reviewer decision payload normalization
**范围文件**
- `quality/editor_gate.py`
- `workflows/daily_intelligence/quality_result_builder.py`
- `tests/quality/*`

**Subtasks checklist**
- [ ] reviewer decision / remediation / status 字段统一
- [ ] blocked / rewrite / human review 三条路径共享字段语义
- [ ] reviewer remediation 结构明确
- [ ] 补质量层契约测试

**验收标准**
- [ ] reviewer payload 统一
- [ ] 质量测试通过

---

### Issue S5-2 Approval -> resume -> quality trace closure
**范围文件**
- `interfaces/services/approval_service.py`
- `interfaces/api/routers/approvals.py`
- `interfaces/services/report_service.py`
- `tests/interfaces/api/test_approval_api.py`
- `tests/interfaces/services/test_report_service.py`

**Subtasks checklist**
- [ ] approval decision 进入 quality trace
- [ ] resume workflow 后保留 reviewer 上下文
- [ ] request / decision / resume 关联稳定
- [ ] 补 API / service 测试

**验收标准**
- [ ] approval → resume → trace 闭环成立
- [ ] 测试通过

---

### Issue S5-3 Report detail unified query surface
**范围文件**
- `interfaces/services/report_service.py`
- `interfaces/services/run_inspection_service.py`
- `storage/repository.py`
- `tests/interfaces/services/test_report_service.py`
- `tests/interfaces/api/test_run_lineage_api.py`

**Subtasks checklist**
- [ ] 统一 report detail 的 quality/evidence/claim trace 字段
- [ ] 统一 report service / repository / inspection 返回结构
- [ ] 补 query surface 回归测试

**验收标准**
- [ ] report detail 可稳定返回统一 trace
- [ ] 测试通过

---

### Issue S5-4 Reviewer artifact inspection views
**范围文件**
- `interfaces/services/artifact_service.py`
- `interfaces/services/run_inspection_service.py`

**Subtasks checklist**
- [ ] 识别 reviewer 相关 artifact
- [ ] 让 artifact service 可稳定读取 reviewer artifact
- [ ] 确保 reviewer artifact 与 report/run detail 解释一致
- [ ] 增加 inspection view 回归测试

**验收标准**
- [ ] reviewer artifact inspection 稳定
- [ ] 与 query surface 一致

---

### Sprint 5 退出门
- [ ] `tests/quality/*`
- [ ] `tests/interfaces/api/test_approval_api.py`
- [ ] `tests/interfaces/services/test_report_service.py`
- [ ] `tests/interfaces/api/test_run_lineage_api.py`

---

## 9. Sprint 6 — Web Console realtime + frontend verification

### 目标
把 Web Console 从“静态查看页”推进到“更像 operator console”。

### Issue S6-1 Run progress / event stream consumption
**范围文件**
- `apps/web/src/app/runs/[runId]/page.tsx`
- `apps/web/src/components/runs/*`

**Subtasks checklist**
- [ ] 选择 SSE / polling 的最小实现路径
- [ ] 真正消费 `/progress` 或 `/events/stream`
- [ ] 展示 run progress / event stream
- [ ] 处理流中断 / 请求失败
- [ ] 保留非实时降级视图

**验收标准**
- [ ] run detail 可展示实时进度或事件
- [ ] 构建和类型检查通过

---

### Issue S6-2 Unified list UX for runs/reports/workers
**范围文件**
- `apps/web/src/app/runs/page.tsx`
- `apps/web/src/app/reports/page.tsx`
- `apps/web/src/app/workers/page.tsx`

**Subtasks checklist**
- [ ] 统一 limit/filter/pagination 模式
- [ ] 统一列表 header 与 controls
- [ ] 统一 API query param 组织方式
- [ ] 保持页面间 UX 一致

**验收标准**
- [ ] list UX 一致
- [ ] build/typecheck 通过

---

### Issue S6-3 Error / empty / request_id visibility standardization
**范围文件**
- `apps/web/src/components/common/ErrorState.tsx`
- `apps/web/src/components/common/EmptyState.tsx`
- 页面容器组件

**Subtasks checklist**
- [ ] 统一 request_id 展示规则
- [ ] 统一 empty state 与 error state 文案
- [ ] 检查关键页面是否都用统一组件
- [ ] 补充页面容器适配

**验收标准**
- [ ] 关键页面错误态都带 request_id
- [ ] 空状态/错误态一致

---

### Issue S6-4 Frontend verification harness expansion
**范围文件**
- `scripts/check_web_console.py`
- `docs/web-console.md`

**Subtasks checklist**
- [ ] 扩展 web-check required files 到真实页面矩阵
- [ ] 保持 docs/web-console.md 与页面矩阵一致
- [ ] 确保关键组件入口被 file check 覆盖
- [ ] 固化前端验证命令：typecheck / build / web-check

**验收标准**
- [ ] `python -m scripts.dev web-check` 覆盖真实页面矩阵
- [ ] `npm --prefix apps/web run typecheck` 通过
- [ ] `npm --prefix apps/web run build` 通过

---

### Sprint 6 退出门
- [ ] `npm --prefix apps/web run typecheck`
- [ ] `npm --prefix apps/web run build`
- [ ] `.venv/Scripts/python -m scripts.dev web-check`

---

## 10. 并行执行图

### Sprint 1
- 先：S1-1
- 并行：S1-2 + S1-3
- 最后：S1-4

### Sprint 2
- 先：S2-1
- 并行：S2-2 + S2-3 + S2-4

### Sprint 3
- 先：S3-1
- 并行：S3-2 + S3-3
- 最后：S3-4

### Sprint 4
- 先：S4-1
- 并行：S4-2 + S4-3
- 再：S4-4
- 最后：S4-5

### Sprint 5
- 先：S5-1
- 并行：S5-2 + S5-3
- 最后：S5-4

### Sprint 6
- 并行起手：S6-1 + S6-2
- 再：S6-3
- 最后：S6-4

---

## 11. 统一执行要求

- 后续开发必须严格按本文档推进
- 每个 issue 的 subtasks 完成后才能标记该 issue 完成
- 每个 Sprint 的退出门通过后，才允许进入下一个 Sprint
- 不允许跳过基础 issue 直接推进并行 issue
- 若 contract 变化，优先更新本文档，再改代码
