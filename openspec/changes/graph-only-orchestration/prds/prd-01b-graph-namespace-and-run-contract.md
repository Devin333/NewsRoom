# 叶子 PRD 01b：Graph Namespace 与 Run Contract

## 目标

建立最终 Graph namespace，并把 run declaration 从 Workflow-shaped contract 收敛为显式 `HarnessRunSpec.graph` 和不可变 `HarnessGraphDefinition`。

## 任务来源与前置

- 根任务：`tasks.md` 2.1-2.3。
- 前置：01a 的 inventory/freeze evidence。
- 后续：01c 依赖本叶子冻结的 definition/reference/wire schema。

## 允许修改

- `framework/harness/graph/**` 的 DSL、normalized graph、reference、definition 和 runtime resolution owner。
- `framework/harness` 的 run contract、serialization、type exports 和直接 caller。
- Graph contract、round-trip、identity 和 namespace architecture tests。

## 不允许修改

- 不把 scheduler/evaluator 重新实现为第二套 runtime。
- 不保留 `workflow` 作为 nullable alias，不把 Graph state 投影回 flat Workflow state。

## 完成标准

1. `HarnessGraphDefinition` 具有 immutable `graph_id`、`graph_version`、root Graph、activity bindings、terminal policy 和 canonical serialization。
2. `HarnessRunSpec.graph` 是唯一生产 declaration；缺 Graph、mixed declaration、Workflow alias 在类型和 wire 层都拒绝。
3. Graph package 成为 definition/reference/normalized owner，root facade 只做明确导出，不形成第二个 identity owner。
4. canonical checksum 对字段顺序、默认值和未知字段稳定；同一 payload round-trip 后 checksum 不变。

## 验证与证据

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness/graph tests/framework/harness/test_phase_contract.py -q
python -m pytest tests/architecture/test_harness_graph_namespace_boundary.py tests/architecture/test_framework_public_api.py -q
```

提交 Graph namespace/run contract evidence，并只勾选 2.1-2.3 已有实现的任务。
