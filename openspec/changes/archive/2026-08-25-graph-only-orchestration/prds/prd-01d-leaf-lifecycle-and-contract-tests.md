# 叶子 PRD 01d：Leaf Lifecycle 与 Graph Contract Tests

## 目标

明确 `HarnessStepSpec` 只描述 executable leaf lifecycle，禁止它拥有 outer routing、readiness 或 publication decision，并补齐 Graph contract 的组合测试。

## 任务来源与前置

- 根任务：`tasks.md` 2.8-2.10。
- 前置：01b、01c。
- 后续：02b 使用 leaf activity binding，02d 使用 contract round-trip/recovery oracle。

## 允许修改

- leaf lifecycle、activity binding、gate/terminal policy 和 Graph contract tests。
- `HarnessStepSpec`、`StepRef` 的职责注释、validation 和 exports。

## 不允许修改

- 不把 leaf 改造成 outer scheduler，不通过 step label 决定 routing、quality 或 publication。
- 不删除 Graph DSL 中合法的 definition-level `step_id`。

## 完成标准

1. leaf 只能表示 activity input/output lifecycle，outer route/readiness/publication 由 Graph/Harness 管理。
2. round-trip、canonical checksum、unknown construct、missing Graph、dual declaration、no-worker-before-preflight 具备正向测试。
3. 同 definition 多实例、retry、loop、parallel 的 identity oracle 明确区分 `node_id` 与 `node_instance_id`。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/graph tests/framework/harness/control_plane -q
python -m pytest tests/architecture/test_harness_graph_authority.py tests/architecture/test_harness_graph_namespace_boundary.py -q
```

提交 contract matrix 和测试 evidence；完成后才进入 02a。
