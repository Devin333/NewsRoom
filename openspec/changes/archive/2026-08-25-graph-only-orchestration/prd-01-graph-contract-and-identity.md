# 子 PRD 01：Graph Contract 与 Identity

## 目标

把 Graph declaration、compiler、versioning、preflight 和 canonical identity 收敛成唯一的公共契约，为后续 control plane、storage、Research 和 public surface 提供冻结输入。

## 任务来源

对应 `tasks.md` 的 **1.1-1.9、2.1-2.10**。已完成的任务只作为 evidence 读取，不重复实现；未完成任务按当前 source 重新验证后再勾选。

## 范围

- `framework/harness/graph/**` 的 DSL、normalized graph、compiler、reader、versioning、validation、binding 和 runtime resolution owner。
- `HarnessRunSpec.graph`、`HarnessGraphDefinition`、`HarnessGraphReference`、`GraphRunIdentity`、`GraphStageIdentity`、`GraphExecutionIdentity` 的 schema、canonical serialization、checksum 和 unknown-version fail-closed。
- preflight、dual declaration rejection、legacy Workflow declaration rejection，以及 worker/side-effect 前的 admission contract。
- `step_id` 只保留为 Graph definition-level leaf label；durable execution 必须使用 node instance，activity fact 还必须使用 activity/attempt。

## 不在范围内

本切片不迁移 Research caller、AgentLoop、Artifact/Event storage、API/CLI/MCP/SDK，也不删除 legacy runtime；这些由后续子 PRD 承担。不得通过保留 fallback 或 compatibility alias 提前“兼容”后续切片。

## 完成标准

- 新 run 只能显式声明 checksum-valid Graph；`graph=None`、legacy routing、dual declaration 和 unknown schema 在任何 mutation 前 fail closed。
- Graph identity 在序列化、反序列化、checkpoint、event、result 和 public contract 中字段一致，跨 Graph/checksum/node/activity/attempt substitution 被拒绝。
- 两个相同 definition `step_id` 的不同 `node_instance_id` 可以并存，且不相互覆盖。
- focused Graph contract、compiler、identity、preflight、architecture boundary tests 通过。

## 建议验证

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness/graph tests/framework/harness/control_plane/test_graph_state.py tests/architecture/test_harness_graph_authority.py -q
openspec validate graph-only-orchestration --strict
```

## 交付物

实现提交、对应 contract tests、Graph identity/checksum evidence，以及 `tasks.md` 的 1.x/2.x 勾选更新。完成后将 exact contract 作为 `prd-02` 至 `prd-05` 的输入，不重新定义 identity。
