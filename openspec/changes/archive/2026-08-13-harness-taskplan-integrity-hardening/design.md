## Context

TaskPlan 已经能够验证动态 candidate、生成不可变 Plan、应用有限 patch、调度任务并从 durable event stream replay。当前完整性缺口分布在 `validation.py`、`patches.py`、`stage.py`、`scheduler.py` 与 `replay.py`：patch 没有绑定 accepted policy 内容，task input reference 的解析和授权存在多套实现，patch DAG 深度缓存错误，halt event 写入失败会被吞掉，而 `reduce()` 丢失 patch evidence。

本变更必须保持 Harness 为唯一流程控制者，保持既有 Graph、Research 输出和 publication 路径不变，并兼容已有有效 Plan 历史的只读 replay。所有决策都必须由确定性代码完成，不引入 live planner、worker 或当前默认 policy 参与恢复。

## Goals / Non-Goals

**Goals:**

- 将 accepted Plan 同 exact `policy_ref` 和 canonical `policy_checksum` 绑定，拒绝 reference 或内容漂移。
- 对每个 input reference 独立执行 task dependency、policy allowlist 和 stage context 校验。
- 让 candidate validation、patch validation 和 scheduler 使用一致的 task reference 与 DAG 深度语义。
- 只有 durable `TASK_PLAN_HALTED` 写入成功后才返回普通受控失败；写入失败必须 fail closed。
- 让 `reduce()`、`replay()` 和 recovery 对带 patch 的同一历史产生相同 projection。
- 保持诊断稳定、有界、脱敏并可按低基数字段聚合。

**Non-Goals:**

- 不重写 HarnessGraphState、Graph compiler、Graph scheduler、event store 或 queue。
- 不修改 Research 的业务输出角色、publication 协议或外部 API。
- 不引入 compatibility layer、第二套 policy registry 或第二个 workflow authority。
- 不自动修复、补写或猜测缺失 evidence 的历史。

## Decisions

### 1. Accepted Plan 持久化 policy checksum

`ValidatedTaskPlan` 增加可序列化的 `policy_checksum`。新 Plan 与后续版本都必须携带当前 `TaskPlanPolicy.policy_checksum`；patch 同时比较 `policy_ref` 与 checksum，任一不一致都返回 `task_plan_policy_mismatch`，并且不得写入 patch proposal/rejection/acceptance 或新 projection。

旧 schema payload 没有 checksum 时，反序列化和 replay 保持可用，且旧 checksum projection 不改变；但是它不能通过 patch validator 继续产生新版本，因为该入口无法独立证明调用方提供的 policy 来自唯一不可变 registry。这个选择优先保证控制边界，不把 exact reference 当成内容证明。

备选方案是在 `TaskPlanStageRunner` 注入 registry 并只比较 exact ref。该方案仍让直接调用 `TaskPlanPatchValidator` 的入口缺少内容绑定，且把一个局部完整性条件变成调用顺序假设，因此不采用。

### 2. 共享 task reference parser

在 TaskPlan canonical 模块提供唯一的 task producer 解析函数，按顺序识别 `task://producer/path`、`task:producer/path`，并在给定已知 task ids 时保留现有 plain task-id 引用。validator、patch validator 和 scheduler 均调用该函数。

validator 对每个 input 独立分类。显式 task URI 指向未知 producer 时返回 `task_plan_unknown_dependency`；已知 producer 未出现在 `depends_on` 时返回 `task_plan_task_input_dependency_missing`；external ref 必须同时位于 policy allowlist 和当前 stage context，否则返回 `task_plan_input_reference_unavailable`。future-stage reference 继续保留独立诊断。

备选方案是在各调用点修正字符串切片。该方案无法保证四个入口长期保持同一 URI 语义，因此不采用。

### 3. 共享确定性 DAG 分析

新增纯 DAG 分析函数，输入为稳定的 `task_id -> depends_on` 映射，使用 DFS 三色状态和真实 depth memo，根节点深度为 0，时间复杂度为 O(V+E)。函数返回所有 task 的 depth，并以稳定 reason code 拒绝 self-loop、cycle、unknown dependency、无 root、不可达节点和超过 `max_depth` 的图。

candidate validator 将 typed DAG failure 转换为有界 diagnostic；patch validator 直接传播同一 typed failure；scheduler 的排序 depth 也复用同一计算结果。这样深度不再受 task 排序、共享依赖或重复访问影响。

### 4. Durable halt 是失败闭环提交

`TaskPlanStageRunner._halt()` 不再吞掉 store 异常。它先解析当前 Plan version，再写入 `TASK_PLAN_HALTED`；任一步骤失败都包装为 `task_plan_halt_persistence_failed`，details 只包含 run/stage、可用的 plan version、原 reason code 和 canonical diagnostic ref。异常从 `run()` 向调用方传播，因此不会被伪装成普通 `BLOCKED`/`FAILED`。

`run()` 只在 `_halt()` 成功后返回普通业务失败结果。由于 halt 在 dispatch/aggregate/verify/publication 的失败分支末端同步提交，写入不确定时不会执行任何后续动作。

### 5. Replay convenience API 接受完整 Plan history

`TaskPlanReplayReducer.reduce()` 的首个参数兼容单个 Plan 和 Plan iterable。单 Plan 保持既有初始版本用法；带 patch 的调用必须提供完整 Plan history 与 patch documents。`reduce()` 原样转发 `results`、`patches` 和 terminal-event policy 给 `replay()`，并返回其 projection。

replay 继续校验 patch document、base version、checksum、相邻 `PLAN_PATCH_ACCEPTED -> PLAN_ACCEPTED` 序列。RecoveryService 已调用 `replay()`，因此不新增另一套恢复逻辑。

### 6. 诊断与观测保持低基数

新增或规范化的完整性错误使用 PRD 定义的 `task_plan_*` reason code。错误 details 只记录 task id、policy ref/checksum、plan version、sequence 和 canonical diagnostic ref。现有 observability hook 按 reason code 计数，不把 raw run payload、prompt、secret 或 worker output 作为 metric label。

## Risks / Trade-offs

- [缺少 `policy_checksum` 的活动旧 Plan 无法继续 patch] -> 旧历史仍可 replay；需要继续执行时由受控 repair/quarantine 流程重新建立带 checksum 的 Plan，禁止静默升级。
- [共享 DAG helper 改变旧诊断名称] -> 只规范化本 PRD 列出的 reason code，并用 contract matrix 锁定 candidate/patch 的一致结果。
- [halt store 完全不可用时无法记录失败本身] -> 向调用方传播 typed persistence failure 并阻断后续动作；外层运行基础设施负责告警与人工处置，不能伪造 durable success。
- [`reduce()` 支持 iterable 使类型面扩大] -> 运行时显式区分 `ValidatedTaskPlan` 与 iterable，并继续让 `replay()` 执行完整版本校验。

## Migration Plan

1. 先增加 policy、mixed input、URI、deep DAG、halt store failure 和 patch replay 回归夹具。
2. 引入共享 reference/DAG helper，并切换 validator、patch validator 和 scheduler。
3. 写入新 Plan 的 `policy_checksum`，保留旧 payload 的只读 replay checksum。
4. 修改 halt 和 reduce 行为，运行 TaskPlan、Harness/workflow recovery、architecture 与 smoke 检查。
5. 部署时无需迁移 event store；发现缺少 checksum 或 patch evidence 的历史时 quarantine，不自动补写。

回滚代码不会删除已写入的 Plan/event evidence；如果旧运行时无法识别带 checksum 的 Plan，则必须先停止创建新动态 Plan，再回滚 reader，避免产生不可读历史。

## Open Questions

无。业务 workflow 是否启用动态 TaskPlan 仍由既有显式 workflow id/version 决定，不属于本变更。
