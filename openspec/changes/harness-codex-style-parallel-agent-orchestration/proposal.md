## Why

当前 NewsRoom 已经具备 `PlanCandidate`、DAG readiness、`SubAgentRuntime`、`ChildAgentSupervisor` 和固定 Graph `ParallelAll` 等基础能力，但这些能力还没有组成一个完整的 Codex 式闭环。动态 `TaskPlanStageRunner` 能选出多个 ready task，却仍在同一个同步循环中逐个调用 worker；`AgentLoop` 的 delegation 也一次只等待一个子 Agent，因此主 Agent 不能动态拆解任务、同时派发多个子 Agent、等待结果并继续基于汇总结果工作。

本变更将把已有的规划、能力绑定、并发生命周期、工具运行时和 durable transcript 接通，形成受 Harness 控制的动态 fan-out/fan-in 编排能力，同时保持 `LLM as worker, Harness as control plane`、`PLAN -> EXECUTE -> VERIFY`、确定性 gate、预算上限和可恢复事件历史不变。

## What Changes

- 新增统一的 Codex 式动态 Agent orchestration contract：主 Agent 生成受限的 `PlanCandidate` 或批量 delegation candidate，Harness 验证后创建不可变执行计划。
- 新增 bounded fan-out/fan-in executor：一次从 DAG 中选出多个 ready task，创建覆盖逻辑 join 范围的 `DispatchGroup`，再按 capacity 切分为一个或多个 `DispatchWave`，预留预算和 capacity 后并行 dispatch 到多个已注册的 child Agent，等待并关联每个结果，再执行逐任务验证和确定性聚合。
- 将动态 `TaskPlanStageRunner` 从当前逐任务同步调用改造成可插拔的并行执行路径；当任务不能安全并行、有效 capacity 为 1 或 policy 明确允许降级时，才按确定性顺序退化为串行执行。
- 将 `ChildAgentSupervisor` 接入动态 TaskPlan 主路径，复用其 capacity、parent budget、lease、heartbeat、cancel、terminal receipt 和 recovery 语义；不得创建第二套 child lifecycle。
- 扩展 `AgentLoop` delegation contract，使主 Agent 可以在一个受限 candidate 中提出多个 delegation，并在 Harness group join 后一次性收到带 task identity、状态、输出引用和错误诊断的结果包；本变更正式交付通用 `AgentLoop` 生产编排端口，Research dynamic 是首个生产业务接入点。
- 让 child Agent 通过现有 `AgentRunner`/`ToolExecutor` 使用显式白名单工具；工具调用、memory 操作、预算消耗和 transcript receipt 必须归属于对应 child attempt，planner 和 child 均不得获得 workflow routing、quality、publication 或 memory promotion authority。
- 增加 durable group/wave lifecycle、join、partial failure、retry、replan、cancel 和 crash recovery 事件，并保证 replay 不重新调用 LLM、Tool、SubAgent 或外部副作用。
- 为 Research dynamic analysis 接入并行 fan-out/fan-in，保留 `document`、`evidence_pack`、三个 required output roles、既有 deterministic gates、`verify_claims`、quality gate 和 publication boundary。
- 增加配置和观测字段：group id、wave ids、task instance ids、parallelism、queue/wait duration、child status、join policy、result refs、budget usage、recovery outcome 和 `DEGRADED_SERIAL` reason。
- 按 PRD 固定 durable candidate dedup、统一 `RefAuthority`、多 capability/resource pool 原子 reservation，以及 spawn intent/receipt/reconcile 协议；上游失败必须传播为终态 `BLOCKED_DEPENDENCY`。
- 将 parent submission 与 terminal observation 分离：bounded wait 到期保存 `PENDING` receipt，通过 durable continuation 恢复同一 parent turn，不能启动第二次推理或重复追加 observation。
- 区分在线 recovery 与离线 replay，并按 G1 Contract、G2 Coordinator、G3 AgentLoop、G4 Research、G5 Release 分别验收；feature flag enable 是独立 release gate。
- **BREAKING**：动态 TaskPlan executor 的生产语义从“选择多个但逐个调用”改为“在满足真实并行条件时并行执行并显式 group join”；现有单任务 worker contract 保持兼容，但自定义 executor 必须实现新的 wave/attempt result contract，或由明确的 serial adapter 包装。

## Capabilities

### New Capabilities

- `harness-parallel-agent-orchestration`: 定义主 Agent 动态计划、批量 delegation、bounded fan-out/fan-in、child result join、并行预算、生命周期、恢复和观察性契约。

### Modified Capabilities

- `harness-task-plan`: 将 dynamic TaskPlan 的 ready-task 执行从隐式串行改为受策略控制的 group/wave dispatch，并定义 group join、部分失败和结果聚合行为。
- `agent-loop-runtime`: 允许 parent Agent 产生受限的多 child delegation candidate，并在 Harness 统一 join 后继续 loop；保留 AgentLoop 仅生成候选动作，不拥有路由和质量权威。
- `research-dynamic-analysis-stage`: 动态 Research stage 使用统一并行 orchestration，多个分析 child 可以并行执行，结果经逐任务 gate 和 deterministic aggregation 后进入固定下游 Graph。

## Impact

- Framework：`framework/harness/task_plan`、`framework/harness/subagents`、`framework/harness/control_plane`、`framework/agent/loop`、`framework/agent/subagents` 和相关 event/projection/replay contracts。
- Runtime composition：Research dynamic factory、`ResolvedSubAgentTaskAdapter`、`SubAgentRuntime`、`ChildAgentSupervisor`、`ToolExecutor`/`ToolBatchExecutor` 的连接方式和生产依赖校验。
- Durable storage：新增 group/wave/join/child-attempt 事件、projection、receipt 索引和 replay schema；现有 run、Graph、TaskPlan、SubAgent transcript 和 artifact identity 必须保持可验证关联。
- API/inspection：run inspection、trace、transcript 和 metrics 暴露 group/wave/task/child 状态，但不暴露 hidden prompt、未经授权的 raw context 或控制字段。
- Tests：需要覆盖候选验证、并行上限、依赖就绪、fan-out/fan-in、工具边界、partial failure、retry/replan、cancel/lease、crash recovery、replay equivalence、serial fallback 和 Research publication regression。
- Dependencies：复用现有 Graph compiler/control plane、TaskPlan validator/scheduler/store、SubAgent supervisor/runtime、ToolRuntime、durable event/replay 和 side-effect authority；ToolRuntime 不新增独立能力，只由 child-attempt adapter 传递 attribution、budget 和 receipt identity；不新增通用工作流引擎、第二套 queue、第二套 child lifecycle 或绕过 Harness 的直连 executor。

## Definition of Done

- 通用 `AgentLoop` 能在一个 parent turn 提交至少两个独立 child proposal，并通过 production `AgentOrchestrationPort` 返回一次 joined observation。
- 当两个或以上任务独立、通过并发资格检查、`effective_parallelism >= 2` 且未启用 `serial_fallback` 时，Harness 必须真实并发启动 child；串行只能是显式、可观测的例外。
- `DispatchGroup` 覆盖完整逻辑 join 范围，`DispatchWave` 只表示一次受 capacity 限制的物理派发；多 wave 结果必须在同一 group 内完成 role-complete aggregation。
- group 状态、retry、replan、cancel、lease、reservation 和 recovery 均有有界状态转换、唯一事件 owner 和可回放证据。
- child 完成顺序变化不改变 aggregate/observation checksum；offline replay 不调用 live dependency。在线 recovery 只可执行已审计的 supervisor status/reconcile 和 policy 允许的新 attempt，不调用 live LLM 重新规划，也不重复已确认或不确定的非幂等副作用。
- 旧单 child `delegate` 保持兼容，Research dynamic 在固定 quality/publication boundary 内作为首个 production opt-in 接入。
- PRD、design、spec、tasks、schema、默认值和测试 oracle 保持一致；G1-G4 的实现证据与 G5 的开启、遥测、恢复及回滚演练证据分别记录，不以 strict validation 或 feature flag 代替行为验收。
