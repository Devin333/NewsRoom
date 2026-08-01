# Harness Dynamic Task Planning PRD

## 1. 文档信息

| 字段 | 内容 |
|---|---|
| 产品/能力 | Harness Dynamic Task Planning |
| OpenSpec Change | `harness-dynamic-task-planning` |
| 前置变更 | `harness-workflow-graph-runtime` |
| 文档状态 | Proposed |
| 日期 | 2026-08-01 |
| 目标版本 | Harness Dynamic Task Planning v1 |
| 影响范围 | `framework/harness`、SubAgent Runtime、worker binding、durable events、checkpoint/replay、Research Harness |

## 2. 摘要

本变更将 Harness 当前只用于校验输入的 `PLAN` 阶段，扩展为受 Harness 控制的动态任务规划阶段。

动态规划不是让 LLM 改写已经冻结的 Workflow Graph，也不是让 subagent 自己决定下一步路由。系统采用两层模型：

1. `Harness Control Graph`：在 `RUN_CREATED` 前编译、验证、冻结并记录 checksum 的固定外层流程。
2. `TaskPlan DAG`：在固定业务 stage 内由 LLM 提出候选任务，经 Harness 确定性校验、版本化接受和持久化后，作为该 stage 的运行时任务图。

LLM 只负责提出任务分解候选。Harness 负责决定候选是否可接受、任务绑定哪个已注册 worker、哪些任务已经 ready、何时 dispatch、何时通过 VERIFY、何时 retry/replan/halt。所有计划版本、任务状态、调度决定和非确定性结果都必须进入 durable event/transcript，以便恢复、审计和 replay。

首个业务试点是 Research 的 `analysis` stage。现有 source collection、document compilation、RAG、evidence、claim verification、quality gate、report 和 artifact publication 保持确定性和固定边界不变。

## 3. 背景与问题

### 3.1 当前 Harness 的能力

前置变更 `harness-workflow-graph-runtime` 已提供：

- `HarnessWorkflowSpec`、`HarnessStepSpec`、Graph DSL 和规范化 Graph IR。
- `Sequence`、`Choice`、`Parallel-All`、`Parallel-Any`、`Bounded-Loop`、`Wait`、`Compensation`。
- 固定的 `PLAN -> EXECUTE -> VERIFY` Step 生命周期。
- deterministic gates、retry、replan、repair、approval wait、budget、halt。
- Worker、Gate、Side Effect Registry、durable transition、activity result、checkpoint 和 replay。
- 在 `RUN_CREATED` 前冻结 `NormalizedHarnessGraph`，运行中禁止原地修改 Graph。

### 3.2 当前 PLAN 的真实语义

当前 `HarnessControlPlane` 在进入 `PLAN` phase 后主要执行：

- `ToolAllowlistGate`；
- `DeduplicationGate`；
- `BudgetGate`；
- `SkillEvolutionBudgetGate`；
- 其他当前 step 的计划前置校验。

当前 PLAN 不会让 LLM 生成任务列表，不会建立 Task DAG，也不会将一个业务目标拆成多个可独立调度的 subagent task。因此它更准确地说是 `VALIDATE_PLAN`，而不是动态任务规划器。

### 3.3 现有 Research 流程的限制

当前 `business/research/workflows/paper_analysis_workflow.py` 将分析阶段固定为：

```text
build_evidence_pack
        |
        v
ParallelAll
    |-- analyze_structure
    |-- analyze_contribution
    `-- analyze_experiments
        |
        v
verify_claims
```

固定分支保证了输出契约和质量门，但不能根据论文类型、证据缺口或失败原因动态增加任务、拆分任务、复用已经完成的结果或生成受控修复任务。

### 3.4 不能采用的做法

以下做法会破坏前置变更的架构边界，明确禁止：

- 让 LLM 在运行中修改 `NormalizedHarnessGraph`。
- 让 LLM 返回 `next_step`、`route`、`quality_passed`、`publish_artifact`、`write_memory` 等控制字段。
- 让 subagent 直接向队列写入任意任务或直接改变 Harness 状态。
- 把 `framework/workers/models/task.py` 的通用队列任务模型直接当成 DAG 契约。
- 让确定性的 source、evidence、quality gate、publication 工作进入 LLM 规划。
- 用一个隐含在业务 Worker 内部的循环替代可持久化、可 replay 的任务调度器。

## 4. 产品目标

### G1. 支持固定 Graph 内的动态 TaskPlan

允许一个已经声明为 dynamic 的固定业务 stage 在运行时生成、验证、接受和执行 TaskPlan DAG，同时保证外层 Graph checksum 不变。

### G2. 保持 Harness 的控制权

LLM 只能生成候选内容。路由、worker binding、工具授权、质量判定、预算消耗、memory 写入、publication 和 halt 必须由 Harness、注册表和 deterministic gate 控制。

### G3. 支持受控并行和依赖调度

支持多个 ready task 并行执行、显式依赖、稳定调度顺序、有限并发、输出隔离、确定性聚合和 durable join。

### G4. 支持版本化 replan

任务失败、VERIFY 失败或证据缺口出现时，可以生成带 `base_plan_version` 的 `PlanPatch`。新版本只能影响尚未完成的任务，不得篡改历史输出。

### G5. 支持恢复和 replay

进程崩溃或 worker 重启后，系统可以从 checkpoint 和 event stream 恢复 plan/task 状态，不能重复调用已经 durable commit 的非确定性 activity。

### G6. Research 兼容

Research 动态分析试点必须继续满足现有 `verify_claims`、`ResearchQualityGate`、reader payload、paper card 和 artifact publication 的输出契约。现有静态 workflow 保持可用。

## 5. 非目标

本变更不包含：

- 运行时 Graph DSL 编辑器、BPMN/Petri Net 编辑器或通用低代码流程平台。
- 跨整个 Run 由 LLM 一次性生成总 DAG。
- LLM 直接选择任意 Python callable、任意 handler 或任意 worker version。
- 任意 stage 的动态插入、跨 stage 依赖或动态修改 publication/quality gate 路径。
- 新建分布式队列、消息系统或独立事件数据库。
- 用新 TaskPlan Runtime 替换现有 Worker、Gate、Memory、RAG 或 Side Effect Port。
- 为了动态化而删除现有静态 Research workflow。
- 在 v1 中支持动态 TaskPlan 内的无限循环、任意递归或 nested dynamic plan。
- 对外部系统提供 exactly-once 副作用保证。副作用仍遵循既有 idempotency、fencing 和 outcome 规则。

## 6. 用户与使用场景

### 6.1 Framework Maintainer

维护者可以新增一个 dynamic stage policy，声明允许的 worker capability、输入引用、输出角色、确定性 gates 和预算上限，不需要在 `HarnessScheduler` 中写业务分支。

### 6.2 Business Workflow Author

业务作者可以为一个固定 stage 声明：

- stage 的输入和输出 contract；
- 允许的任务能力；
- 必须产出的 output role；
- 任务数量、深度、并发和 retry 上限；
- 任务结果如何由确定性 aggregator 汇聚。

业务作者不能授权 LLM 修改外层 Graph，也不能让 LLM 直接发布 artifact。

### 6.3 Operator / Reviewer

操作人员可以查看：

- 当前 Graph checksum、plan id、plan version 和 plan checksum；
- 候选计划为何被接受或拒绝；
- ready/running/waiting/succeeded/failed task 数量；
- 每个 task 的 dependency、attempt、worker binding、预算和结果引用；
- replan 的触发原因、patch 操作和新旧版本差异；
- replay 是否复现了原始决定 checksum。

### 6.4 代表性场景：Research 动态分析

对于一篇结构复杂的论文，LLM 可以提出：

```text
extract_method_claims
extract_experiment_claims
analyze_method_novelty (depends_on extract_method_claims)
analyze_baseline_quality (depends_on extract_experiment_claims)
```

Harness 会校验依赖、将 capability 绑定到已注册的 Research subagent、并发执行无依赖任务、等待依赖任务完成，再把结果映射到 `analysis_branch_refs`。只有 deterministic `verify_claims` 和 `ResearchQualityGate` 通过后，流程才会进入报告和发布阶段。

## 7. 总体架构

### 7.1 两层图模型

```text
Frozen Harness Control Graph
    |
    | fixed executable node: dynamic_analysis_stage
    v
TaskPlanStageRunner
    |-- PlanCandidateBuilder      -> LLM worker, candidate only
    |-- TaskPlanValidator         -> pure deterministic validation
    |-- TaskPlanStore             -> durable candidate/plan/task refs
    |-- TaskPlanScheduler         -> ready calculation and bounded dispatch
    |-- WorkerBindingResolver     -> registered capability -> pinned worker
    |-- TaskResultVerifier         -> deterministic task gates
    `-- StageAggregator           -> deterministic output role aggregation
    |
    v
Existing fixed Graph successor
    -> verify_claims
    -> quality_gate
    -> build_reader_payload
    -> build_paper_card
    -> publish_artifacts
```

`TaskPlanStageRunner` 是 Harness 管理的固定 stage runner，不是让 LLM 控制流程的新入口。TaskPlan 中的 task definition、task instance 和 task result 属于 run data，不会成为外层 Graph 的新 node definition。

### 7.2 生命周期映射

外层固定 Step 生命周期保持不变：

```text
PLAN -> EXECUTE -> VERIFY
```

dynamic stage 内部生命周期为：

```text
BUILD_CANDIDATE
    -> VALIDATE_CANDIDATE
    -> ACCEPT_PLAN
    -> SCHEDULE_READY_TASKS
    -> DISPATCH_TASKS
    -> COLLECT_RESULTS
    -> AGGREGATE_OUTPUTS
    -> VERIFY_STAGE
    -> COMPLETE
```

失败路径为：

```text
candidate/schema failure -> bounded candidate rebuild or HALT
task failure             -> task retry -> PlanPatch or HALT
stage gate failure       -> PlanPatch or outer Step REPLAN/HALT
event/checksum failure   -> fail closed
budget exhaustion        -> HALT
```

`PLAN` 阶段负责生成和接受 plan，`EXECUTE` 阶段负责调度和收集 task，`VERIFY` 阶段负责 deterministic task/stage gates。LLM 不得跳过任何阶段。

### 7.3 单一决策入口

- `HarnessScheduler` 仍是 Control Plane 可见的唯一调度决策入口。
- `TaskPlanScheduler` 是 `HarnessScheduler` 内部的受控组件，不是另一个平级的 workflow scheduler。
- `WorkflowGraphEvaluator` 只解释外层 Graph。
- `TaskPlanValidator`、ready calculation 和 patch validator 都必须是无 I/O 的确定性组件。
- `HarnessControlPlane` 负责提交 decision event、分配 activity identity、调用 worker、接收结果和更新 projection。

## 8. 核心术语

| 名称 | 定义 |
|---|---|
| `Harness Control Graph` | 在 Run 创建前编译、验证、冻结的外层 Workflow Graph。 |
| `Dynamic Stage` | 外层 Graph 中显式声明允许生成 TaskPlan 的固定 executable node。 |
| `PlanCandidate` | LLM 生成的候选计划，只包含语义任务分解和 capability hints。 |
| `TaskSpec` | 候选计划中的单个任务定义，不等于队列中的 `Task`。 |
| `ValidatedTaskPlan` | Harness 校验、解析 binding、归一化预算后接受的不可变计划版本。 |
| `Task Definition` | plan 内逻辑任务，跨 retry attempt 保持相同 identity。 |
| `Task Instance` | 某个 task definition 的一次执行实例，包含 attempt 和 fencing identity。 |
| `PlanPatch` | 基于旧 plan version 的受控增量变更。 |
| `Worker Capability` | 业务层可请求的能力名称，不是任意 worker implementation。 |
| `Worker Binding` | Harness 根据 registry 解析得到的精确 contract reference。 |
| `Output Role` | stage 需要的语义输出槽位，例如 `analysis.structure`。 |
| `Ready Task` | 所有必需依赖成功、输入引用可解析、预算已预留且尚未 dispatch 的 task。 |
| `Committed Result` | 已写入 durable event 并通过 identity/checksum 校验的 task result。 |
| `Plan Version` | 同一 stage 的单调递增计划版本，初始版本为 1。 |

## 9. 数据契约

### 9.1 通用约束

所有以下对象必须：

- 使用 versioned schema 和 canonical JSON 序列化；
- 在构造时验证必填字段、类型、长度、引用格式和可序列化性；
- 生成稳定 checksum；
- 不携带 callable、未序列化对象、raw prompt、secret 或未授权 tenant data；
- 对未知 schema/version/operation fail closed。

推荐 schema 标识：

```text
newsroom.harness-task-plan/v1
newsroom.harness-task-plan-patch/v1
```

### 9.2 `TaskSpec`

`TaskSpec` 是候选任务定义，字段语义如下：

| 字段 | 必填 | 语义 |
|---|---:|---|
| `task_id` | 是 | 在同一个 candidate 内唯一，接受后不得复用历史 task id。 |
| `objective` | 是 | 面向 worker 的任务目标，必须是非空、有限长度文本。 |
| `depends_on` | 否 | 同一 candidate 内的 task id 列表，不支持隐式依赖。 |
| `worker_capability` | 是 | capability hint，例如 `research.analysis.structure`。不是实际路由。 |
| `input_refs` | 是 | 对 stage context、artifact、memory 或前序输出的显式引用。 |
| `output_contract` | 是 | 允许的输出 schema 和 `output_role`。 |
| `acceptance_criteria` | 是 | 只能引用 stage policy 允许的 deterministic gate criteria。 |
| `requested_tools` | 否 | 工具请求，不代表授权；最终权限由 Harness policy 决定。 |
| `budget_request` | 否 | turns、tool calls、memory ops 等预算请求。 |
| `retry_policy` | 否 | task 级 retry 请求，最终上限由 policy 和 run budget 裁剪。 |
| `priority` | 否 | ready task 的逻辑优先级，默认 0；不得破坏依赖顺序。 |

候选任务不得出现 `worker_ref`、`handler`、`route`、`next_step`、`quality_passed`、`publish_artifact`、`write_memory`、`halt_workflow`、`promote_skill` 等控制字段。

### 9.3 `PlanCandidate`

```python
class PlanCandidate:
    schema_version: str
    candidate_id: str
    run_id: str
    workflow_id: str
    stage_id: str
    graph_checksum: str
    input_context_refs: tuple[str, ...]
    tasks: tuple[TaskSpec, ...]
    required_output_roles: tuple[str, ...]
    generated_by: str
    requested_plan_budget: dict[str, int]
    candidate_checksum: str
```

约束：

- `graph_checksum` 必须等于当前 run 的冻结 Graph checksum。
- `stage_id` 必须对应一个已注册 `TaskPlanPolicy`。
- `required_output_roles` 只能是 policy 允许的角色集合的子集，且不能减少 policy 的 required roles。
- `generated_by` 只用于 provenance，不得作为 worker 路由或授权依据。
- candidate 被拒绝时也必须持久化 candidate ref、拒绝原因和 validator version。

### 9.4 `ValidatedTaskPlan`

```python
class ValidatedTaskPlan:
    schema_version: str
    plan_id: str
    run_id: str
    workflow_id: str
    stage_id: str
    graph_checksum: str
    version: int
    parent_plan_id: str | None
    source_candidate_ref: str
    tasks: tuple[ResolvedTaskSpec, ...]
    required_output_roles: tuple[str, ...]
    limits: TaskPlanLimits
    plan_checksum: str
    accepted_at: str
```

`ResolvedTaskSpec` 在 `TaskSpec` 基础上增加：

- 精确且 pinned 的 `worker_ref`；
- Harness 计算后的 `allowed_tools`；
- 归一化后的 budget 和 retry policy；
- gate references；
- task definition checksum。

接受后的 `ValidatedTaskPlan` 不可原地修改。任何变更必须生成新的 plan version。

### 9.5 `TaskPlanPolicy`

```python
class TaskPlanPolicy:
    policy_id: str
    version: str
    stage_id: str
    allowed_worker_capabilities: tuple[str, ...]
    allowed_subagent_ids: tuple[str, ...]
    allowed_tool_ids: tuple[str, ...]
    allowed_memory_namespaces: tuple[str, ...]
    allowed_output_roles: tuple[str, ...]
    required_output_roles: tuple[str, ...]
    allowed_gate_refs: tuple[str, ...]
    max_tasks: int
    max_depth: int
    max_parallelism: int
    max_replans: int
    max_task_attempts: int
    max_plan_build_turns: int
    max_plan_build_tool_calls: int
```

Policy 必须在 Graph 准备阶段注册并 pinned。LLM 不能在 candidate 中覆盖 policy。

### 9.6 `PlanPatch`

```python
class PlanPatch:
    schema_version: str
    patch_id: str
    run_id: str
    stage_id: str
    base_plan_id: str
    base_plan_version: int
    reason_code: str
    source_candidate_ref: str
    operations: tuple[PlanPatchOperation, ...]
    patch_checksum: str
```

v1 只允许三种 operation：

1. `ADD_REPLACEMENT_TASK`：为失败或缺失输出增加新 task definition。
2. `SKIP_PENDING_TASK`：将尚未启动且不属于 required output role 的 task 标记为 skipped。
3. `UPDATE_PENDING_DEPENDENCY`：只调整尚未启动 task 的依赖，且新依赖必须通过完整 DAG 校验。

禁止：

- 修改 `SUCCEEDED`、`RUNNING`、`COMMITTED` task；
- 覆盖历史 artifact/output ref；
- 删除已经写入 durable history 的 task；
- 修改 `required_output_roles`、worker policy、gate policy 或外层 Graph；
- 添加 publication、side effect、quality decision 或 memory promotion task。

## 10. LLM、Harness 与 Worker 边界

### 10.1 LLM 可以做什么

- 根据 stage 输入和已授权 context 提出任务分解；
- 提出任务之间的显式依赖；
- 提出 capability hint、输出 role、验收标准和预算请求；
- 针对失败原因提出 `PlanPatch` 候选。

### 10.2 LLM 不可以做什么

- 修改 `NormalizedHarnessGraph` 或外层 Graph checksum；
- 指定实际 worker implementation、handler version 或任意 callable；
- 决定 route、next step、join、loop exit、winner 或 compensation；
- 决定 quality pass/fail、publication、memory write、skill promotion 或 halt；
- 授权工具、扩大 memory namespace 或突破 tenant/context boundary；
- 直接写 Task queue、event store、checkpoint 或 active skill package。

### 10.3 Harness 的确定性职责

Harness 必须：

- 解析和校验 candidate/patch schema；
- 校验 DAG、输入输出 dataflow 和 stage boundary；
- 将 capability 解析为唯一的 pinned worker binding；
- 将 requested tools/memory/budget 与 policy 求交集；
- 计算 ready tasks 和稳定调度顺序；
- 原子预留和消耗 budget；
- 运行 deterministic task/stage gates；
- 接受或拒绝 plan version；
- 写入事件、checkpoint、transcript 和 inspection projection。

## 11. Plan 验证规则

候选计划只有在以下规则全部通过后才能 dispatch：

### 11.1 Schema 验证

- 所有必填字段存在且类型正确；
- ID、引用、schema 和版本格式正确；
- `tasks` 非空且不超过 `max_tasks`；
- `depends_on`、`input_refs`、output role 和 gate refs 可序列化；
- 禁止字段在顶层、嵌套 output、diagnostics 和 metadata 中都不得出现。

### 11.2 DAG 验证

- task id 唯一；
- 依赖只能指向同一 candidate 的 task；
- 不允许 self-loop、cycle 或隐式依赖；
- DAG depth 不超过 `max_depth`；
- 所有 task 从 stage entry 可达；
- 至少有一个 task 能从零依赖开始；
- required output role 必须存在可达 producer。

### 11.3 Stage boundary 验证

- `stage_id` 必须是固定 Graph 中声明的 dynamic stage；
- 不得引用未来 stage 的输出；
- 不得跳过固定前置 stage；
- 不得创建外层 Graph successor、side effect 或 publication task；
- task 输出只能写入 policy 声明的 namespace 和 output role。

### 11.4 Worker binding 验证

- capability 必须在 policy allowlist 中；
- capability 必须解析为唯一的 registry binding；
- binding 的 contract/version 必须与 pinned runtime compatible；
- 候选不得直接传入 worker ref、handler 或 callable；
- `subagent_id` 必须存在且匹配 allowed subagent set；
- nested subagent 默认禁止，除非 stage policy 明确允许。

### 11.5 Dataflow 和输出验证

- 每个 input ref 必须来自 stage input、已接受 artifact 或已完成上游 task；
- 同一 output role 不允许多个 task 无条件写入；
- 允许的聚合必须通过 policy 声明的 deterministic aggregator；
- output contract 必须是 policy allowlist 中的 schema；
- acceptance criteria 只能引用已注册 deterministic gate；
- candidate 不能把 LLM 自评结果当成 gate result。

### 11.6 工具、memory 和预算验证

- requested tools 只能从 stage policy 的 allowed tools 中选择；
- 最终 `allowed_tools` 由 Harness 计算，不由 LLM 授权；
- memory namespace 必须匹配现有 `SubAgentMemoryNamespaceGate`；
- task budget 不能超过 task、stage 或 run 剩余预算；
- `max_parallelism`、`max_replans`、`max_attempts` 和 `max_plan_build_turns` 必须有界；
- 预留失败时不得 dispatch 任何未预留 task。

任何验证失败都必须在第一个 task dispatch 前记录 typed failure event。

## 12. 调度与执行

### 12.1 Ready 计算

task 只有同时满足以下条件才是 ready：

- 所有必需 dependency 已进入 `SUCCEEDED` 且 result 已 durable commit；
- 所有 input refs 可解析且 checksum 匹配；
- task 尚未被 dispatch 或已完成；
- task 没有被 skip/block；
- budget reservation 成功；
- worker binding、tool policy、memory policy 仍然有效。

v1 的 dependency 语义为 all-success。依赖失败或 skipped 时，下游 task 不会自动执行，必须由受控 `PlanPatch` 明确处理。

### 12.2 稳定调度顺序

在物理并发限制内，ready task 使用以下稳定顺序：

1. `priority` 升序；
2. dependency depth 升序；
3. `task_id` 字典序；
4. `task_definition_checksum` 字典序。

ready 不等于立即并发。实际 dispatch 必须受 `max_parallelism`、budget、worker capacity 和 queue availability 限制。

### 12.3 Queue 投影

现有 `framework/workers/models/task.py` 继续作为通用执行队列模型。TaskPlan Runtime 只向其 payload/metadata 写入：

```text
run_id
workflow_id
stage_id
plan_id
plan_version
task_id
task_instance_id
attempt
task_checksum
```

依赖关系、plan version 和 task 状态的权威来源是 TaskPlan event/projection，不是 generic queue record。queue record 丢失、重复或延迟时，Control Plane 依据 durable plan state 决定是否重投。

### 12.4 Dispatch 和结果提交

dispatch 顺序必须是：

```text
reserve budget
  -> commit TASK_READY/TASK_DISPATCHED event
  -> allocate attempt and fencing identity
  -> invoke registered worker
  -> validate HarnessWorkerResult/SubAgentResult
  -> commit TASK_RESULT_ACCEPTED or TASK_RESULT_REJECTED
  -> update task projection
```

worker result 必须携带可验证的 `run_id`、`plan_id`、`plan_version`、`task_id` 和 `attempt`。过期版本、重复 attempt、错误 worker binding 或 checksum 不匹配的结果必须拒绝。

### 12.5 聚合

聚合必须是确定性 service/aggregator，不是 LLM 路由决策。聚合器只能读取已接受 task results，按稳定 task order 生成 stage output refs，并验证 required output roles 完整。

## 13. Retry、Replan、Halt

### 13.1 Retry

- worker transport failure、retryable error 或 task gate failure 可以在 `max_task_attempts` 内重试；
- 每次 retry 使用新的 `task_instance_id` 和 attempt，但保留 task definition identity；
- 已提交的 result 不得被 retry 覆盖；
- 不可重试错误必须直接进入 task terminal failure。

### 13.2 Replan 触发条件

只有以下原因可以触发动态 replan：

- candidate schema 或 DAG 无效且仍有 plan build budget；
- task 达到 retry 上限但 stage policy 允许 repair；
- deterministic stage gate 提供可修复的缺口；
- required output role 缺失且存在可用 capability；
- worker binding 在执行前失效且 policy 声明允许替换。

以下情况不得通过 LLM replan 绕过：

- Graph checksum/version 不匹配；
- event store、checkpoint 或 plan artifact 不可验证；
- unauthorized tool/memory/tenant access；
- publication、side effect 或 quality gate authorization 失败；
- run 或 stage budget 已耗尽。

### 13.3 Patch 接受流程

```text
collect failure context
  -> LLM proposes PlanPatch candidate
  -> validate base_plan_version
  -> validate allowed operations
  -> re-run full DAG/dataflow/policy/budget validation
  -> reserve incremental budget
  -> commit PLAN_PATCH_ACCEPTED
  -> create version N+1
  -> recompute ready tasks
```

patch 的 `base_plan_version` 必须等于当前权威版本。并发 patch、重复 patch 或旧版本 patch 必须拒绝，不得自动 merge。

### 13.4 Halt 规则

以下任一条件满足时 stage 必须 halt 或按 outer Step failure policy 结束：

- `max_replans`、`max_plan_build_turns`、task retry 或 budget 上限耗尽；
- required output role 无法满足；
- plan artifact、event 或 result checksum 无法验证；
- worker binding 无法唯一解析；
- 检测到 cycle、非法跨 stage ref 或未经授权字段；
- event store 不可用且无法安全提交下一步决定。

Halt 必须给出 typed reason code，并且不得伪装为成功或自动 publication。

## 14. Durable Event、Checkpoint、Replay 与 Inspection

### 14.1 事件类型

至少记录以下事件：

- `PLAN_CANDIDATE_BUILT`
- `PLAN_CANDIDATE_REJECTED`
- `PLAN_VALIDATION_FAILED`
- `PLAN_ACCEPTED`
- `TASK_READY`
- `TASK_DISPATCHED`
- `TASK_STARTED`
- `TASK_RETRY_SCHEDULED`
- `TASK_RESULT_ACCEPTED`
- `TASK_RESULT_REJECTED`
- `TASK_COMPLETED`
- `TASK_FAILED`
- `TASK_BLOCKED`
- `TASK_SKIPPED`
- `PLAN_PATCH_PROPOSED`
- `PLAN_PATCH_REJECTED`
- `PLAN_PATCH_ACCEPTED`
- `STAGE_OUTPUT_AGGREGATED`
- `TASK_PLAN_VERIFIED`
- `TASK_PLAN_HALTED`

### 14.2 事件关联字段

每个事件至少包含：

```text
run_id
workflow_id
stage_id
graph_checksum
plan_id
plan_version
task_id           optional
task_instance_id  optional
attempt           optional
schema_version
actor_type
causal_event_ref
input_checksum
output_refs
reason_code
```

事件 payload 使用 refs 和 checksum，不能嵌入完整 raw prompt、secret、tenant-private payload 或大型 worker output。

### 14.3 Checkpoint

TaskPlan checkpoint 至少包含：

- frozen Graph checksum；
- 当前 `plan_id` 和 `plan_version`；
- plan checksum 和 policy ref/version；
- 每个 task definition/instance 的状态、attempt、fencing identity；
- ready queue 的稳定排序 key；
- 已接受 output refs 和 output role projection；
- reserved/consumed budget；
- replan count、retry count 和 last durable stream sequence。

### 14.4 Replay

- replay 使用已持久化的 candidate、accepted plan、patch 和 worker result，不调用 live LLM/worker/tool；
- replay 只能重建 projection 和 deterministic decisions；
- 已完成 task 不得再次执行；
- plan、patch、result 或 event checksum 不匹配时 fail closed；
- replay 结果必须输出原始与重建的 decision checksum 对比。

### 14.5 Inspection

Run inspection 必须展示：

- dynamic stage 开关、policy ref/version；
- candidate/plan/patch refs；
- 当前 plan version 和 checksum；
- task 状态统计、dependency、attempt、binding 和输出 refs；
- 当前 ready/running/waiting/blocked task；
- budget/replan/retry 使用量；
- 最后 durable sequence 和 replay verification result。

raw prompt、完整 transcript、未脱敏 tool result 和未授权 tenant data 不得出现在公开 inspection 或 metrics label 中。

## 15. Research 动态分析试点

### 15.1 固定流程

新增动态版本不改变现有静态版本。动态版本的外层 Graph 为：

```text
load_paper_source
    -> compile_document
    -> run_research_rag
    -> build_evidence_pack
    -> dynamic_analysis_stage
    -> verify_claims
    -> quality_gate
    -> build_reader_payload
    -> build_paper_card
    -> publish_artifacts
```

建议提供独立构建入口：

```python
build_dynamic_paper_analysis_workflow_spec()
```

静态入口 `build_paper_analysis_workflow_spec()` 保持原样，默认不切换到动态版本。

### 15.2 Dynamic stage contract

`dynamic_analysis_stage` 的固定 policy 至少声明：

```text
stage_id: research.analysis
input_refs: document, evidence_pack
required_output_roles:
  - analysis.structure
  - analysis.contribution
  - analysis.experiments
aggregate_output_key: analysis_branch_refs
```

允许的 capability 由 Research registry 映射到现有 `SubAgentSpec` 和 gates，例如：

```text
research.analysis.structure
research.analysis.contribution
research.analysis.experiments
research.analysis.claim_support
```

candidate 可以把一个 output role 拆成多个前置 task，但最终必须由 deterministic aggregator 生成现有 `analysis_branch_refs`。如果 required role 缺失、重复写入或没有合法 aggregator，plan 必须拒绝。

### 15.3 Research task gates

每个 dynamic task 的 gate 只能来自 Research 已注册 contract：

- `SummarySchemaGate@1`
- `SummaryEvidenceCoverageGate@1`
- `BenchmarkEvidenceLineageGate@1`

聚合结果继续进入：

- `ClaimEvidenceGate@1`；
- `ResearchQualityGate@1`；
- 既有 reader payload、paper card 和 artifact publication gates。

LLM 输出的自评质量、claim verification 或 publication decision 不得替代这些 gates。

### 15.4 Research failure behavior

- source、document、RAG、evidence、claim verification、quality gate 和 publication 失败仍遵循原有固定 Step policy；
- dynamic task 的 retry 只作用于该 task；
- analysis output 缺口可以触发 `ADD_REPLACEMENT_TASK`；
- `verify_claims` 失败时只有 Research policy 明确允许的 evidence repair 才能产生 patch；
- quality gate 或 artifact publication 失败不得由 LLM 通过 patch 直接标记成功；
- dynamic stage 未完成或未通过时，不得生成可发布 artifact。

### 15.5 Research 兼容性

- 静态 workflow 的 Graph checksum、输出 key、Gate contract 和 public result envelope 保持兼容；
- 动态 workflow 使用新的 workflow id/version 和 Graph checksum，不覆盖旧 run；
- 动态 metadata 只增加 plan/task refs，不把 raw candidate 或 prompt 放入业务结果；
- 原有 Research replay fixture 继续通过；动态 fixture 单独建立 golden history。

## 16. 对外接口与注册边界

### 16.1 新增或扩展的框架接口

PRD 后续实现应提供以下窄接口，具体模块位置由 design artifact 决定：

```python
class PlanCandidateBuilderPort(Protocol):
    def build_candidate(self, request: PlanBuildRequest) -> PlanCandidate:
        ...


class TaskPlanStorePort(Protocol):
    def append_candidate(self, candidate: PlanCandidate) -> str:
        ...

    def accept_plan(self, plan: ValidatedTaskPlan) -> str:
        ...

    def append_patch(self, patch: PlanPatch) -> str:
        ...

    def load_projection(self, run_id: str, stage_id: str) -> TaskPlanProjection:
        ...


class TaskPlanScheduler(Protocol):
    def next_ready_tasks(
        self,
        projection: TaskPlanProjection,
        max_count: int,
    ) -> tuple[TaskInstanceRequest, ...]:
        ...


class TaskPlanStageRunner(Protocol):
    def run(self, request: TaskPlanStageRequest) -> HarnessWorkerResult:
        ...
```

这些接口不能绕过 `HarnessControlPlane` 直接写 durable event、worker registry 或 queue。

### 16.2 Worker type

如实现需要显式绑定固定 dynamic stage，新增 `HarnessWorkerType.TASK_PLAN`，序列化值为 `task_plan`。

该 worker type 表示 Harness 管理的 stage runner，不表示 LLM 获得新的控制权。runtime binding、reader、schema catalog、replay 和 version validation 必须同步支持该类型。

### 16.3 既有接口兼容

- `SubAgentSpec`、`SubAgentInvocation`、`SubAgentResult` 的核心字段和禁止控制字段保持兼容；
- `HarnessWorkerResult` 继续作为 worker activity result envelope；
- `control.delegate_to_subagent` 不直接接受任意 `PlanCandidate`，动态 dispatch 必须经过 TaskPlan Runtime；
- generic queue `Task` 不新增 DAG dependency 语义；
- interface 层仍调用 application service，不直接调用 executor/store。

## 17. 功能需求

### FR-1：Dynamic stage registration

系统必须只允许已注册且 pinned 的 `TaskPlanPolicy` 启用 dynamic stage。未知 policy、版本不匹配或 Graph 未声明 dynamic stage 时，Run 必须在 dispatch 前失败。

### FR-2：Candidate generation

系统必须通过受控 `PlanCandidateBuilderPort` 调用 LLM worker，并将输入限制为 stage 允许的 context refs、memory refs 和 tool policy。LLM 输出只能被解析为 candidate，不得直接变成 accepted plan。

### FR-3：Candidate validation

系统必须在接受前完成 schema、DAG、stage boundary、worker binding、dataflow、output conflict、tool/memory 和 budget validation。

### FR-4：Plan acceptance

系统必须为每个 accepted plan 生成单调递增 version、canonical checksum、policy ref 和 source candidate ref，并在 dispatch 前提交 `PLAN_ACCEPTED` event。

### FR-5：Immutable plan version

accepted plan 不得原地修改。任何变更必须经过带 base version 的 `PlanPatch` 并生成新版本。

### FR-6：Ready task calculation

系统必须根据依赖成功状态、输入可用性、预算 reservation 和 worker binding 计算 ready task，并使用稳定顺序输出。

### FR-7：Bounded dispatch

系统必须同时受 stage `max_parallelism`、worker capacity、task retry policy、run budget 和 event commit 顺序限制，禁止无界并发。

### FR-8：Worker execution boundary

所有 task 必须通过已注册 worker/subagent binding 执行。TaskPlan Runtime 不得直接执行 callable、任意脚本或未注册 handler。

### FR-9：Result identity validation

系统必须验证 result 的 run、stage、plan、task、attempt、worker binding 和 checksum identity。过期、重复、越权或不匹配 result 不得改变 projection。

### FR-10：Deterministic task verification

每个 task 的 output contract、acceptance criteria 和 gate result 必须由 deterministic gate 验证。LLM 自评不得作为通过条件。

### FR-11：Deterministic aggregation

系统必须通过已注册 aggregator 生成 stage output，拒绝隐式 last-writer-wins、未声明覆盖和不完整 required output role。

### FR-12：Retry

系统必须在 task 和 stage policy 允许的次数内 retry，并为每次 attempt 生成独立 identity 和 durable event。

### FR-13：Controlled replan

系统必须只接受通过 base version、operation、DAG、policy、dataflow 和 budget 校验的 `PlanPatch`。失败 patch 不得启动 task。

### FR-14：Bounded halt

系统必须在 plan build、retry、replan、budget、checksum 或 event store 安全条件不满足时 typed halt，不能降级为成功。

### FR-15：Durable history

系统必须记录 candidate、plan、patch、task readiness、dispatch、result、retry、aggregation、verify 和 halt 的 canonical events。

### FR-16：Checkpoint and replay

系统必须保存恢复动态 stage 所需的 plan/task projection，并从 durable history 重建而不调用 live LLM/worker。

### FR-17：Inspection

系统必须向受授权 operator 暴露 plan/task 状态、版本、checksum、预算、失败原因和 replay verification，且不得泄露 raw prompt 或未授权数据。

### FR-18：Research pilot compatibility

Research dynamic analysis 必须保持既有后续 `verify_claims -> quality_gate -> artifacts` 的输入输出和安全边界，并保留静态 workflow。

## 18. 非功能需求

### NFR-1：确定性

- 相同 Graph checksum、policy version、accepted plan、projection 和 observation 必须产生相同 ready order、aggregation 和 control decision；
- validator、scheduler、aggregator 不读取真实时钟、随机数、网络或可变全局状态；
- 所有集合、依赖、事件和 output refs 使用稳定排序；
- decision、plan、patch 和 projection 必须可 canonical serialize 并生成 checksum。

### NFR-2：安全与隔离

- context、tool、memory、tenant 和 identity boundary 继续由 Harness gates 控制；
- LLM 不得改变 tool authorization、memory namespace、quality gate 或 publication policy；
- 未知 schema、capability、worker binding、gate、operation 或 version fail closed；
- inspection、metrics、trace 和 event payload 必须脱敏并限制 payload 大小。

### NFR-3：可靠性

- durable event 提交失败时不得启动下一项 activity；
- crash/restart 不得重复执行已经 committed 的非确定性结果；
- queue 重复投递必须通过 attempt/fencing/idempotency 防止重复提交；
- 计划 artifact、result ref 或 event checksum 损坏时必须 halt 并保留诊断。

### NFR-4：性能与容量

- ready 计算不能在每个 task 完成时无界扫描全部历史 event；
- scheduler 必须支持至少 100 个 ready task，并以 policy 的 `max_parallelism` 限制实际 dispatch；
- event 只保存 refs 和摘要，完整 output 放入既有 artifact/result store；
- 具体延迟目标在 golden fixture 和基准测试建立后锁定，不能牺牲 durable commit 和确定性换取吞吐。

### NFR-5：可测试性

- validator、scheduler、patch validator、aggregator 和 reducer 必须支持纯内存单元测试；
- Control Plane 必须支持 fake event/activity/gate/worker/queue/store ports；
- 必须提供 crash-point、duplicate-result、stale-version 和 replay fixtures；
- Research dynamic pilot 必须有离线 fake LLM 和 fake subagent E2E 场景。

## 19. 事件时序示例

### 19.1 首次动态计划执行

```text
HarnessScheduler
    -> ENTER_STEP_PHASE(PLAN)
ControlPlane
    -> PLAN_CANDIDATE_BUILT
TaskPlanValidator
    -> VALIDATE_CANDIDATE
ControlPlane
    -> PLAN_ACCEPTED(version=1)
HarnessScheduler
    -> ENTER_STEP_PHASE(EXECUTE)
TaskPlanScheduler
    -> TASK_READY(A, B)
ControlPlane
    -> TASK_DISPATCHED(A)
    -> TASK_DISPATCHED(B)
Workers
    -> TASK_RESULT_ACCEPTED(A)
    -> TASK_RESULT_ACCEPTED(B)
TaskPlanScheduler
    -> TASK_READY(C, depends_on=A)
ControlPlane
    -> TASK_DISPATCHED(C)
StageAggregator
    -> STAGE_OUTPUT_AGGREGATED(analysis_branch_refs)
HarnessScheduler
    -> ENTER_STEP_PHASE(VERIFY)
Research gates
    -> TASK_PLAN_VERIFIED
```

### 19.2 失败后增量 patch

```text
Task B
    -> TASK_FAILED(attempt=2, retry_exhausted)
TaskPlanStageRunner
    -> PLAN_PATCH_PROPOSED(base_version=1)
TaskPlanValidator
    -> validate only allowed pending-task changes
ControlPlane
    -> PLAN_PATCH_ACCEPTED(version=2)
TaskPlanScheduler
    -> keep completed A immutable
    -> add replacement B2
    -> recompute ready tasks
```

### 19.3 Replay

```text
Checkpoint
    -> load graph_checksum, plan_version, task projection
Event stream
    -> rebuild accepted plan, attempts and output refs
Replay reducer
    -> recompute ready order and deterministic gates
Replay verifier
    -> compare decision checksums
```

## 20. 观测与运营指标

至少提供以下 metrics/inspection fields：

- candidate count、candidate rejection count、validation failure reason；
- accepted plan count、patch count、plan version distribution；
- task ready/running/succeeded/failed/blocked/skipped count；
- task latency、attempt count、retry rate、worker capability；
- budget reserved/consumed/exhausted；
- deterministic gate failure reason；
- stale result、duplicate result、binding mismatch、checksum mismatch；
- replay verification pass/fail；
- dynamic stage success、halt、fallback-disabled count。

metrics label 不得包含 `run_id` 以外的高基数 raw payload、prompt、secret 或 tenant-private value。完整诊断使用受访问控制的 refs。

## 21. 迁移、启用与回滚

### Phase 0：契约和 fixture

- 固化 TaskPlan schema、policy、decision、event 和 checkpoint contract；
- 为 validator、scheduler、patch、replay 建立 deterministic golden fixtures；
- 固化 Research 静态 workflow 的输出和 gate parity fixture。

### Phase 1：框架运行时

- 实现 `TaskPlanValidator`、`TaskPlanScheduler`、`TaskPlanStorePort`、stage runner 和 durable projection；
- 接入现有 worker/subagent binding、budget、tool/memory gates 和 queue adapter；
- 完成 crash/replay、duplicate result、stale patch 和 fail-closed 测试。

### Phase 2：Research opt-in

- 增加 `build_dynamic_paper_analysis_workflow_spec()`；
- 默认继续使用静态 workflow；
- 通过明确 workflow id/version 启用 dynamic analysis；
- 仅允许非 publication 的 analysis tasks 使用动态计划。

### Phase 3：离线评估

- 使用固定 candidate fixture、fake LLM 和 fake subagent 对比静态与动态输出；
- 比较 required output role 完整性、claim verification、quality gate 和 artifact refs；
- 只有在 deterministic parity、replay 和 budget gate 通过后才扩大范围。

### 回滚

- 未开始写入新 dynamic run 前，可以停用 dynamic workflow id，继续使用静态 workflow；
- 已接受 dynamic plan 的 run 不得压缩成旧的 `current_step_id` 语义；必须恢复、完成或明确 halt；
- 已提交的 task result、event 和 checkpoint 不得通过删除或伪造恢复来实现回滚。

## 22. 验收矩阵

| 能力 | 必须验证 |
|---|---|
| Candidate | 合法 schema 可解析；禁止控制字段被拒绝；来源和 checksum 可追踪。 |
| DAG | 依赖正确；cycle、self-loop、未知 task 和不可达 task 被拒绝。 |
| Binding | capability 唯一解析到 pinned worker；未知或冲突 binding fail closed。 |
| Dataflow | 输入引用可解析；required output role 完整；输出冲突不允许隐式覆盖。 |
| Scheduling | ready order 稳定；并发和预算有界；queue projection 不成为 DAG 权威。 |
| SubAgent | context、tool、memory、budget 和 output gates 继续有效。 |
| Verification | task/stage gate deterministic；LLM 自评不能通过验证。 |
| Replan | base version、operation、pending-task invariant 和新 checksum 正确。 |
| Retry | attempt/fencing identity 唯一；已提交结果不重复执行或覆盖。 |
| Durable event | 所有未来决策都有 event；event store 不可用时 fail closed。 |
| Replay | 不调用 live worker/LLM；projection 和 decision checksum 一致。 |
| Research | dynamic stage 输出兼容 `analysis_branch_refs`、`verify_claims`、quality gate 和 artifacts。 |
| Compatibility | 静态 Research workflow、既有 SubAgent Runtime 和旧 replay fixture 不回归。 |

## 23. 必须覆盖的测试场景

### 单元测试

- `TaskSpec`、`PlanCandidate`、`ValidatedTaskPlan`、`PlanPatch` 的字段、schema、序列化和 checksum；
- candidate forbidden field 的递归检测；
- DAG cycle、depth、reachability、duplicate id 和 required role validation；
- capability binding、tool/memory allowlist 和 budget intersection；
- ready task 的稳定排序、dependency completion 和 max parallelism；
- output role 冲突、deterministic aggregation 和 missing role；
- patch operation、base version、pending-task invariant 和 checksum；
- stale result、duplicate result、wrong attempt、wrong worker binding 拒绝。

### Harness 集成测试

- `PLAN -> EXECUTE -> VERIFY` 中 dynamic stage 的 phase transition；
- candidate reject 时不发生 worker dispatch；
- plan accepted 后多个独立 task bounded dispatch；
- task result durable commit 后才激活下游 task；
- retry exhaustion 后受控 patch 或 halt；
- event store 不可用时不推进状态、不启动新 activity；
- crash 在 reserve、dispatch、result commit、aggregation 前后的恢复；
- replay 不重复调用 live worker/LLM/tool，并复现 decision checksum。

### Research E2E 测试

- 使用 fake LLM 生成 structure/contribution/experiments 合法候选；
- 使用 fake subagent 执行并行任务和有依赖任务；
- 验证输出生成 `analysis_branch_refs` 并通过 `verify_claims`；
- 缺少 required role 时不进入 quality gate 和 publication；
- 任务失败后生成 replacement task，历史结果保持不变；
- dynamic workflow 与 static workflow 的 public result envelope 和 gate 结果兼容；
- static `build_paper_analysis_workflow_spec()` 回归测试全部通过。

## 24. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 生成过大的 DAG | 成本、延迟和调度压力 | max tasks/depth/parallelism、budget preflight、fail closed。 |
| candidate 伪装成 routing decision | Harness 控制权被绕过 | capability hint 与 pinned binding 分离，递归禁止字段 gate。 |
| 多 task 写同一输出 | 结果不确定 | output role namespace、冲突拒绝、显式 deterministic aggregator。 |
| patch 修改历史结果 | replay 和审计失真 | immutable completed/running task、base version、单调版本。 |
| queue 与 plan 状态漂移 | 重复或丢失执行 | plan event/projection 为权威，queue 只是投影，attempt/fencing 去重。 |
| dynamic stage 泄漏到 publication | 未验证内容被发布 | policy 禁止 side effect/publication task，固定 quality/artifact successor。 |
| Research contract 漂移 | 既有质量门失败 | required output roles、`analysis_branch_refs`、golden parity fixture。 |
| durable event 缺失 | 无法恢复或 replay | 所有未来决定先 commit event，store 不可用时 fail closed。 |
| TaskPlan Runtime 变成第二套 Harness | 架构分裂 | TaskPlanScheduler 仅作为 HarnessScheduler 内部组件，复用既有 Control Plane。 |

## 25. 依赖与前置条件

- `harness-workflow-graph-runtime` 已完成 Graph freeze、deterministic scheduler、event、checkpoint 和 replay contract；
- 现有 `SubAgentSpec`、`SubAgentRuntime`、SubAgent gates 和 transcript store 可复用；
- 现有 worker registry 能提供 capability 到 pinned binding 的唯一解析；
- 现有 event/checkpoint/artifact ports 支持 plan/task refs 和 checksum；
- Research gates、`analysis_branch_refs`、`verify_claims` 和 artifact publication contract 保持稳定；
- OpenSpec 后续 proposal/design/spec/tasks 必须以本 PRD 为产品约束来源，不得自行放宽 LLM/Harness 边界。

## 26. 锁定的设计结论

1. 新变更是独立 follow-up：`harness-dynamic-task-planning`。
2. 动态计划是 stage-local TaskPlan DAG，不是跨全 Run 的总 DAG。
3. 外层 `NormalizedHarnessGraph` 永不被运行时 candidate 或 patch 修改。
4. LLM 生成 candidate/patch，Harness 验证、接受、绑定、调度和验证结果。
5. `PlanCandidate` 使用 capability hint，实际 `worker_ref` 由 Harness registry 解析。
6. accepted plan 不可变，所有修改使用增量、版本化 `PlanPatch`。
7. 已完成、运行中和已提交结果不可被 patch 修改或删除。
8. generic queue `Task` 只做执行投影，不承载 TaskPlan DAG 权威状态。
9. 确定性的 source、evidence、quality gate、publication 和 side effect 不进入 LLM 动态规划。
10. Research 首个试点只动态化 `analysis`，固定 `verify_claims -> quality_gate -> artifacts` 路径。
11. 静态 Research workflow 保留并默认启用，动态 workflow 通过独立 workflow id/version opt-in。
12. event store、checkpoint、plan artifact 或 checksum 不可验证时必须 fail closed。

## 27. 完成定义

本 PRD 对应的 OpenSpec 变更只有在以下条件全部满足时才可标记完成：

- TaskPlan contracts、validator、scheduler、store、stage runner 和 policy registry 已有明确实现边界；
- 所有 FR/NFR 的关键测试和故障场景具备可执行测试；
- Research dynamic analysis pilot 可以在离线 fake runtime 中完成并通过 deterministic gates；
- static Research workflow 和既有 Graph/SubAgent/replay 回归通过；
- operator 可以查看 plan/task/replan/replay 状态；
- 未授权 LLM routing、quality、memory、tool、publication 行为在 schema 和 runtime gates 两层均被拒绝；
- OpenSpec strict validation 通过，且没有新增与旧 Graph Runtime 平行的调度真相来源。
