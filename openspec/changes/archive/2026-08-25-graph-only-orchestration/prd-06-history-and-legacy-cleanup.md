# 子 PRD 06：History Quarantine 与 Legacy Cleanup

## 目标

在 Graph replacement coverage 完成后，隔离历史 Workflow 数据并删除 production legacy runtime、reader、writer、compatibility export 和仅服务旧 runtime 的测试，形成可审计的 zero-reference proof。

## 前置

完成 `prd-01` 至 `prd-05`。任何尚未迁移的 live caller 都必须先回到对应子 PRD，不能在本切片保留 shim。

## 任务来源

对应 `tasks.md` 的 **8.1-8.12、9.1-9.11**。

## 范围

- history-only schema reader、Workflow record classifier、quarantine reason、checksum、sequence gap、ambiguous record 和 dry-run inventory。
- 证明 migration/replay/classifier 无 LLM、Tool、worker、retrieval、memory write、publication 和 Graph store side effect。
- 将 history fixture/raw record 隔离到非 production import 路径，删除 active migrator、legacy reader、dual-store writer、rollback switch 和 compatibility facade。
- 删除 `framework/workflow`、`framework/harness/workflow`、`framework/specs/workflow` 的 production source、root exports、registry、reflection、legacy schema writer 和 only-legacy fixtures。
- production import/export/schema/entrypoint zero-reference scan；历史输入只能 typed quarantine，不能 resume、replay、worker 或 side effect。

## 不在范围内

不删除 Artifact owner、raw storage、integrity/path-safety、Graph checkpoint/replay、Research Graph 或现行 public application service。删除前必须找到 replacement owner 和测试证据。

## 完成标准

- unknown schema、identity mismatch、checksum tamper、sequence gap、重复输入和缺失 gate evidence 稳定拒绝。
- legacy package/source/public symbol/registry/import/test/fixture 只有明确 history allowlist 命中，且 allowlist 不可覆盖整目录。
- 删除后 compile、focused/full tests、source validation、architecture scan 和 history side-effect count 全通过。

## 建议验证

```powershell
python -m scripts.dev compile
python -m pytest tests/architecture tests/scripts tests/infrastructure/storage/events -q
rg -n "WorkflowRunner|WorkflowExecutor|AgentLoopStepRunner|framework\.workflow|workflow_id" framework business interfaces infrastructure scripts --glob '*.py'
```

## 交付物

quarantine/deletion evidence、zero-reference inventory、删除提交和 `tasks.md` 的 8.x/9.x 更新。完成后只剩 canonical spec 同步和最终 release gate。
