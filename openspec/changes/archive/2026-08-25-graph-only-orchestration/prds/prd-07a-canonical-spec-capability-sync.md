# 叶子 PRD 07a：Canonical OpenSpec Capability 同步

## 目标

把 Graph-only implementation 同步到 canonical capabilities，删除仍要求 legacy Workflow authority 的 requirements，并保持 capability traceability 完整。

## 任务来源与前置

- 根任务：`tasks.md` 10.1-10.4。
- 前置：06d；canonical spec 只能在 source deletion proof 后收口。
- 后续：07b-07d。

## 允许修改

- `openspec/specs/**`、active change specs、capability archive metadata 和 traceability evidence。
- `harness-graph`、`graph-storage-indexing`、`approval-graph-resume-interfaces` 等 Graph capability。

## 不允许修改

- 不通过删除 requirement 掩盖未完成 source/test；不保留 Workflow compatibility requirement。
- 不改变本 change 的 Graph identity、Artifact retain invariant 或 Harness authority。

## 完成标准

1. Graph-only delta 在 `harness-graph` canonical spec 中可追溯。
2. Graph storage/indexing、approval resume capability requirements 已同步；旧 capability 明确 superseded/archive。
3. `harness-runtime`、`research-runtime`、AgentLoop、Artifact、interface、architecture、cleanup specs 不再要求 Workflow authority。

## 验证与证据

```powershell
openspec validate graph-only-orchestration --strict
openspec validate --all --strict
rg -n "WorkflowRunner|WorkflowExecutor|AgentLoopStepRunner|framework\.workflow" openspec/specs openspec/changes
```

提交 capability traceability matrix 和 supersede/archive evidence。
