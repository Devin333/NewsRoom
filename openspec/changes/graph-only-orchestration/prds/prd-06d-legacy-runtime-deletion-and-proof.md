# 叶子 PRD 06d：Legacy Workflow Runtime 删除与 Zero-reference Proof

## 目标

在所有 replacement owner 和 public surface 完成后，删除旧 Workflow runtime、exports、registry、schema、compatibility tests，并生成逐 symbol deletion proof。

## 任务来源与前置

- 根任务：`tasks.md` 9.1-9.11。
- 前置：01-06c；任何仍有 active caller 的 legacy symbol 必须回到对应叶子修复。
- 后续：07a-07d。

## 允许修改

- `framework/workflow/**`、`framework/harness/workflow/**`、`framework/specs/workflow.py`、root exports、legacy registries/reflection/schema/tests/fixtures。
- deletion inventory、allowlist、zero-reference scan and architecture tests。

## 不允许修改

- 不删除 Artifact owner、Graph control-plane checkpoint/replay、raw storage 或 history-only frozen fixture。
- 不保留 shim、forwarding facade、fallback executor、hidden feature flag 或 dual runtime。

## 完成标准

1. Workflow runners/executors/routing/scheduling/compiler/governance/checkpoint/buffer/inspection/operations/runtime/specs 全部无 production caller。
2. root/public API 不导出 `WorkflowRunner`、`WorkflowExecutor`、legacy `RunResult` 等 authority。
3. schema/registry/reflection/CLI/API/MCP/SDK/fixtures/exports 的 zero-reference proof 只允许具体 history allowlist。
4. deletion 后 compile、architecture、source validation 和 targeted/full tests 通过。

## 验证与证据

```powershell
python -m scripts.dev compile
python -m pytest tests/architecture tests/scripts tests/interfaces -q
rg -n "WorkflowRunner|WorkflowExecutor|AgentLoopStepRunner|framework\.workflow|framework\.harness\.workflow|workflow_id" framework business interfaces infrastructure scripts --glob '*.py'
```

提交逐 symbol deletion proof 和 path-scoped deletion commit。
