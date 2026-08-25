# 叶子 PRD 03a：Artifact Owner 与 Inspection

## 目标

保留 Artifact 产品能力并让其只消费 Artifact-owned Graph terminal manifest、integrity、catalog、governance、GC 和 inspection contract；删除仅属于 Workflow 的 artifact bridge。

## 任务来源与前置

- 根任务：`tasks.md` 4.1-4.2、4.6。
- 前置：02c/02d 的 terminal publication 和 result contract。
- 后续：03c、04c、06d 依赖 Artifact owner/read-back。

## 允许修改

- `framework/harness/artifacts/**`、`infrastructure/storage/artifacts/**`、Research publisher/lifecycle/composition、artifact inspection service。
- `WorkflowArtifactRef`、`WorkflowArtifactPublisher`、`LocalArtifactPublisher` 的 caller migration/deletion 和 owner tests。

## 不允许修改

- 不删除 raw storage、path safety、checksum、catalog、quota、usage、cost、GC、retention 或 publication owner。
- worker/activity 不能直接发布 manifest/public ref。

## 完成标准

1. controller-terminal deterministic VERIFY 后才能提交 terminal manifest、catalog/usage facts 和 public refs。
2. v2 manifest strict read/write/read-back 使用 Graph execution version/checksum；v1 只能 quarantine。
3. artifact inspection 读取 Graph terminal manifest，不从旧 Workflow manifest 猜测。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/artifacts tests/infrastructure/research tests/infrastructure/storage/artifacts -q
python -m pytest tests/architecture/test_graph_artifact_owner_boundary.py tests/infrastructure/research/test_artifact_port.py -q
```

提交 Artifact owner/read-back evidence；删除 bridge 时保持 raw primitives 可用。
