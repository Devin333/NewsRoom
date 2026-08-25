# 叶子 PRD 03d：Node-output Resource 与 Physical Dispatcher

## 目标

让 physical executor 独占 worker execution、lease、cancellation、reconciliation 和 result commit；control plane 只负责 durable decision、dispatch、VERIFY 和 transition。

## 任务来源与前置

- 根任务：`tasks.md` 4.10、4.13。
- 前置：02d 的 result/recovery 和 03a/03b 的 terminal/event ports。
- 后续：04a、04d 需要使用唯一 dispatcher。

## 允许修改

- `framework/harness/control_plane` dispatch boundary、Graph node-output resource port、physical executor/dispatcher、lease/current-commit reader。
- Research production composition、crash-window、lease-fencing、cancellation/reconciliation tests。

## 不允许修改

- control plane 不得直接执行 worker，不得反向导入 legacy runtime。
- resource generation 不得来自 Graph/local attempt、budget、retry credit 或 event sequence。

## 完成标准

1. 无 dispatcher、无 exact current commit、stale owner 或 missing binding 时 zero mutation/worker。
2. staged write/commit、atomic monotonic lease、typed stale-owner rejection、duplicate delivery 和 crash reopen 具备证据。
3. 同一 activity 不会双重执行；restart/cancel/reconciliation 能恢复或稳定 halt。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/control_plane tests/framework/harness/runtime tests/infrastructure/research -q
python -m pytest tests/framework/harness/control_plane/test_node_output_resource.py tests/business/research/integration/test_graph_artifact_cutover.py -q
```

提交 dispatcher admission/reconciliation evidence；这是 production wiring 的独立 commit 边界。
