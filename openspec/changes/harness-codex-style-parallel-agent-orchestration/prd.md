# PRD: Codex 式动态规划与并行子 Agent 编排

## 1. 背景与问题

NewsRoom 已具备动态 `TaskPlan`、子 Agent 运行时、工具执行器和可回放事件流，但这些能力尚未组成一条统一的多 Agent 编排路径：

- `TaskPlanStageRunner` 虽能找出多个 ready task，当前仍可能在同步循环中逐个调用 worker。
- `AgentLoop` 的既有 `delegate` action 一次只委派一个 child，主 Agent 无法在同一轮规划中拆分并并行推进多个独立子任务。
- 子 Agent 的工具、预算、结果验证、重试、取消和恢复缺少以“一个逻辑委派组”为单位的统一 join 语义。

因此，主 Agent 不能以 Codex 式方式完成“提出受限计划 -> Harness 验证 -> 并行委派多个子 Agent -> 汇总可验证结果 -> 继续下一轮推理”的闭环。

## 2. 产品目标

在不改变 Harness 控制权边界的前提下，为 NewsRoom 提供受控、可观测、可恢复的动态 fan-out/fan-in 能力。

1. 主 Agent 可在一次 parent turn 中提出多个逻辑子任务候选，并获得一次安全投影后的 joined observation。
2. 当多个任务满足并发条件时，Harness 必须实际并行启动多个 child，而非仅返回多个 ready task 后串行执行。
3. 所有 child 的 worker 绑定、工具权限、预算、生命周期、结果验证、重试与恢复仍由 Harness 决定和记录。
4. 动态 Research analysis 作为首个业务 opt-in，在既有 evidence、quality 和 publication 边界内验证该能力。
5. 运行可以离线 replay，且 replay 不重新调用 live LLM、工具、worker、队列或 publication adapter。

## 3. 非目标

- 不允许 LLM 或 child Agent 直接决定 workflow routing、quality pass/fail、memory promotion、tool authorization 或 artifact publication。
- 不实现跨进程分布式 scheduler、自动扩缩容或 exactly-once transport。
- 不引入第二套 workflow engine、queue 或 child lifecycle。
- 不把动态 Research stage 变成可任意改写外层 Graph 的 agent。
- 不改变 static Research workflow 作为默认路径的事实。

## 4. 目标用户与使用场景

| 用户/系统 | 需求 | 预期结果 |
| --- | --- | --- |
| 主 Agent | 将一个复杂目标拆为独立子目标 | 提交受限候选，收到一次汇总后的 observation |
| Harness | 控制并行执行与风险边界 | 验证、授权、派发、验证和汇聚均可审计 |
| Research dynamic stage | 并行产出结构、贡献、实验分析 | 在角色齐全且通过既有 gate 后得到 `analysis_branch_refs` |
| 运维与审计 | 追踪并恢复异常运行 | 按 group/wave/attempt 查看事件、预算、结果和恢复证据 |

## 5. 核心产品概念

### 5.1 `PlanCandidate` 与 `delegate_batch`

主 Agent 只能生成候选，而不能直接生成已授权的执行请求。候选中的每个子任务必须包含稳定 task identity、逻辑目标、capability hint、输入 refs、输出角色和依赖 refs。候选中的并发提示只表达意图，不得扩大 policy 上限或授予权限。

`AgentLoop` 支持版本化 `delegate_batch`，但只负责解析和提交候选；它不得创建线程、选择具体 worker、授予工具、改变工作流状态或判断结果质量。

### 5.2 `DispatchGroup` 与 `DispatchWave`

| 概念 | 定义 | 生命周期职责 |
| --- | --- | --- |
| `DispatchGroup` | 一个 accepted plan version 的完整逻辑 join 范围 | 固定成员、required roles、总预算 envelope、join policy、aggregate 和 parent continuation |
| `DispatchWave` | 在当前 readiness 与 capacity 下实际启动的一批 task | 保存本轮 task、capacity/budget reservation、wave ordinal 和派发证据 |

一个 group 可以包含尚未 ready 的依赖任务。因依赖或容量不能立即执行的任务必须留在同一 group，后续以新的 wave 派发；不得隐式创建新的 join 范围。

## 6. 功能需求

### FR-1：受控动态规划

- Harness 必须验证 `PlanCandidate` 或 `delegate_batch`，包括依赖闭包、输入 refs、角色冲突、capability binding、工具/内存 allowlist、预算和 policy checksum。
- 候选不得包含或扩大 routing、quality、publication、memory promotion、worker implementation 或 tool authorization 等控制权。
- Planner 如需外部事实，只能走 `PlanningObservationRequest -> PlanningObservationReceipt -> PlanCandidate(source_observation_refs) -> candidate validation` 链路。
- Planning observation 默认拒绝；只有 policy 显式允许的只读工具可调用，并受工具次数、超时和预算限制。

### FR-2：真实并行委派

- 当两个或以上 ready task 独立、并发安全、完成 reservation、`effective_parallelism >= 2` 且未选择 `serial_fallback` 时，Harness 必须并发启动 child attempts。
- `effective_parallelism` 必须取 stage policy、capability capacity、`ChildAgentSupervisor` capacity 和可用 concurrency reservation 的最小值。
- 不得把 token 或 cost 数值直接当作 worker 数量。
- 只有 side-effect fence、有效 capacity 为 1，或 policy 明确启用 `serial_fallback` 时才能串行；每次串行降级必须记录 `DEGRADED_SERIAL` 和稳定原因。

### FR-3：group/wave admission 与预算

- Harness 必须在 child 启动前完成 durable group admission；admission 固定 group 成员、join scope、policy checksum 和总预算 envelope。
- Group admission 只锁定总预算上限，不重复消费逐任务预算。
- 每个 wave admission 必须原子预留 task identity、capacity 和标准化预算，并以 `RESERVED -> CONSUMED | RELEASED` 结算。
- 重试、取消、失败和恢复必须幂等地释放或消费 reservation，不能重复扣费或重复占用 capacity。

### FR-4：子 Agent 执行与工具边界

- 每个 admitted task 必须通过已有 `ChildAgentSupervisor` 创建独立 child attempt，并复用 lease、heartbeat、cancel、close 和 reclaim 语义。
- 每个 child 的 context、tool allowlist、memory namespace、预算、transcript 和 attempt identity 必须隔离。
- Child 工具调用复用 `ToolExecutor`/`ToolBatchExecutor`，并持久化归属于对应 child attempt 的 receipt 和 checksum。
- Child 输出只是候选证据，必须通过输出 schema、确定性 gate、工具/内存使用和 receipt 验证后才可成为 accepted result。

### FR-5：确定性 fan-in 与 parent observation

- Group join 和聚合必须依据 plan 中稳定 task order，而不能依赖 child 完成时间、线程顺序或队列顺序。
- 聚合必须验证 required roles、输出冲突、schema 和既有确定性 gate；所有 child terminal 不等于 group 成功。
- Parent 只能收到一个安全投影后的 joined observation，其中包括 group 状态、wave 摘要、稳定 task summaries、refs/checksums、gate diagnostics 和预算/恢复信息。
- `ParentObservationLimits` 必须限制 summaries 数量、summary 字节数、diagnostics、refs 和 observation 总字节数；超限内容只能提供 checksum-bound artifact ref。
- 禁止把 hidden prompt、sibling 私有 transcript、secret 或未经授权的原始工具 payload 返回给 parent。

### FR-6：失败、重试、replan 与恢复

- 每个 group 必须固定 `wait_all` 或 policy 注册的 `fail_fast` join policy，以及 group deadline、join wait 上限和 wave 上限。
- `wait_all` 必须等待所有必要任务到达终态后再聚合；Research dynamic 固定使用该策略。
- `fail_fast` 必须按“记录失败 -> 关闭 admission -> 取消 sibling -> 等待取消 receipt 或 lease expiry -> 隔离迟到 receipt -> 记录单一终态”执行。
- 达到 `max_task_attempts` 后只能进行 policy 明确允许的 replan。`ADD_REPLACEMENT_TASK` 只能替换 terminal failed task；`SKIP_PENDING_TASK` 和 `UPDATE_PENDING_DEPENDENCY` 只能作用于尚未进入任何 wave 的 task。
- 每次 replan 必须产生新的 plan version、`DispatchGroup` 和 correlation id；旧 group 的迟到结果不得写入新 projection。
- 缺少或损坏关键证据时必须 fail closed，不能猜测结果、静默切回 static workflow 或发布部分产物。

### FR-7：持久化、检查与 replay

- 运行必须记录 candidate、validation、group/wave admission、dispatch、child lifecycle、retry、join、aggregation、verification、cancel、reclaim 和 halt 等规范事件。
- Checkpoint 必须包含 plan/group/wave identity、policy checksum、task projection、reservation、attempt evidence、aggregate checksum 和 event sequence。
- 重启恢复应优先读取并校验已有 receipt、result artifact 和 projection，只补写缺失 transition；不得因为事件缺失重新执行已确认的 child 或外部副作用。
- Offline replay 必须只使用持久化的候选、计划、tool receipt、child receipt 和 aggregate evidence，不得调用 live dependencies。

## 7. 状态与责任边界

`DispatchGroup` 状态为：`PLANNED -> ADMITTED -> DISPATCHING -> RUNNING -> JOINING -> SUCCEEDED | FAILED | CANCELLED | INDETERMINATE | HALTED | SUPERSEDED`。`REPLAN_PENDING` 仅是 coordinator 内部非终态诊断，不得作为 parent 最终结果。

`DispatchWave` 状态为：`PLANNED -> ADMITTED -> DISPATCHING -> RUNNING -> TERMINAL`。

每个状态转换必须具有唯一 owner、规范事件名、幂等 key、允许后继状态和恢复行为。Harness 是唯一的 fan-out/fan-in coordinator；LLM 和 child Agent 只产生候选或受限结果。

## 8. Research 动态分析接入

Research dynamic analysis 是首个生产 opt-in，必须遵守以下边界：

- 仅消费已通过 gate 的 `document` 和 `evidence_pack` refs。
- 仅允许 policy 批准的 `analysis.structure`、`analysis.contribution`、`analysis.experiments` 及受控辅助角色。
- 每项结果仍须通过现有 Research deterministic gates。
- 只有 group join 后角色完整，才能确定性生成 `analysis_branch_refs`。
- 后续固定路径保持为 `verify_claims -> ResearchQualityGate@1 -> reader/card -> publication`。
- 不允许动态任务创建 publication、quality verdict、memory promotion 或 outer-Graph routing task。

## 9. 非功能需求

| 类别 | 要求 |
| --- | --- |
| 安全 | 默认拒绝未授权 capability、工具、内存、控制字段和 planning tool；隔离 sibling 私有上下文 |
| 一致性 | 聚合顺序稳定；结果 checksum 不受 child 完成顺序影响 |
| 可观测性 | 记录 requested/effective parallelism、queue/wait/run/join duration、预算、retry/replan、recovery 和 `DEGRADED_SERIAL` |
| 有界性 | 默认限制 task 数、wave 数、并行度、attempt、replan、group runtime、join wait、planning 工具次数和 observation 大小 |
| 兼容性 | 旧单 child `delegate` 经单 task group/wave compatibility adapter 继续可用 |
| 生产性 | 通用 `AgentLoop` orchestration port 必须走真实 composition；fake worker、fake LLM 和 in-memory store 仅限测试 |

## 10. 验收标准

1. 通用 `AgentLoop` 能在一个 parent turn 提交至少两个独立 child proposals，并经 production `AgentOrchestrationPort` 获得一个 joined observation。
2. 在满足并发条件时，集成测试能证明至少两个 child 的执行时间真实重叠，而非串行调用。
3. capacity 不足时，任务以稳定 READY 顺序分入后续 wave，并在同一 `DispatchGroup` 内完成 join。
4. 子 Agent 无法选择 worker、扩大工具权限、修改路由、发布产物、提升 memory 或影响 sibling 私有上下文。
5. partial failure、retry exhaustion、replan、cancel、lease expiry 和 crash recovery 都产生受控、可审计的 group outcome。
6. replay 可重建相同 plan/group/wave/task/aggregate projection，并证明没有 live LLM、工具、worker、队列或 publication 调用。
7. Research dynamic 在所有 required role 和既有 gate 成功后才生成 `analysis_branch_refs`；失败时不进入 quality 或 publication。
8. static Research workflow 仍保持默认路径，dynamic Research 仅在 feature flag 和生产依赖校验全部通过后 opt-in。

## 11. 交付与上线顺序

1. 先完成 group/wave schema、policy、状态机、validator、reservation 和 replay 合同。
2. 接入 Harness coordinator 与真实 `ChildAgentSupervisor`，验证 multi-wave join。
3. 完成通用 `AgentLoop` 的 `delegate_batch`、生产端口、parent observation、feature flag 和兼容 adapter。
4. 在 Research dynamic 中接入并行角色任务，运行 publication regression 与 offline replay 验证。
5. 仅在通用 AgentLoop smoke、Research parity、telemetry 和 replay evidence 全部通过后启用动态 Research opt-in；static 路径继续保留为默认。

## 12. 关联 OpenSpec 工件

- `proposal.md`：变更动机、影响面与完成定义。
- `design.md`：架构决策、状态机、预算/容量合同、恢复与上线策略。
- `specs/`：Harness、TaskPlan、AgentLoop 和 Research 的可验证行为要求。
- `tasks.md`：实施任务与验证清单。
