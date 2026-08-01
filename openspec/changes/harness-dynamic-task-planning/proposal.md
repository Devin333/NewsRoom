## Why

当前 Harness 的 `PLAN` 阶段主要执行工具、重复和预算校验，并没有把一个业务目标拆分为可独立调度的任务 DAG。Research 分析阶段因此只能依赖固定的 `ParallelAll` 分支；当论文类型、证据缺口或失败原因变化时，系统无法在保持外层流程安全边界的前提下增加、替换或复用分析任务。

现在补齐这一能力，是因为 `harness-workflow-graph-runtime` 已经提供了不可变 Graph、`PLAN -> EXECUTE -> VERIFY`、durable event、checkpoint 和 replay 基础。动态任务应作为固定 Graph 内的 stage-local run data 建模，而不是再次引入一个可以修改 Graph 或由 LLM 控制路由的执行引擎。

## What Changes

- 新增 `PlanCandidate`、`TaskSpec`、`ValidatedTaskPlan`、`PlanPatch` 和 `TaskPlanPolicy` 契约。
- 新增 Harness 管理的 TaskPlan validation、worker capability binding、ready-task scheduling、bounded dispatch、deterministic aggregation 和 versioned replan。
- 让 LLM 只生成 candidate/patch；Harness 独占实际 worker 路由、工具授权、质量判定、memory、publication、预算和 halt 决策。
- 将 TaskPlan 状态、计划版本、任务 attempt、结果引用、patch 和 replay 信息写入既有 canonical durable event/checkpoint/transcript 边界。
- 保持冻结的 `NormalizedHarnessGraph` 不可变；TaskPlan 只能存在于外层 Graph 显式声明的 dynamic stage 内。
- 保留通用队列 `Task` 的执行职责，不把 DAG 依赖和计划版本塞入通用队列模型；队列记录只作为 TaskPlan 的执行投影。
- 新增 Research dynamic analysis workflow variant，将固定分析分支替换为 `dynamic_analysis_stage`，并继续使用既有 `verify_claims`、quality gate 和 artifact publication 路径。
- 保留现有静态 Research workflow，动态版本通过独立 workflow id/version 显式启用。

## Capabilities

### New Capabilities

- `harness-task-plan`: 定义动态计划契约、候选验证、capability binding、DAG 调度、任务执行、聚合、retry/replan、持久化和 replay 行为。
- `research-dynamic-analysis-stage`: 定义 Research `analysis` stage 的动态计划边界、输入输出角色、确定性 gates、兼容性和失败语义。

### Modified Capabilities

- `harness-runtime`: 扩展 Harness authority、`PLAN -> EXECUTE -> VERIFY`、controlled failure 和 durable replay 要求，使动态 TaskPlan 仍由 Harness 控制且不能修改外层 Graph。

## Impact

- 框架边界：`framework/harness/workflow`、`framework/harness/control_plane`、worker binding、SubAgent Runtime、event/checkpoint/replay ports。
- Research：`business/research/workflows/paper_analysis_workflow.py` 的可选 dynamic workflow variant 和对应 gates/aggregator wiring。
- 新增 versioned plan/task event、projection、inspection 和测试 fixture；复用现有 event store、artifact/result refs、queue adapter、SubAgent gates 和 budget policy。
- 不新增分布式队列、第二套 event store、第二个平级 scheduler，也不修改旧静态 Research workflow 的默认行为。
