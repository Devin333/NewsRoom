# PRD: Codex 式动态规划与并行子 Agent 编排

| 项目 | 内容 |
| --- | --- |
| OpenSpec change | `harness-codex-style-parallel-agent-orchestration` |
| 文档状态 | Proposed，作为该 change 的产品需求入口 |
| 适用范围 | 通用 `AgentLoop` 编排能力，以及首个业务 opt-in：Research dynamic analysis |
| 当前基线 | 已存在动态 `TaskPlan`、`ChildAgentSupervisor`、`SubAgentRuntime`、工具执行器、durable event 和 replay 能力；当前路径仍可能逐任务串行执行 |
| 目标边界 | 在 Harness 控制面补齐受限 fan-out/fan-in，不改变 static Research 默认路径和固定质量/发布边界 |
| 规范关系 | 本文定义产品需求；`proposal.md` 定义变更意图，`design.md` 定义架构决策，`specs/` 定义可验证行为，`tasks.md` 定义实施工作 |

## 1. 背景与问题

NewsRoom 已经可以生成动态 `TaskPlan`、计算 DAG readiness、运行受控 child、保存事件和检查点，但这些能力还没有组成一条完整的并行编排路径：

- `TaskPlanStageRunner` 可以发现多个 ready task，但执行层仍可能在同步循环中逐个调用 worker。
- `AgentLoop` 的旧 `delegate` 只委派一个 child，parent 无法在同一轮提交多个独立子任务并等待一个确定性汇总。
- child 的工具、预算、attempt、取消、恢复、结果验证和 group join 没有统一的逻辑委派范围。
- 崩溃恢复需要区分“只重建历史”和“受策略允许继续执行”，现有文档没有明确两者的 live dependency 边界。

因此，系统无法稳定完成以下闭环：

```text
parent candidate -> Harness validation -> group admission
-> capacity-limited waves -> isolated child attempts
-> deterministic verification -> one joined observation
-> parent continuation
```

本 PRD 只把 LLM/child 视为候选生产者。Harness 仍是唯一的计划接受、授权、调度、验证、重试、恢复、路由和发布控制者。

## 2. 产品目标

1. parent `AgentLoop` 可以在一个 action candidate 中提交多个逻辑 child task，并通过真实 `AgentOrchestrationPort` 获得一个安全投影后的 group outcome。
2. 当并发条件满足时，Harness 必须实际重叠运行多个 child attempt，而不是只返回多个 ready task 后串行执行。
3. 一个 `DispatchGroup` 固定完整逻辑 join 范围；capacity、依赖和重试只改变 `DispatchWave`，不得隐式创建新的 join 范围。
4. child 的 capability、工具、memory、预算、lease、receipt、gate、取消和恢复全部由 Harness 决定并持久化。
5. 在线 crash recovery 能在不重复已确认工作或不确定的非幂等副作用的前提下重建或受控继续；offline replay 永远不调用 live dependency。
6. Research dynamic analysis 作为首个 production opt-in，只在既有 evidence、quality 和 publication 边界内使用并行能力。
7. 旧单 child `delegate` 通过明确的 compatibility adapter 保持当前 `AgentLoopResult` 语义。

## 3. 非目标与范围边界

- 不允许 LLM/child 决定 workflow routing、quality pass/fail、tool authorization、memory promotion 或 artifact publication。
- 不实现跨进程分布式 scheduler、持久队列、自动扩缩容、跨 run 公平调度或跨进程 exactly-once transport。
- 不引入第二套 workflow engine、queue 或 child lifecycle；必须复用现有 Harness、`ChildAgentSupervisor`、`SubAgentRuntime` 和 tool adapter。
- 不允许 dynamic Research 改写外层 Graph、跳过 source/evidence、quality、reader/card 或 publication 步骤。
- 不把本变更的 feature flag enable 视为代码实现完成；启用属于独立 release gate。

## 4. 不可破坏的系统不变量

以下不变量优先于性能和便利性，任何实现或配置都不能覆盖：

1. `PLAN -> EXECUTE -> VERIFY` 必须有界；`max_task_attempts`、`max_replans`、`max_waves`、group deadline 和 parent turn budget 必须阻止无限循环。
2. group admission、wave admission 和 child spawn 的身份、预算和权限必须可追溯到同一个 run/stage/plan。
3. child 输出是候选证据。只有身份、receipt、schema、工具/memory 使用和 deterministic gate 均通过，才可成为 accepted result。
4. aggregate 顺序、summary 投影、checksum 和 replay 结果不能受 child 完成时间、线程顺序或队列顺序影响。
5. 已确认的 receipt 不得重放；无法确认的非幂等副作用必须进入 `INDETERMINATE` 或 `HALTED`。
6. parent 只接收 security-projected observation；原始 hidden prompt、sibling private transcript、secret 和未授权 tool payload 不得跨边界。
7. static Research 仍是默认路径；dynamic Research 失败时不得静默切回 static 或发布部分产物。

## 5. 核心概念

### 5.1 Candidate、plan 与 dedup

`PlanCandidate`/`delegate_batch` 是 parent 或 planner 产生的候选，不是已授权执行请求。Harness 接受后生成不可变 `ValidatedTaskPlan`，再创建 group/wave。

候选重投必须使用以下 durable 去重键：

```text
candidate_dedup_key =
run_id + stage_id + parent_turn_id + action_correlation_id
```

并记录 `candidate_checksum`：

- 相同 `candidate_dedup_key` + 相同 checksum：返回原 plan/group/submission 或 terminal observation，不创建第二个 group。
- 相同 `candidate_dedup_key` + 不同 checksum：返回 `CANDIDATE_IDEMPOTENCY_CONFLICT`，不得执行任一新 payload。
- 原 group 已 terminal：只返回已有 outcome；不得重新 spawn 或重新发布副作用。
- 新 plan version 的 replan 必须使用新的 `action_correlation_id` 和新的 dedup key。

`group_id` 必须由 accepted plan identity 和 dedup key 的稳定 hash 生成，重启和重放保持不变；不能由线程、时间或随机数生成。

### 5.2 `DispatchGroup` 与 `DispatchWave`

| 对象 | 定义 | 不变量 |
| --- | --- | --- |
| `DispatchGroup` | 一个 accepted plan version 的完整逻辑 join 范围 | 成员、required roles、join policy、预算 envelope、policy checksum 固定；后续 wave 复用同一个 group |
| `DispatchWave` | 在当前 readiness、capacity 和 side-effect 约束下的一次物理派发 | 只包含本次实际 admission 的 task；wave ordinal 在 group 内唯一、递增 |
| `TaskAttempt` | 一个 logical task 的一次物理执行 | 新 attempt 必须有新 attempt id、operation key 和 receipt；不得复用失败 attempt identity |
| `ParentObservation` | group outcome 的安全投影 | 只投影 deterministic accepted evidence 和 typed diagnostics，不成为控制通道 |

group 可以包含尚未 ready 的 task。依赖、容量或 backpressure 只让 task 留在 durable `PENDING`/`READY`，不得改变 group join scope。

### 5.3 `RefAuthority` 与上下文边界

所有 `input_refs`、result refs、planning observation refs 和 memory namespace 都必须经过统一的 `RefAuthority` 校验。校验维度至少包括 `run_id`、`stage_id`、tenant/owner、读写权限、artifact type、source checksum 和 policy allowlist。

跨 run、跨 stage 或跨 tenant 的 ref 默认拒绝；允许共享时必须由 pinned policy 声明共享范围和只读权限。candidate 不能自行声明共享范围，child 不能访问 sibling private refs。

## 6. Candidate 输入契约

### 6.1 `delegate_batch`

每个 logical task 至少包含：

| 字段 | 规则 |
| --- | --- |
| `logical_task_id` | 在同一 plan 内唯一；不能由执行时间生成 |
| `objective` | 非空且受长度限制；不得包含 policy、routing、quality 或 publication 控制指令 |
| `capability_hint` | 只能映射到已注册、版本兼容且 allowlisted 的 binding |
| `input_refs` | 必须由 `RefAuthority` 解析并通过 owner/stage/tenant 校验 |
| `output_roles` | 必须属于 stage role registry；重复 role 必须声明 deterministic merge contract |
| `depends_on` | 必须形成 DAG；不得引用未来 plan、sibling private history 或未存在的 ref |
| `side_effect_class` | 只能由 Harness 根据 binding/policy 解析；candidate 不能升权 |
| `correlation_id` | 继承 parent action correlation；重放保持不变 |

candidate 可以携带 token/cost 估算和 advisory parallelism，但这些字段不能改变 worker 数量、预算上限、权限或质量判断。

### 6.2 禁止字段

以下字段在 candidate 中出现即拒绝，不能靠忽略字段实现兼容：

```text
concrete_worker_ref
queue_or_thread_selection
tool_grant
memory_grant
budget_increase
routing_decision
quality_verdict
publication_decision
memory_promotion
outer_graph_mutation
```

Harness 对每个 candidate 必须返回 `accepted`、`rejected`、`deferred` 或 `halted`，并附稳定 reason code。结构不完整时不得猜测默认值。

### 6.3 Planning Observation

planner 需要外部只读事实时，必须经过以下因果链：

```text
PlanningObservationRequest
-> PlanningObservationReceipt
-> PlanCandidate(source_observation_refs)
-> candidate validation
```

planning observation 默认关闭。开启时只能调用 pinned policy allowlist 中的只读工具，并且必须绑定 `run_id`、`stage_id`、`planner_turn_id`、独立的 planning correlation id、policy checksum、planning budget 和 timeout。receipt 必须先 durable 落盘，candidate 只能引用 immutable receipt ref，不得内联未验证的 raw tool payload。

工具失败、超时、超预算、结构非法、checksum 不匹配或跨 run/stage 的 observation ref，必须返回稳定诊断并拒绝 candidate；不得由 planner 猜测缺失事实。planning tool 不能修改 routing、quality、publication、policy 或 memory promotion。

## 7. Group 状态、Wave 状态与依赖状态

### 7.1 Group 状态机

`REPLAN_PENDING` 是 canonical group state，不是只写在诊断里的隐式状态：

```text
PLANNED
  -> ADMITTED
  -> DISPATCHING
  -> RUNNING
  -> DISPATCHING       # 仍有 READY task，创建下一 wave
  -> RUNNING
  -> JOINING
  -> SUCCEEDED | FAILED | CANCELLED | INDETERMINATE | HALTED

JOINING -> REPLAN_PENDING
REPLAN_PENDING -> SUPERSEDED   # 新 plan/group 已 accepted
REPLAN_PENDING -> FAILED | HALTED
```

终态为 `SUCCEEDED`、`FAILED`、`CANCELLED`、`INDETERMINATE`、`HALTED`、`SUPERSEDED`。`REPLAN_PENDING` 不向 parent 作为最终 outcome 暴露，但必须进入 event/checkpoint/replay。

同一 group 只允许一个 active wave admission transaction。wave terminal 后由 coordinator 事件驱动下一次 readiness/admission；不得由 child 自行创建 wave。

### 7.2 Wave 与 Task 状态

wave 状态为：

```text
PLANNED -> ADMITTED -> DISPATCHING -> RUNNING -> TERMINAL
```

`TERMINAL` 必须带 typed `terminal_outcome`：

```text
SUCCEEDED | PARTIAL_FAILED | FAILED | CANCELLED
INDETERMINATE | RECLAIMED | DEADLINE_EXCEEDED
```

task 至少使用：`PENDING`、`READY`、`BLOCKED_DEPENDENCY`、`ADMITTED`、`RUNNING`、`SUCCEEDED`、`FAILED`、`CANCELLED`、`INDETERMINATE`、`QUARANTINED`。`BLOCKED_DEPENDENCY` 是未进入任何 wave 的终态，不是无限等待状态。

### 7.3 上游失败传播

当 predecessor 达到不可恢复 terminal failure，coordinator 必须按稳定 DAG 顺序传播：

1. 将尚未 admission 的直接和传递后继标记为 `BLOCKED_DEPENDENCY`，记录 `TASK_BLOCKED_UPSTREAM_FAILURE`。
2. 释放这些 task 尚未消费的 reservation；不得创建 child 或等待其永远变成 READY。
3. `wait_all` 等待传播产生的终态后，返回 `DEPENDENCY_BLOCKED`/`REQUIRED_ROLE_MISSING` typed partial failure。
4. 若 policy 允许 replacement replan，旧 group 进入 `REPLAN_PENDING`；新 plan 必须重新验证受影响的依赖 closure。旧 group 的 blocked task 不得被直接改写为新 plan 的 task。

## 8. Admission、Spawn 与崩溃恢复协议

外部 child spawn 无法和 durable event 原子提交，因此采用 intent/receipt/reconcile 协议。每个 attempt 使用唯一 `spawn_operation_key`：

```text
spawn_operation_key = group_id + wave_id + task_instance_id + attempt
```

提交顺序固定为：

1. 事务或等价 durable batch 写入 `TASK_WAVE_ADMITTED`、reservation ledger 和 `TASK_ATTEMPT_SPAWN_INTENT`。
2. coordinator 将 intent 交给 `ChildAgentSupervisor`；supervisor 以 `spawn_operation_key` 幂等处理。
3. supervisor 返回 `SPAWN_CONFIRMED`（含 child id/lease）或 `SPAWN_UNKNOWN`；两者都必须持久化 receipt。
4. 只有所有 selected task 的 spawn 状态已知且对应 child 可追踪时，才写 `TASK_WAVE_DISPATCHED` 并进入 `RUNNING`。
5. spawn batch 部分成功时按 task 独立 reconcile；已 confirmed 的 task 不重复 spawn，unknown task 只能按 recovery policy 处理。

恢复时：

- 事件、intent 和 receipt 都存在：验证 checksum，补缺失 transition，不重复 spawn。
- intent 存在但没有 receipt：读取 supervisor 的 operation status；若状态仍 unknown，进入 `SPAWN_UNKNOWN`，不能直接假设未启动。
- child 已启动但 dispatch event 缺失：以 supervisor receipt 为事实补写 dispatch event，不创建新 child。
- reservation 存在但 admission event 缺失：以同一 idempotency key 补写 admission 或标记 ledger conflict；不得再次扣费。
- 任意 identity、operation key 或 checksum 冲突：进入 `HALTED`，保留审计证据。

在线 recovery 可以调用 supervisor 的只读 status/termination/reconcile 接口，这些调用必须有独立 `RECOVERY_*` event 和审计记录。它不能调用 live LLM 重新规划，也不能重放已确认 receipt。

## 9. Capacity、Wave Packing 与副作用

### 9.1 异构 capability capacity

capacity 不是单一全局标量，而是一个按 capability/resource pool 分开的向量。每个 task 有 demand：

```text
{ capability_pool: quantity, resource_conflict_key: key, side_effect_class: class }
```

wave admission 使用确定性的 first-fit packing：按 plan stable task order 扫描 task；只有当该 task 所需的全部 capability pool、并发 slot 和资源 key 都能原子 reservation 时才加入当前 wave；不能 reservation 的 task 留在 READY，继续检查后续 task，并记录 `CAPACITY_NOT_AVAILABLE`。同一 wave 的 packing 结果和每个 pool reservation 都进入 wave checksum。

因此：

- `effective_parallelism` 是当前 wave 实际 admitted task 数量与 policy 上限的共同约束，不再用一个 capability 标量代表所有能力池。
- 不允许部分 reservation；多资源 reservation 必须 all-or-nothing。
- capability pool capacity、supervisor capacity、stage limit 和 available concurrency reservation 都必须参与 admission。
- 缺失或过期的 capacity 信息 fail closed，不默认为无限容量。

### 9.2 副作用冲突

默认冲突规则如下：

| side effect | 同 `resource_conflict_key` | 不同 key |
| --- | --- | --- |
| `READ_ONLY` | 可并发 | 可并发 |
| `EXTERNAL_IDEMPOTENT` | 需 policy 明确允许；默认串行 | 可并发，但每项必须有 idempotency/receipt |
| `MUTATING_SERIAL` | 串行 | 可并发，除非 policy 将 capability 声明为全局串行 |
| `FENCED_MUTATION` | 必须持有该 key 的 deterministic fence | 按各自 fence 并发 |

`FENCED_MUTATION` 的 fence 必须有 owner、fencing generation、TTL、续租、释放和恢复事件。fence 丢失、generation 冲突或 TTL 无法确认时，attempt 进入 `INDETERMINATE`/`HALTED`，不得自动重试。

## 10. Budget Reservation

预算使用版本化 `BudgetReservation`，至少包含 `token_limit`、`time_limit_ms`、`tool_call_limit`、可选 `cost_limit`、owner scope、reservation key、parent allocation、attempt allocation 和 ledger version。

不变量：

```text
consumed + released + outstanding_reserved <= group_envelope
```

- group admission 只 pin 总 envelope，不消费 attempt 资源。
- wave admission 对每个 selected task 原子 reservation；失败时整项释放，不留下半个 reservation。
- attempt 超过任一硬上限时停止执行并写 `BUDGET_EXCEEDED`；已消费部分记 `CONSUMED`，未消费部分 `RELEASED`。
- retry 必须使用新 attempt reservation，不能把旧 attempt 的剩余余额重复使用。
- cancel、reclaim、crash reconcile 必须按 reservation key 幂等结算。
- replan 的新 group 只能继承 policy 明确允许复用的预算和 sibling evidence；不能把旧 group 的未结算余额直接当作新 group 可用余额。

## 11. Child 执行、Receipt 与结果验证

每个 admitted task 必须通过已注册的 `ChildAgentSupervisor` 和 `SubAgentRuntime`/Harness-owned adapter 执行，并获得独立的：

- context 与输入 refs；
- capability binding、tool allowlist 和 memory namespace；
- budget snapshot、lease、heartbeat 和 cancel handle；
- transcript ref/checksum、candidate output ref/checksum；
- terminal receipt、attempt id 和 `spawn_operation_key`。

缺失、损坏、重复、跨 run 或 identity 不匹配的 receipt 必须导致 reject 或 `INDETERMINATE`。非 subagent task 不得伪造 transcript，但所有声明为 subagent 的结果都必须有可读、可校验 receipt。

结果只有在以下条件全部通过后才能提交 `TaskResultRecord(accepted)`：

1. plan/group/wave/task/attempt/binding identity 匹配；
2. 输出 schema 和 output role 合法；
3. input refs、tool receipt、memory 使用和 budget ledger 可验证；
4. 该 task 声明的 deterministic gate 通过；
5. transcript/output/terminal receipt 的 checksum 一致。

完整 attempt history 必须保留 rejected、failed、cancelled、indeterminate、reclaimed 和 quarantined 记录。`results_for()` 可以只返回 accepted projection，但 canonical `result_history_for()` 必须返回完整历史，供 retry、replay 和 recovery 使用。

## 12. Fan-In、Aggregate 与 ParentObservation

### 12.1 Deterministic join

coordinator 只在 join policy 条件满足、deadline 到达或 group 被关闭后进入 `JOINING`。aggregator 按 plan stable task order 读取所有 wave 的 accepted result，并检查：

- required role 是否完整；
- role 是否重复且存在 deterministic merge contract；
- output schema、gate evidence、input refs 和 checksum 是否有效；
- `BLOCKED_DEPENDENCY`、failed、cancelled、indeterminate task 是否使 required role 缺失。

所有 task terminal 不代表 group success。只有 required roles、aggregate gate 和 checksum 全部通过，才写一个 aggregate ref/checksum 和 `TASK_GROUP_JOINED`。

### 12.2 Summary 的确定性来源

Parent observation 的 summary 只能来自已持久化、已通过 gate 的结构化 result fields、typed status 和 deterministic diagnostics。禁止在 projection 或 replay 中调用 LLM 重新摘要。

排序、字段选择、脱敏、UTF-8 截断、`summary_truncated` 标记和 projection version 都必须固定，并纳入 observation checksum。LLM 原始输出只能以 checksum-bound artifact ref 暴露。

### 12.3 ParentObservation 限制

canonical schema 使用 `max_observation_bytes`，默认值为：

```text
max_task_summaries = 8
max_summary_bytes = 2048
max_diagnostics = 16
max_refs = 16
max_observation_bytes = 16384
```

超限时保留 group state、terminal outcome、核心 checksum 和 continuation 信息，详细内容收敛为 artifact ref；不得截断成会改变含义的半条控制信息。

### 12.4 Parent continuation 语义

`AgentOrchestrationPort` 采用“提交结果”和“parent terminal observation”分离的合同：

1. `submit(candidate)` 返回 durable `submission_id`、`group_id`、dedup 状态和 bounded wait 信息。
2. 正常情况下，port 在 bounded wait 内等待 group terminal，并向 parent 追加一次 terminal `ParentObservation`。
3. capacity 等待、在线 recovery 或 join 超时不能在 parent conversation 中伪装成成功。bounded wait 到期时返回 `PENDING` submission receipt，不启动新的 parent reasoning turn。
4. coordinator 完成后，Harness 通过 durable continuation 唤醒同一个 parent turn；按 `observation_id + observation_version` 幂等追加一次 terminal observation。
5. 中间 progress 只供 inspection/metrics，不作为 parent 的 child 原文或控制指令。
6. group terminal 后重复读取只返回同一 observation checksum，不重复追加、不重新执行。

## 13. Failure、Retry、Replan 与 Join Policy

每个 group 必须 pin：`join_policy`、`group_deadline`、`max_join_wait_seconds`、`max_waves`、`max_task_attempts`、`max_replans` 和 cancellation policy。

### 13.1 `wait_all`

Research dynamic 固定使用 `wait_all`。它必须等待所有必要 task，包括因上游失败而被传播为 `BLOCKED_DEPENDENCY` 的 task，到达明确终态后再聚合。required role 缺失时返回 typed partial failure，不产生成功 aggregate。

### 13.2 `fail_fast`

只有 policy registry 允许的通用场景才能使用：

```text
record failure
-> close group admission
-> request sibling cancel
-> wait cancel receipt or lease expiry
-> quarantine late receipts
-> write one terminal group outcome
```

未确认的 sibling 不能直接重派；不确定副作用按 pinned policy 进入 `INDETERMINATE`/`HALTED`。

### 13.3 Retry 与 Replan

- retry 只在 retryable reason code 和剩余 attempt budget 同时满足时发生，并使用新 attempt identity。
- retry exhaustion 之后只能执行 policy 注册的 `PlanPatch`：`ADD_REPLACEMENT_TASK` 只能针对 terminal failed logical task；`SKIP_PENDING_TASK` 和 `UPDATE_PENDING_DEPENDENCY` 只能针对尚未进入任何 wave 的 task。
- 每次 replan 创建新 plan version、new group、new correlation id；旧 group 在新 group accepted 后转 `SUPERSEDED`。
- 旧 group 的迟到 receipt 只能进入 quarantine/audit，不能写新 projection。
- `max_waves` 统计初次 dispatch 和 retry waves；达到上限时未 admission task 按稳定顺序标记 `WAVE_LIMIT_EXCEEDED`/`BLOCKED_DEPENDENCY`，group 进入 typed failure 或 halt，不得静默饿死。

### 13.4 稳定 reason code

至少使用以下 typed reason code：

```text
PLAN_SCHEMA_INVALID
PLAN_DEPENDENCY_INVALID
CANDIDATE_IDEMPOTENCY_CONFLICT
REF_UNAUTHORIZED
CAPABILITY_UNAVAILABLE
CAPACITY_NOT_AVAILABLE
CONCURRENCY_NOT_SAFE
BUDGET_EXCEEDED
SPAWN_UNKNOWN
CHILD_TIMEOUT
RESULT_SCHEMA_INVALID
DEPENDENCY_BLOCKED
REQUIRED_ROLE_MISSING
OUTPUT_CONFLICT
GROUP_DEADLINE_EXCEEDED
JOIN_TIMEOUT
WAVE_LIMIT_EXCEEDED
REPLAN_EXHAUSTED
CANCEL_UNCONFIRMED
REPLAY_LIVE_DEPENDENCY
DEGRADED_SERIAL
```

## 14. Online Recovery 与 Offline Replay

### 14.1 Online crash reconciliation

在线 recovery 是执行控制操作，允许以下 live 调用：

- 读取 supervisor/lease/termination status；
- 读取 durable artifact、receipt、reservation ledger 和 event stream；
- 在 receipt 未确认、side-effect policy 允许、idempotency key 有效且仍在 deadline 内时创建受控新 attempt。

任何 recovery live 调用必须写 `RECOVERY_STATUS_READ`、`RECOVERY_RECONCILED`、`RECOVERY_RETRY_ADMITTED` 或 `RECOVERY_HALTED` 事件。不能调用 live LLM 重新规划，也不能重放已确认或不确定的非幂等副作用。

### 14.2 Offline replay

offline replay 是纯历史重建，必须只读取持久化 candidate、plan、patch、events、receipt、result history、aggregate 和 checkpoint。它严禁调用 live LLM、source、RAG、tool、worker、supervisor、queue 或 publication adapter。

测试必须使用一旦被调用就失败的 spy/fake live adapters，并验证：

- plan/group/wave/task 状态一致；
- complete attempt history、quarantine 和 reservation ledger 可重建；
- aggregate/observation checksum 一致；
- live call counter 为零。

## 15. Durable Events、Checkpoint 与 Inspection

至少记录以下规范事件：

```text
CANDIDATE_ACCEPTED / CANDIDATE_REJECTED
TASK_GROUP_ADMITTED
TASK_WAVE_ADMITTED
TASK_ATTEMPT_SPAWN_INTENT
TASK_ATTEMPT_SPAWN_CONFIRMED / TASK_ATTEMPT_SPAWN_UNKNOWN
TASK_WAVE_DISPATCHED / TASK_WAVE_COMPLETED
TASK_BLOCKED_UPSTREAM_FAILURE
TASK_RESULT_ACCEPTED / TASK_RESULT_REJECTED
TASK_GROUP_JOIN_WAITING / TASK_GROUP_JOINED
TASK_GROUP_REPLAN_PENDING / TASK_GROUP_SUPERSEDED
TASK_ATTEMPT_RETRY / TASK_ATTEMPT_CANCEL_REQUESTED
TASK_ATTEMPT_RECLAIMED / TASK_RECEIPT_QUARANTINED
TASK_GROUP_FAILED / TASK_GROUP_CANCELLED
TASK_GROUP_INDETERMINATE / TASK_GROUP_HALTED
RECOVERY_STATUS_READ / RECOVERY_RECONCILED / RECOVERY_HALTED
```

每个 event 至少携带 `run_id`、`stage_id`、`plan_id`、`plan_version`、`group_id`、可选 `wave_id`、`task_instance_id`、attempt、correlation id、idempotency key 和 event sequence。缺少这些关联信息的 event 不能作为 replay 控制事实。

Checkpoint 至少包含 graph/plan checksum、group/wave identity、join policy、task projection、完整 result history 索引、spawn intent/receipt、reservation ledger、aggregate/observation checksum 和 stream sequence。

Inspection 必须能回答：

1. group/wave 是否 admission，当前哪些 task ready/running/blocked；
2. 每个 reservation 是否 `RESERVED`、`CONSUMED` 或 `RELEASED`；
3. 每个 outcome 由哪些 receipt、gate 和 checksum 支撑；
4. 是否发生 serial fallback、recovery retry、quarantine 或 indeterminate。

日志、metrics、diagnostics 和 replay artifact 必须执行现有 redaction，不能记录 raw prompt、secret 或未授权 payload。

## 16. Research Dynamic Analysis 接入

Research dynamic 是首个 production opt-in，必须满足：

- 只消费已经通过 deterministic gate 的 `document` 和 `evidence_pack` refs；
- 只允许 `analysis.structure`、`analysis.contribution`、`analysis.experiments` 及 policy 注册的只读 helper role；
- 三个 required role 通过各自 Research gate 后，才能进入 group aggregate；
- aggregate 成功后才写 `analysis_branch_refs`；
- 下游固定顺序仍为 `verify_claims -> ResearchQualityGate@1 -> reader/card -> publication`；
- dynamic task 不得创建 quality verdict、publication、memory promotion 或 outer-Graph routing task；
- 任一 required role、gate、binding、receipt 或 evidence 失败时，不得生成成功 `analysis_branch_refs`，也不得进入 quality/publication。

### 16.1 Research parity 定义

“parity”表示 contract parity，不要求 dynamic 与 static 生成逐字相同的 LLM 文本。使用固定 golden inputs 比较以下不可变语义：

- required role 集合和 role completeness；
- `analysis_branch_refs` 的结构、引用归属和 checksum；
- `verify_claims` 接收的 evidence refs 和 gate evidence；
- quality verdict、reader/card/artifact 的字段契约和 publication boundary；
- failure run 不产生 downstream success refs。

允许变化的字段必须显式列出，例如 wall-clock duration、wave id、attempt id 和 trace timing；不允许变化的字段必须字段级断言。parity fixture、允许差异和失败阈值必须进入测试工件，不能只写“回归通过”。

## 17. AgentLoop 生产组合与兼容性

### 17.1 Generic AgentLoop

生产 composition 必须解析真实的 `AgentOrchestrationPort`、coordinator、worker registry、`ChildAgentSupervisor`、durable run/event store、artifact verifier、authorized tool ports 和 parent observation policy。缺少任一 required binding 时返回稳定 unavailable/deferred/halted，不得安装 ad hoc executor 或 fake fallback。

feature flag 必须独立区分：

```text
FEATURE_DISABLED
DEPENDENCY_UNAVAILABLE
DEGRADED_SERIAL
ENABLED_PARALLEL
```

### 17.2 Legacy single delegate

旧 `delegate` 通过 one-task group/one-wave adapter 执行，保留：

- parent identity、tool allowlist、memory boundary、budget、transcript 和 result gate；
- 现有 `AgentLoopResult` 的 success/error/stop_reason/diagnostics/trace projection；
- 旧 concrete child ref 到 policy-pinned capability 的唯一映射。

映射缺失、歧义、版本不兼容或无 policy 时，返回稳定 typed diagnostic，不选择任意 worker。兼容验收必须使用旧调用方 golden fixtures，断言字段、错误、取消和 recovery 语义，而不是只断言返回字符串。

## 18. 非功能需求

| 类别 | 要求 |
| --- | --- |
| 一致性 | group/wave/task/result/observation checksum 对完成顺序稳定；reservation ledger 满足不变量 |
| 安全 | RefAuthority、tool allowlist、memory namespace、tenant scope 和 redaction 默认拒绝越权 |
| 可恢复 | online recovery 与 offline replay 分离；attempt history、spawn intent、receipt 和 quarantine 可重建 |
| 有界性 | task、wave、parallelism、attempt、replan、runtime、join wait、planning calls、observation size 均有硬上限 |
| 可观测性 | 按 run/stage/group/wave/capability/outcome 关联 admission、wait、run、join、budget、recovery 和 degradation |
| 性能 | 只在相同 provider/model/input/budget/tool/gate 配置下比较 overlap 和 wall-clock；不预设脱离 workload 的加速倍数 |
| 兼容性 | legacy single delegate 保持现有结果 projection；dynamic Research 不改变 static 默认 |
| 生产性 | fake LLM、fake worker、in-memory store 和 fixture artifact adapter 只能出现在显式测试 composition |

## 19. 默认 Policy 与参数确认

除非 stage policy 明确覆盖，否则使用以下 bounded defaults：

```text
max_tasks_per_group = 8
max_waves = 16
max_parallelism = 3
max_task_attempts = 2
max_replans = 2
max_group_runtime_seconds = 900
max_join_wait_seconds = 300
max_planning_tool_calls = 3
planning_timeout_seconds = 30

ParentObservationLimits:
  max_task_summaries = 8
  max_summary_bytes = 2048
  max_diagnostics = 16
  max_refs = 16
  max_observation_bytes = 16384
```

`max_observation_bytes` 是唯一 canonical 字段名；不得在同一 contract 中同时使用 `max_total_bytes` 和 `max_observation_bytes`。PRD、design、spec、代码和测试必须同步上述默认值。

实现前必须确认 stage-specific 的 capability pool、resource conflict、预算单位、join policy、serial fallback、fence policy 和 Research role limits。缺少必需 capacity、join、budget、ref 或 binding policy 时 fail closed；只有 observation limit 缺失时才使用安全默认值。

## 20. 验收标准与证据矩阵

### 20.1 必须通过的行为

1. 相同 parent turn/candidate 重投复用原 group；冲突 payload 被 `CANDIDATE_IDEMPOTENCY_CONFLICT` 拒绝。
2. 两个独立 read-only child 的 monotonic start/end 区间真实重叠，且不超过 capability pool 和 supervisor capacity。
3. 三个 task、capacity=2 时形成两个 wave，同一 group 只 join 一次，READY 顺序稳定。
4. A -> B 中 A retry exhaustion 后，B 及其传递后继进入 `BLOCKED_DEPENDENCY`，释放 reservation，group 不无限等待。
5. 异构 capability 的 wave packing 按 stable order 完成 all-or-nothing 多池 reservation，wave checksum 包含 pool 证据。
6. admission、spawn intent、spawn receipt、dispatch event 任意位置 crash 后，不重复已确认 child/tool/side effect。
7. `wait_all` 的 required task 失败返回 typed partial failure，不生成成功 aggregate 或 downstream ref。
8. `fail_fast` 先关闭 admission、取消 sibling、等待 receipt/lease，再 quarantine 迟到 receipt。
9. retry exhaustion + legal replan 创建新 plan/group；旧 group 结果不能写新 projection。
10. online recovery 只进行有审计的 status/reconcile/受控 retry；offline replay 对 live dependency 的调用计数为零。
11. ParentObservation summary、排序、脱敏和 truncation 在 replay 中保持 checksum 一致。
12. legacy single delegate 的旧结果字段、错误、取消和诊断语义保持兼容。
13. Research dynamic 只有三个 required role、既有 gates、`verify_claims` 和 quality gate 全通过后才生成 `analysis_branch_refs`。

### 20.2 证据矩阵

| 场景 | 必须提供的证据 | 通过条件 |
| --- | --- | --- |
| Candidate dedup | durable dedup records、checksum conflict tests | 相同请求复用，冲突请求不执行 |
| 并发 overlap | monotonic timestamps、barrier supervisor、dispatch events | eligible child 运行区间重叠，capacity 不超卖 |
| 多 capability packing | pool reservation ledger、wave checksum | all-or-nothing reservation，稳定选取 |
| 多 wave | group/wave history、READY projection | 同一 group、多 wave、一次 join |
| 上游失败 | A exhausted + B pending fixture、block events | B 进入 `BLOCKED_DEPENDENCY`，无 child、无泄漏 |
| Spawn crash | intent/receipt/reconcile fixture、调用计数 | 不重复 spawn、receipt identity 不变 |
| 结果完整性 | rejected/failed/indeterminate/quarantine history | accepted projection 不采纳损坏结果 |
| Parent redaction | schema/size/redaction tests | 无 hidden/private/raw payload，checksum 稳定 |
| 在线 recovery | supervisor status spy、recovery events | 只读核对或 policy 允许的新 attempt，禁止未知非幂等重放 |
| Offline replay | failing live adapters、golden history | projection/checksum 一致，live call=0 |
| Research parity | 固定 golden inputs、字段级比较 | role/gate/downstream contract 满足，允许差异显式化 |
| Legacy compatibility | 旧 `AgentLoopResult` fixtures | 字段、错误、取消、trace projection 保持 |

## 21. 交付拆分与上线门禁

### 21.1 独立交付 gate

| Gate | 范围 | 退出条件 |
| --- | --- | --- |
| G1 Contract | schema、状态机、dedup、ref authority、budget、event、replay history | strict OpenSpec、契约测试、checksum/ledger 不变量通过 |
| G2 Coordinator | admission/spawn protocol、capacity packing、多 wave、join、dependency block | overlap、spawn crash、multi-capability、upstream failure 通过 |
| G3 AgentLoop | production port、parent continuation、observation、legacy adapter | real composition、redaction、compatibility、bounded pending 通过 |
| G4 Research | dynamic role dispatch、Research gates、parity、publication regression | golden fixture、static default、failure boundary、offline replay 通过 |
| G5 Release | feature flag、telemetry、alert、rollback 和 recovery rehearsal | 运行中 group、serial fallback、recovery 和回滚演练通过 |

### 21.2 分阶段发布

1. 阶段 0：schema、validator、event、reservation 和 replay 默认关闭，只运行 fixture/replay。
2. 阶段 1：G2 使用 fake supervisor 验证真实 overlap、packing、join 和 recovery。
3. 阶段 2：G3 在受控测试 run 开启 generic AgentLoop，缺依赖返回稳定诊断。
4. 阶段 3：G4 只对 allowlisted Research dynamic run 开启，static 仍是默认。
5. 阶段 4：根据 latency、error、budget、replay 和隔离数据扩大范围，不自动切换默认路径。

### 21.3 回滚

- 新请求可关闭 feature flag 或切换显式 `SerialTaskExecutorAdapter`；不能删除 group、receipt、event 或 result history。
- 运行中的 group 继续使用创建时 pinned policy 完成 recovery、cancel 或 halt；不得中途改变 join policy、budget 或 capability binding。
- 回滚后旧 single-child path 可以接收新请求，但旧 group 的 inspection/replay 必须保持可用。
- 回滚记录必须包含影响的 run/stage/capability、最后 accepted plan version、未结算 reservation 和原因。

## 22. 责任边界与关联工件

| 角色 | 负责 | 不得负责 |
| --- | --- | --- |
| Parent `AgentLoop` | 生成 candidate、引用 observation、继续下一轮候选 | 选 worker、授予权限、修改 group、发布 artifact |
| Planner/LLM | 生成 task objective、依赖和输出角色候选 | 决定 routing、quality、authorization、memory 或 publication |
| Harness validator | schema、DAG、ref、capability、budget、side-effect 和 policy 验证 | 采纳未验证输出 |
| Group/Wave coordinator | admission、packing、dispatch、join、retry、replan、cancel、reclaim、terminal state | 绕过 gate、改写已接受 plan |
| `ChildAgentSupervisor` | spawn、lease、heartbeat、cancel、close、reconcile | 改变 outer Graph 或 quality/publication |
| Child worker | 在隔离上下文中产生 candidate evidence | 访问 sibling private context、扩权、宣布成功 |
| Deterministic gate/aggregator | result validation、role completeness、aggregate/checksum | 按完成时间覆盖冲突、采纳 raw text |
| 运维/审计 | 查看 projection、暂停 flag、导出 replay、执行 recovery | 直接修改运行中的 plan/receipt |

关联工件：

- `proposal.md`：动机、影响面、breaking boundary 和 Definition of Done。
- `design.md`：架构决策、状态机、预算/capacity 合同、迁移策略；必须同步本 PRD 的 recovery、capacity 和默认值。
- `specs/`：Harness、TaskPlan、AgentLoop 和 Research 的 SHALL/MUST 行为；必须拆分 offline replay 与 online recovery。
- `tasks.md`：按 G1-G5 拆分实施任务；feature flag enable 属于 G5 release gate，不是普通实现 task。

本 PRD 的实现前置条件是：PRD、design、spec、tasks、schema、代码默认值和测试 oracle 完成同一轮一致性更新。OpenSpec 严格校验通过只代表工件结构合法，不能替代上述行为证据。
