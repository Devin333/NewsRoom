# Harness TaskPlan Runtime

TaskPlan 是固定 Harness Graph 中 dynamic stage 的 stage-local DAG。外层 graph 在运行前冻结并保持原始 checksum；LLM 只能返回 `PlanCandidate` 或 `PlanPatch`，不能携带 worker、route、quality、publication、memory 或 authorization 控制字段。

## 生命周期

`PLAN` 解析并校验候选，解析 pinned `TaskPlanPolicy` 和 capability binding，然后提交不可变的 `ValidatedTaskPlan` version 1。`EXECUTE` 由 `TaskPlanScheduler` 按依赖成功、输入可用、预算和并发上限计算 ready task，并把 `TaskInstance` 投影到通用 queue。`VERIFY` 只接受通过绑定 gate 的结果，再由确定性 aggregator 按 output role 生成 stage refs。

每次候选、计划、ready、dispatch、start、result、retry、patch、aggregation、verify 和 halt 都写入带 checksum 的 TaskPlan event。旧计划和已提交结果只读；修复必须使用带 `base_plan_version` 的 `PlanPatch` 创建下一个版本。

## Research 动态变体

生产默认仍是 `build_paper_analysis_workflow_spec()`。显式选择 `dynamic_analysis` 或 `dynamic_task_plan` 选项时，entrypoint 才选择 `build_dynamic_paper_analysis_workflow_spec()`。该变体只替换 evidence 与 `verify_claims` 之间的 `dynamic_analysis_stage`，随后继续使用现有 claim、quality、reader、paper card 和 artifact publication 路径。

`dynamic_analysis_stage` 的控制面契约全部由 Harness 固定，LLM 只生成 task outline：

| 契约 | 固定引用或范围 |
| --- | --- |
| Policy | `research.analysis@1` |
| Capabilities | `research.analysis.structure`、`research.analysis.contribution`、`research.analysis.experiments` |
| Worker bindings | 每个 capability 精确绑定对应的 `@1` worker ref 和 `.worker-contract@1` contract ref |
| SubAgents | `research_analysis_structure`、`research_analysis_contribution`、`research_analysis_experiments` |
| Deterministic gates | `SummarySchemaGate@1`、`SummaryEvidenceCoverageGate@1`、`BenchmarkEvidenceLineageGate@1` |
| Aggregator | `research.analysis-aggregator@1` |

生产 composition 必须注入真实 `PlanCandidateBuilder`、完整且精确的 worker bindings、deterministic gate registry、result verifier、event/checkpoint/result store，以及可调用的 dynamic runner。TaskPlan store 必须是 durable store；`InMemoryTaskPlanStore` 只允许显式测试使用。任何必需能力缺失时，运行必须在 source、worker 和 publication 活动发生前 fail closed；接口层返回 `503 research_runtime_unavailable`，并列出缺少的 builder、worker bindings 或 store，不能安装 fake planner、fake worker 或内存 fallback。

### 启用与回滚

- 启用：保持默认配置不变，只对经过验证的请求显式设置 `options.dynamic_analysis=true` 或 `options.dynamic_task_plan=true`。启用前确认上述生产依赖已经组成并完成 replay、gate failure 和 publication-blocking 检查。
- 回滚：停止发送这两个 opt-in 选项，或将它们设为 `false`。新请求会立即回到 `build_paper_analysis_workflow_spec()` 的静态三分支分析路径；不需要修改已冻结 graph，也不迁移或重写既有 TaskPlan event、checkpoint 和 result。
- 恢复动态模式：修复依赖后先重放已有事件并核对 projection/replay checksum，再重新开放 opt-in。不得通过放宽 gate、替换为内存 store 或重跑 live planner 来恢复旧 run。

## 恢复与检查

恢复使用已接受的 plan、patch、result refs 和 TaskPlan projection 重建 ready order；不会重新调用 live planner 或 worker。operator inspection 只应暴露 policy/plan/task refs、状态、attempt、预算、失败原因和 replay checksum，不暴露 prompt、secret 或未授权 worker payload。
