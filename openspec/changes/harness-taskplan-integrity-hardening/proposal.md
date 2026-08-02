## Why

TaskPlan 已具备动态计划、patch、持久化与 replay 能力，但当前实现允许 patch 在未绑定的 policy 下验证、对混合输入执行非逐项授权、低估 patch DAG 深度、吞掉 halt 持久化失败，并在 reduce 入口丢失 patch evidence。这些缺口会破坏 Harness 的单一控制权、预算边界和 durable recovery 语义，必须在动态 TaskPlan 扩大使用前关闭。

## What Changes

- 将 accepted Plan 与 exact policy identity 绑定，patch 只能使用原 Plan 的 policy；policy 内容漂移必须 fail closed。
- 统一 task: 与 task:// 引用解析，并对每个 task/external input reference 独立执行 dependency、policy 和 stage-context 校验。
- 使用确定性的 O(V+E) DAG 深度算法校验初始 candidate 与 patch 后 Plan，拒绝遍历顺序相关的深度绕过。
- 将 TASK_PLAN_HALTED 定义为失败闭环的必要 durable evidence；halt 写入失败不得伪装为普通业务失败。
- 对齐 TaskPlanReplayReducer.reduce、replay 与 TaskPlanRecoveryService，使带 patch 的历史在所有公开入口产生相同 projection。
- 增加 policy mismatch、mixed input、task URI、deep patch DAG、halt persistence failure 和 patch replay parity 回归夹具。
- 补充稳定 reason code、脱敏诊断和低基数观测指标要求。

## Capabilities

### New Capabilities
- `harness-taskplan-integrity`: 定义 TaskPlan policy identity、逐项输入授权、有界 DAG、patch 版本完整性与 replay parity 契约。

### Modified Capabilities
- `harness-runtime`: 强化 controlled failure 和 durable replay 要求，只有失败/停止事件持久化成功后才能把 Harness 管理的阶段视为已安全 halt。

## Impact

- Affected code: `framework/harness/task_plan/validation.py`, `patches.py`, `stage.py`, `replay.py`，以及共享的 TaskPlan canonical reference helpers。
- Affected tests: `tests/framework/harness/task_plan`、Harness/workflow runtime recovery tests 和相关 architecture tests。
- Affected contracts: TaskPlan policy/plan identity、input reference parsing、`TASK_PLAN_HALTED` durable semantics、patch replay behavior。
- No new infrastructure dependency, queue authority, event store, business API, UI, or compatibility layer is introduced.
- Existing static Research workflow、Graph runtime 与 artifact publication 路径保持不变。
