# 子 PRD 02：Harness Control Plane 与 Admission

## 目标

让 Harness 成为唯一的 Graph 流程控制者，闭合有界 `PLAN -> EXECUTE -> VERIFY`、dispatch、gate、budget、retry/replan、wait、side-effect 和 crash recovery 边界；physical worker execution 不得回流 control plane。

## 前置

完成 `prd-01-graph-contract-and-identity.md`，并使用其冻结的 Graph/run/node/activity/attempt identity。

## 任务来源

对应 `tasks.md` 的 **3.1-3.18**。其中包含 control plane、scheduler/evaluator/state/checkpoint/durable event、TaskPlan、side-effect、memory/governance、worker/skill/LLM scope、RAG session 和 flat runtime 删除边界。

## 范围

- control plane、scheduler、evaluator、state、checkpoint、durable event、phase transition、replay 和 TaskPlan caller 的 Graph identity 收口。
- activity binding、physical dispatcher admission、lease/cancellation/reconciliation 和 exact committed node-output contract。
- Harness-owned side-effect intent/decision/outcome/approval identity；terminal 使用 `terminal_action` 和 run-level Graph identity，不创建 synthetic step。
- worker 只能产生 candidate/evidence；memory write、tool authorization、budget scope、skill promotion、artifact publication 只能由 Harness gate/handler 决定。
- 删除 `_graph_compat_state()`、flat `HarnessState`、`LEGACY_UNBOUND` 和无 production caller 的 flat checkpoint/replay runtime。

## 不在范围内

不迁移 Research 业务 graph builder、AgentLoop production composition 或外部 API schema；它们必须消费本切片提供的 application/physical ports，不能自行实现控制决策。

## 完成标准

- 没有 physical dispatcher、exact node-output commit 或合法 Graph admission 时，零 durable mutation、零 worker、零 side effect。
- gate 失败只能触发有界 replan/retry/halt；不存在无限重试或 worker 自行恢复。
- crash/reopen/replay、lease fencing、duplicate delivery、parallel same-definition node 和 terminal side-effect 测试通过。
- 每次 phase transition 都有 durable transcript/event，且与 Graph/node-instance/activity/attempt identity 对齐。

## 建议验证

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness tests/framework/shared tests/infrastructure/storage/harness -q
python -m pytest tests/architecture/test_harness_durable_event_boundary.py tests/architecture/test_harness_graph_result_boundary.py -q
```

## 交付物

control-plane/admission/recovery 实现、focused/adversarial tests、side-effect/budget evidence 和 `tasks.md` 的 3.x 更新。完成后把 dispatcher、node-output、event 和 artifact port 的稳定契约交给 `prd-03`。
