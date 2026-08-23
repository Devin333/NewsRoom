# 子 PRD 03：Domain-neutral Owners 与 Storage

## 目标

把 Artifact、Event、inspection、index、node-output 和 storage 的有用能力迁到明确 owner，并切换到 Graph durable contract；迁移能力后才允许删除 legacy Workflow bridge。

## 前置

完成 `prd-01-graph-contract-and-identity.md` 和 `prd-02-harness-control-plane-and-admission.md`。

## 任务来源

对应 `tasks.md` 的 **4.1-4.13**。

## 范围

- 保留 `framework/harness/artifacts/**`、physical Artifact storage、catalog、integrity、quota、usage、cost、GC、inspection 和 controller-terminal publication owner。
- 将 event projection/read model、stream identity validation、event application port、run operation/inspection/replay 和 Graph storage indexing 切到 Graph authority。
- 激活 durable Graph context writer、Graph event/index writer/reader、read-back、projection、replay checks 和 typed unavailable/quarantine contract。
- 激活 Graph-native physical executor、node-output resource、monotonic lease、staged write/commit、stale-owner rejection、cancellation/reconciliation。
- 删除 `WorkflowArtifactRef`、legacy publisher/reader 和仅服务它们的 bridge；不得删除 Artifact 产品能力或 raw storage/integrity/path-safety primitives。

## 不在范围内

本切片不负责 Research graph declaration、AgentLoop loop contract 或 API/CLI/MCP/SDK public major schema；只提供稳定 application/storage ports 和 owner-level contracts。

## 完成标准

- Artifact/Event/index/read-back 使用同一 Graph identity、sequence、checksum 和 idempotency contract。
- V2 manifest、event projection、node-output commit 在 write/read/replay/recovery 中保持一致；旧 reader 不可从 production composition 到达。
- 同 definition 多 node instance 的 artifact、event、output、GC 和 inspection 不串线。
- legacy bridge 的 import/export/registry/test zero-reference proof 有机器可读 evidence。

## 建议验证

```powershell
python -m scripts.dev compile
python -m pytest tests/infrastructure/research tests/infrastructure/storage tests/interfaces/services/test_event_projection_service.py tests/interfaces/services/test_event_reader_service.py -q
python -m pytest tests/architecture/test_graph_artifact_owner_boundary.py tests/architecture/test_harness_durable_event_boundary.py -q
```

## 交付物

owner contract、production composition、storage read-back/replay tests、legacy bridge deletion evidence 和 `tasks.md` 的 4.x 更新。完成后由 `prd-04`、`prd-05` 消费这些 application ports。
