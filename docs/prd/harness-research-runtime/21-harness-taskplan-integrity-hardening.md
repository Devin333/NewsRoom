# 阶段 21：Harness TaskPlan 完整性与失败闭环 PRD

> 文档状态：DRAFT
>
> 版本：v1.0
>
> 优先级：P1
>
> 范围：framework/harness/task_plan、TaskPlan 与 Harness Control Plane 的集成边界
>
> 来源：2026-08-02 Harness 框架层代码审查

## 1. 一句话结论

TaskPlan 已具备计划、调度、结果验证、持久化和 replay 的主体能力，但仍存在几处会破坏 Harness 权限边界或 durable 语义的缺口。本 PRD 要求把这些缺口收敛为可验证的完整性契约：策略不可替换、输入引用逐项授权、patch DAG 深度有界、halt 结果必须持久化、replay 必须复现带 patch 的历史。

## 2. 背景与问题

Harness 的职责不是接受一个“看起来合理”的动态计划，而是保证每个动态阶段都经过：

    candidate -> deterministic validation -> pinned plan -> bounded execution
             -> durable result -> deterministic verification -> replayable outcome

本次审查确认了以下问题：

| 编号 | 问题 | 影响 |
|---|---|---|
| P1-1 | TaskPlanStageRunner.apply_patch 未确认 supplied policy 与当前 Plan 的 policy_ref 一致 | patch 可在另一套 capability、预算或 gate 规则下验证，产生策略漂移 |
| P1-2 | _halt 吞掉持久化异常 | 调用方收到失败结果，但 durable stream 没有 TASK_PLAN_HALTED，恢复可能重新执行不完整阶段 |
| P2-1 | 输入 allowlist 以任务级条件判断，混入一个 task: 引用即可跳过其他输入的授权检查 | 未授权输入可能绕过 validator 边界；task:// 解析也不一致 |
| P2-2 | TaskPlanPatchValidator._validate_dag 对已访问节点返回 0 | 长链或共享依赖的深度被低估，patch 可超过 max_depth |
| P2-3 | TaskPlanReplayReducer.reduce 接收 patches 却未传给 replay | 带 patch 的历史在 convenience API 下无法恢复 |

## 3. 产品目标

### G1. 锁定策略权威

一个已接受的 Plan 只能由它声明的、不可变的 policy 继续演进。任何 policy reference、policy checksum 或 policy 内容不一致，都必须在 patch 接受前 fail closed。

### G2. 完整校验数据流

每一个 input_ref 都必须独立判断：

1. 是否是合法的 TaskPlan task reference；
2. 若是 task reference，是否指向当前 plan 中的 task；
3. 是否已显式声明对应 dependency；
4. 若不是 task reference，是否同时满足 policy allowlist 与当前 stage context。

### G3. 保证动态计划有界

初始计划与 patch 后计划必须使用同一套 DAG 语义计算 cycle、未知依赖、可达性和最大深度，不能因为遍历顺序而得到不同结果。

### G4. 保证失败可恢复

业务失败和 durable 写入失败必须区分。只有 TASK_PLAN_HALTED 成功写入后，阶段才可被视为已 halt；否则必须返回持久化不确定状态并阻止继续执行。

### G5. 保证 replay API 等价

reduce、replay 和 TaskPlanRecoveryService 对 candidate、plan、patch、result、event 的处理必须语义一致。带 patch 的历史不能只在某一个入口可恢复。

## 4. 非目标

- 不重写 HarnessGraphState、Graph compiler 或 Graph scheduler。
- 不新增第二套 event store、queue authority 或 policy registry。
- 不改变 TaskPlan 的业务输出角色、Research dynamic analysis contract 或现有 publication 路径。
- 不允许 LLM、worker 或 queue 直接决定 policy、routing、quality、halt 或 publication。
- 不在本 PRD 中实现 UI、运维控制台或新的外部 API。

## 5. 用户与使用场景

### 5.1 Framework maintainer

维护者需要在不修改业务 workflow 的情况下修复 validator、patch、replay 和 store 边界，并能通过单元测试验证每一条完整性规则。

### 5.2 Operator / reviewer

当阶段因输入、策略、预算、存储或 replay 失败时，操作人员需要看到稳定的 reason code、plan version、policy ref、event sequence 和恢复建议，而不是一个没有 durable 记录的通用失败。

### 5.3 Runtime integrator

集成方可以传入 policy、candidate、patch 和 durable store，但不能通过调用顺序或缺省参数替换已接受计划的策略身份。

## 6. 功能需求

### FR-1：Policy identity binding

1. apply_patch 必须验证 current.policy_ref == request.policy.exact_ref。
2. TaskPlanPatchValidator.apply 必须验证 plan.policy_ref == policy.exact_ref，否则返回稳定错误码 task_plan_policy_mismatch。
3. policy 内容应通过不可变 registry 或 policy checksum 固定；同一 exact reference 不得解析到多个内容不同的 policy。
4. 新 Plan 必须保留并验证原 Plan 的 policy identity，不得以“旧 reference + 新规则”静默接受。
5. policy mismatch 发生时，不得写入 PLAN_PATCH_ACCEPTED、新 Plan 或新的 task projection。

### FR-2：Per-reference input authorization

1. validator 必须先规范化 task: 与 task:// 两种 task reference，规范化结果只能有一个实现。
2. 每个 task reference 必须解析到当前 candidate 的 task，并且 producer 必须出现在 depends_on。
3. 每个非 task reference 必须同时存在于 policy.allowed_input_refs 和 stage context；只满足其中一项不得通过。
4. 一个任务包含 task reference，不得改变同一任务其他 input reference 的授权结果。
5. 未知 task reference、未来 stage reference、缺失 dependency 和未授权 context 必须分别返回可区分的 reason code。

### FR-3：Deterministic bounded DAG

1. 初始 candidate 与 patch 后 Plan 必须共享同一套深度计算语义。
2. DAG 计算必须缓存真实 depth；重复访问节点必须返回已计算 depth，而不是 0。
3. 必须拒绝 cycle、self-loop、unknown dependency、unreachable task 和超过 max_depth 的计划。
4. 深度检查结果不能依赖 task id 排序或依赖图遍历顺序。
5. patch 通过后，旧版本的 completed task、result ref 和 plan checksum 必须保持不变。

### FR-4：Durable halt semantics

1. TASK_PLAN_HALTED 是阶段失败闭环的必要 durable evidence。
2. 写入 halt event 失败时，不得静默返回普通 BLOCKED 或 FAILED 结果。
3. 持久化异常必须使用稳定错误码 task_plan_halt_persistence_failed，并包含 run、stage、plan version 和原始失败 reason code 的脱敏引用。
4. durable halt 未确认前，runtime 不得继续 dispatch、aggregate、verify 或 publication。
5. recovery 遇到“执行失败但没有 halt event”的历史时，必须返回待人工处理或受控重试状态，不得假设阶段已安全结束。

### FR-5：Replay parity

1. TaskPlanReplayReducer.reduce 必须把 patches、results 和 terminal-event policy 传递给 replay。
2. reduce 与 replay 对同一历史必须产生一致的 projection checksum。
3. 带 PLAN_PATCH_ACCEPTED -> PLAN_ACCEPTED 的历史必须能通过 reduce、replay 和 TaskPlanRecoveryService 恢复。
4. replay 缺少 patch document、patch base version 或 patch checksum 时必须 fail closed。
5. replay 仍不得调用 live planner、worker、queue、tool、memory 或当前 policy default。

### FR-6：Diagnostics and inspection

必须为以下情况提供稳定、可聚合的 reason code：

    task_plan_policy_mismatch
    task_plan_input_reference_unavailable
    task_plan_task_input_dependency_missing
    task_plan_unknown_dependency
    task_plan_depth_exceeded
    task_plan_halt_persistence_failed
    task_plan_replay_patch_missing
    task_plan_replay_patch_mismatch

诊断中只能保留 reference、checksum、sequence、task id 和脱敏摘要，不得写入 raw prompt、secret、tenant-private payload 或完整 worker output。

## 7. 关键验收场景

### AC-1：策略替换被拒绝

给定一个 policy_ref 为 research.analysis@1 的已接受 Plan，当 patch 请求携带另一 exact reference 或内容不一致的 policy 时，系统拒绝 patch，Plan、projection 和 event stream 均不变化。

### AC-2：混合输入逐项校验

给定任务同时包含一个合法 task dependency 和一个不在 policy allowlist 中的外部 ref，validator 必须拒绝该任务，并且不能因为存在 task dependency 而放宽外部 ref 检查。

### AC-3：Task URI 兼容解析

给定 task:producer/output 与 task://producer/output 两种合法表示，validator、scheduler、patch validator 和 replay 必须解析为同一 producer identity。

### AC-4：深度上限不可绕过

给定 A -> B -> C 且 max_depth=1，初始计划和 patch 后计划都必须拒绝，并返回 task_plan_depth_exceeded。

### AC-5：halt 写入失败 fail closed

给定 worker 或 aggregation 已失败但 TASK_PLAN_HALTED 写入抛出存储异常，调用方收到持久化失败结果；不会看到成功的 halt 投影，也不会继续 dispatch 或 publication。

### AC-6：patch replay 等价

给定包含一个 accepted patch、一个 replacement task 和一个 accepted result 的 event history，reduce 与 replay 必须得到相同的 plan version、task projection 和 checksum。

### AC-7：recovery 不调用 live worker

给定上述历史在进程重启后恢复，recovery 只读取 durable candidate、patch、result 和 event evidence，live worker/planner 调用次数必须为零。

## 8. 数据与接口约束

建议在现有 Plan/Policy contract 中补充或明确以下字段，不新增平行模型：

| 字段 | 用途 |
|---|---|
| policy_ref | exact policy identity，必须与 accepted Plan 一致 |
| policy_checksum | 防止同一 reference 的内容漂移 |
| plan_checksum | 绑定 patch base 与 replay projection |
| reason_code | 机器可读的失败分类 |
| diagnostic_ref | 指向脱敏诊断 artifact 或摘要 |
| sequence | durable event 的单调序列 |

所有新增字段必须进入 canonical serialization 和 checksum projection；不得依赖内存字段恢复历史。

## 9. 兼容性与迁移

### 9.1 已有有效历史

已有 policy ref、Plan、patch、result 和 event history 在 schema 不变时必须继续 replay。若旧历史没有 policy checksum，只能在 registry 能证明 exact ref 唯一且内容不可变时兼容读取。

### 9.2 不完整历史

缺少 patch document、halt event 或 policy identity 的历史不得自动补写成功事件。系统应生成 quarantine/repair diagnostic，并保持原始 evidence 不变。

### 9.3 部署顺序

    新增回归测试 -> validator/patch/replay 修复
    -> durable halt 失败语义修复 -> recovery 验证
    -> 观测指标与告警 -> opt-in 集成验证

本 PRD 不要求切换现有 Research workflow；动态分析启用仍由既有显式 workflow id/version 控制。

## 10. 非功能需求

### NFR-1：确定性

相同 Plan、Policy、Patch、Projection 和 Event prefix 必须产生相同 validation result、ready order、projection checksum 和 replay result。

### NFR-2：安全边界

未授权 capability、tool、memory、input、gate、output role 和 policy 不得通过 patch 或 replay 入口进入 accepted Plan。

### NFR-3：可靠性

任何 durable commit 失败都必须阻止后续不可逆操作；不得以 in-memory success 替代 durable evidence。

### NFR-4：可观测性

至少记录 validation rejection、policy mismatch、depth rejection、halt persistence failure、replay mismatch 和 recovery quarantine 的计数与 reason code。

### NFR-5：性能

DAG 深度计算应为 O(V+E)；replay 不得因为 convenience API 重新执行 live worker；诊断 payload 必须有大小上限。

## 11. 测试计划

### 单元测试

- policy exact reference 与 checksum mismatch；
- 混合 task/external input 的逐项授权；
- task: 与 task:// 归一化；
- chain/shared dependency depth、cycle 和 unknown dependency；
- reduce 带 patches 的 replay parity；
- halt store 写入异常和 reason code。

### 集成测试

- TaskPlanStageRunner.apply_patch 的 policy pinning；
- candidate -> plan -> patch -> result -> aggregation -> halt 的 durable event 顺序；
- crash 在 halt、patch acceptance 和 result terminal event 前后的 recovery；
- durable store 与 in-memory store 的同一历史 replay parity。

### 架构测试

- TaskPlan 不得成为第二个 workflow authority；
- queue record 不得覆盖 Plan projection；
- replay 不得 import 或调用 live worker/planner；
- policy、gate、tool、memory 和 publication boundary 仍由 Harness 控制。

## 12. 观测与运营

建议增加以下 metrics：

    task_plan_policy_mismatch_total
    task_plan_input_validation_rejected_total
    task_plan_depth_rejected_total
    task_plan_halt_persistence_failed_total
    task_plan_replay_patch_mismatch_total
    task_plan_recovery_quarantine_total

metrics label 只允许 stage_id、reason_code、policy_ref、plan_version 等低基数字段，不得使用 raw run_id、prompt 或私有 payload。

## 13. 交付阶段

### Phase 0：契约与回归夹具

建立上述失败场景的最小 fixture、golden event history 和 reason-code 断言。

### Phase 1：权限与边界修复

完成 policy pinning、逐项 input authorization、URI normalization 和 DAG depth 修复。

### Phase 2：durable failure 与 replay 修复

完成 halt persistence fail-closed、recovery 行为和 reduce/replay parity。

### Phase 3：集成与发布门

运行 Harness、TaskPlan、workflow runtime、architecture 和 smoke 检查；确认静态检查不再报告本范围内的未使用代码或错误导入。

## 14. 完成定义

- 所有 P1/P2 问题都有回归测试并通过；
- TaskPlanValidator、TaskPlanPatchValidator、TaskPlanReplayReducer 和 TaskPlanStageRunner 使用同一套 policy、input、DAG 和 replay 语义；
- durable halt 失败不会被伪装成普通业务失败；
- patch history 可从所有公开 replay/recovery 入口恢复；
- 不新增第二套 Harness authority 或 compatibility layer；
- python -m scripts.dev compile、相关测试、python -m scripts.dev smoke 和 OpenSpec strict validation 均通过；
- 既有静态 Research workflow、artifact publication 和 Graph runtime 回归通过。

## 15. 后续 OpenSpec 建议

本 PRD 建议作为独立 follow-up change 的产品约束，后续创建 OpenSpec change 时至少拆分为：

    harness-taskplan-integrity-hardening
      - policy identity and patch authority
      - input reference normalization and authorization
      - bounded patch DAG validation
      - durable halt and recovery semantics
      - replay parity and regression fixtures

实现前必须先完成 proposal、design、spec delta 和 tasks，并使用：

    openspec validate <change> --strict
