# 叶子 PRD 02b：Deterministic Control Nodes 与 TaskPlan Boundary

## 目标

保留 Sequence、Choice、Parallel、Join、Bounded Loop、Wait、approval、timer、signal、compensation 等确定性 control nodes，并把 dynamic TaskPlan 限定在 frozen Graph 的显式 stage。

## 任务来源与前置

- 根任务：`tasks.md` 3.4-3.6。
- 前置：02a；TaskPlan 还需使用 01c 的 schema pin。
- 后续：04b 消费 dynamic stage 和 Research candidate contract。

## 允许修改

- Graph evaluator/scheduler control-node handlers、TaskPlan validation/store/queue/stage binding。
- Function、Tool、Skill、SubAgent、AgentLoop activity binding 和 readiness contract。

## 不允许修改

- LLM/worker 不能新增 outer Graph node、route、gate、budget 或 authorization。
- dynamic TaskPlan 不能成为分布式无限 DAG，也不能逃逸 frozen Graph。

## 完成标准

1. control nodes 由普通 deterministic function/service 执行，不委托给 agent。
2. dynamic candidate 必须经过 schema、DAG、capability、budget、policy、gate、binding 校验后成为 immutable validated plan。
3. leaf activity 只接收 Harness 已接受的 binding/input；worker output 进入 candidate/evidence channel。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/graph tests/framework/harness/task_plan tests/framework/harness/control_plane -q
python -m pytest tests/framework/harness/graph/test_definition.py tests/framework/harness/task_plan/test_task_plan_contract_matrix.py -q
```

提交 control-node/TaskPlan boundary evidence，并记录 worker 不能改变 route 的 adversarial case。
