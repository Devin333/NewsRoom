# 叶子 PRD 02a：Control Plane Graph Identity 与 Durable Phase

## 目标

把 control plane、scheduler、evaluator、state、phase transition 和 durable transcript 统一绑定到 frozen Graph identity。

## 任务来源与前置

- 根任务：`tasks.md` 3.1-3.3。
- 前置：01d；必须复用 01c 的 pinned Graph schema。
- 后续：02b、02d 和 03b 依赖 phase/event identity。

## 允许修改

- `framework/harness/control_plane/**`、scheduler/evaluator/state/phase/durable event caller。
- phase transition/event schema、Graph event context、transcript/replay metadata 和相关 tests。

## 不允许修改

- 不让 control plane 直接执行 physical worker，不新增 runtime reverse import。
- 不在 durable event 中把 `step_id` 当 execution authority。

## 完成标准

1. route table、condition、activity readiness、quality gate 和 budget context 从 pinned Graph 读取。
2. 每次 `PLAN -> EXECUTE -> VERIFY` transition 记录 durable event/transcript，字段包含 Graph/run/node-instance identity。
3. phase/event checksum、sequence、attempt 与 Graph reference exact match；跨 Graph 或 tamper fail closed。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/control_plane tests/framework/events -q
python -m pytest tests/architecture/test_harness_durable_event_boundary.py tests/framework/events/test_graph_phase.py -q
```

交付 durable phase identity evidence，不能把旧 `phase_recorded` writer 作为新 Graph writer 的替代品。
