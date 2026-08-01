## Context

`harness-workflow-graph-runtime` 已将外层 Workflow 提升为编译、验证、冻结和 replay 的一等 Graph Runtime。每个 executable node 仍由 Harness 控制 `PLAN -> EXECUTE -> VERIFY`，Worker、LLM、Gate、Tool、Memory、Side Effect 和 Research 业务模块都不能成为路由权威。

当前 `PLAN` 的实现主要执行 framework gates。它没有一个可持久化的“候选任务计划”概念，也没有在固定业务 stage 内计算多个 ready task 的依赖调度。现有 `framework/workers/models/task.py` 是通用队列投影，支持状态、重试和 lease，但没有 DAG dependency、output role、worker capability、plan version 或 deterministic aggregation 契约，因此不能直接充当 TaskPlan 模型。

现有 `framework/harness/subagents` 已提供 `SubAgentSpec`、`SubAgentInvocation`、`SubAgentResult`、上下文隔离、tool allowlist、memory namespace、budget 和 transcript gates。`HarnessWorkerResult` 以及已有 SubAgent gates 还会拒绝 routing、quality、publication、memory、skill promotion 等控制字段。新设计必须复用这些边界，而不是建立另一套 subagent executor。

Research 当前的 paper analysis workflow 使用固定 `ParallelAll` 分析 structure、contribution 和 experiments，再进入 `verify_claims`、`quality_gate` 和 artifact publication。动态能力只允许替换该 analysis stage 的内部任务分解；source、document、RAG、evidence、claim verification、quality、report 和 publication 仍是固定的业务契约。

## Goals / Non-Goals

**Goals:**

- 建立可 canonical serialize、version、checksum、durably persist 和 replay 的 TaskPlan contract。
- 让 LLM 只生成 `PlanCandidate` 或 `PlanPatch` candidate，Harness 负责验证、接受、binding、调度、gate 和终止。
- 在固定 Graph 的 dynamic stage 内支持显式 dependency、bounded parallelism、稳定 ready order、output isolation 和 deterministic aggregation。
- 支持 task-level retry、基于旧版本的受控 patch、历史输出不可变和 stale result rejection。
- 复用既有 worker registry、SubAgent Runtime、tool/memory/budget gates、queue adapter、event store、checkpoint 和 replay ports。
- 为 Research analysis 提供 opt-in dynamic workflow variant，保持静态 workflow 和下游业务结果契约兼容。

**Non-Goals:**

- 运行中新增或删除外层 Graph node/edge，或允许 LLM 修改 `NormalizedHarnessGraph`。
- 跨全 Run 生成一个 LLM 总 DAG，或者让 dynamic task 跨越固定业务 stage boundary。
- 创建新的分布式 queue、event store、workflow executor 或平级 scheduler。
- 让 candidate 指定任意 Python callable、handler、worker version、tool authorization、quality/publication decision 或 memory write。
- 动态 publication、side effect、quality gate、compensation、infinite loop 或 nested dynamic plan。

## Decisions

### 1. 采用两层图，而不是动态修改外层 Graph

外层 Graph 在 `RUN_CREATED` 前编译并冻结。一个固定的 executable node 通过 pinned `TaskPlanPolicy` 声明自己是 dynamic stage。TaskPlan 是该 node instance 的 durable run data，包含 task definition、task instance、attempt、依赖和结果引用，但不会成为外层 Graph 的 node definition。

这样可以同时满足动态分解和 Graph replay：Graph checksum 始终稳定，TaskPlan version 单独递增；replay 读取已接受的 plan/patch，而不是重新要求 LLM 生成当时的图。

替代方案：将每个 LLM task 动态编译成 Graph node。该方案会破坏 Graph freeze、需要运行时修改 Graph schema/checksum，并将 LLM 候选提升为 routing authority，因此拒绝。

### 2. 使用 capability hint 与 pinned worker binding 分离

`PlanCandidate` 中的 `worker_capability` 只是业务能力提示，例如 `research.analysis.structure`。Harness 根据已注册的 capability registry 和 stage policy 解析唯一的 `worker_ref`、contract version、SubAgentSpec、tool policy 和 memory policy。candidate 不得携带实际 handler、callable 或 worker implementation。

这样允许 LLM 提出合理的任务类型，但实际路由仍由 Harness 和注册表决定。解析不唯一、版本不兼容或 capability 不在 allowlist 时，plan 在 dispatch 前拒绝。

替代方案：允许 LLM 直接返回 subagent id。该方案使 prompt 成为工具授权和路由入口，违反 Harness authority 与 SubAgent boundary，因此拒绝。

### 3. 使用不可变 plan version 和增量 PlanPatch

初始 candidate 被接受为 version 1。replan 以 `base_plan_version` 为乐观并发条件，只能影响 pending/not-started task；已完成、运行中和 committed result 都不可修改。Patch 通过与初始 candidate 相同的 schema、DAG、stage、binding、output 和 budget validator，再生成 version N+1 和新 checksum。

采用增量 patch 而非全量替换，是为了保留已经成功的非确定性 activity，避免 retry/replan 时重复调用 LLM、tool 或 subagent，也便于审计“为何增加了 replacement task”。旧版本仍通过 source refs 可回放。

### 4. TaskPlanScheduler 是 HarnessScheduler 的内部组件

对外仍只有一个 `HarnessScheduler`。它在 dynamic stage 的 Step `EXECUTE` phase 中委托给 `TaskPlanScheduler` 计算 ready task、预算 reservation 和 bounded dispatch。TaskPlanScheduler 不直接写 event、不直接调用 worker、不直接改变 Graph state；它返回结构化的 ready/dispatch decision，由 `HarnessControlPlane` 校验、durably commit 和应用。

validator、ready calculation、patch validation 和 aggregator 都应保持纯函数或 port-only 设计。这样可用内存 fixture 验证 cycle、依赖、排序、预算、冲突和 replay，不把网络、时钟或队列时序混入 deterministic decision。

### 5. 复用现有 queue Task 作为投影

每个 ready task 可以 materialize 成现有通用队列 `Task`，但只携带 `run_id`、`stage_id`、`plan_id`、`plan_version`、`task_id`、`task_instance_id` 和 attempt refs。DAG dependency、plan version、task lifecycle 和 result identity 的权威来源是 TaskPlan projection/event stream。

这样不需要把 `depends_on`、output role 或 plan patch 语义污染全局 worker queue，也可以继续复用已有 lease/reclaim/worker service。queue 重复投递和乱序结果通过 attempt、fencing、idempotency 和 plan checksum 拒绝或去重。

### 6. Dynamic stage 的 VERIFY 仍完全确定性

Task result 先经过现有 `HarnessWorkerResult`/`SubAgentResult` schema、context/tool/memory/budget gates，再经过 stage policy 允许的 output contract 和 deterministic gate。聚合器按稳定顺序生成 output refs。LLM 的 self-evaluation、quality score、route suggestion 或 publication suggestion 永远不是 gate input。

Research dynamic analysis 最终必须生成既有 `analysis_branch_refs`，然后走现有 `ClaimEvidenceGate@1`、`ResearchQualityGate@1`、reader payload、paper card 和 artifact publication 路径。

### 7. Durable event 与 replay 不新增真相来源

TaskPlan 复用 canonical `run:<run_id>` event stream、既有 checkpoint/replay ports 和 artifact/result refs。新增事件仅描述 candidate、plan version、task lifecycle、patch、aggregation 和 stage verification；完整 prompt/worker output 保存在既有受保护 store，通过 ref/checksum 关联。

状态 reducer 按 stream sequence 重建 plan/task projection。Replay 使用已记录的 candidate、accepted plan、patch 和 activity result，不调用 live LLM/worker/tool。缺失 schema、policy、binding、result 或 checksum 时 fail closed。

### 8. 先提供 Research opt-in variant

新增 `build_dynamic_paper_analysis_workflow_spec()`，workflow id/version 与静态版本区分。动态版本将固定 `ParallelAll` 替换为一个 `dynamic_analysis_stage`，但维持固定的前后置步骤和 `analysis_branch_refs` output key。默认入口继续使用静态 `build_paper_analysis_workflow_spec()`。

先采用独立 variant 而不是 feature flag 覆盖旧 spec，可以让 Graph checksum、golden fixture、replay 和回滚边界清晰，也不会让旧 run 在恢复时意外切换到动态计划。

## Risks / Trade-offs

- [Risk] LLM 生成过大的或低质量 DAG。 -> [Mitigation] policy 限制任务数、深度、并发、plan build budget、retry 和 replan；在任何 dispatch 前完成完整 preflight。
- [Risk] capability hint 被误当成实际路由。 -> [Mitigation] candidate schema 不接受 `worker_ref`/handler/callable，binding 只由 Harness registry 解析并 pinned。
- [Risk] 多 task 写同一 output role。 -> [Mitigation] role namespace 和 deterministic aggregator；无 merge contract 时 preflight 拒绝。
- [Risk] patch 覆盖历史结果或重复执行 activity。 -> [Mitigation] immutable task state、base version、attempt/fencing identity、durable result refs 和 stale result rejection。
- [Risk] queue projection 与 plan projection 漂移。 -> [Mitigation] plan event/projection 作为权威，queue 只负责执行投影；重复或丢失通过重建 ready state 处理。
- [Risk] Research 动态输出破坏既有 quality/publication contract。 -> [Mitigation] required output roles、`analysis_branch_refs`、现有 deterministic gates 和静态/动态 parity fixture。
- [Risk] 引入第二套调度真相来源。 -> [Mitigation] TaskPlanScheduler 只作为 HarnessScheduler 内部组件，Control Plane 是唯一 decision/apply boundary。
- [Risk] durable event 或 plan artifact 不可用。 -> [Mitigation] 在下一次 transition/dispatch 前 fail closed，保留 typed diagnostic，不使用内存降级。

## Migration Plan

1. 保留已有 `prd.md` 作为产品约束，先落地 proposal、design、specs 和 tasks，并通过 strict OpenSpec validation。
2. 实现 versioned TaskPlan models、policy registry、validator、纯 ready calculator、patch validator 和 in-memory fixtures。
3. 接入 TaskPlanStore、canonical event/checkpoint/replay、worker capability registry、SubAgent gates 和 queue projection。
4. 增加 Harness dynamic stage runner，并让 outer Step lifecycle 继续遵循 `PLAN -> EXECUTE -> VERIFY`。
5. 建立 Research dynamic workflow variant、deterministic aggregator 和 fake LLM/subagent E2E fixture。
6. 以静态 Research workflow 做 parity、replay、budget、failure 和 rollback 对比；动态 variant 默认保持 opt-in。
7. 在完成离线评估、crash-point drill、strict validation 和现有回归后，再决定是否扩大 dynamic stage 的使用范围。

回滚策略：在 dynamic workflow 写入新 run 之前，停用 dynamic workflow id 即可回到静态路径；已经接受 TaskPlan 的 run 不得压缩成旧的 `current_step_id`，必须由支持 TaskPlan 的 runtime 恢复、完成或明确 halt。

## Open Questions

无阻塞性问题。具体 Python 模块路径和 constructor 名称在实现阶段确定，但必须保留本设计中的两层图、Harness authority、immutable plan version、queue projection 和 Research output boundary。
