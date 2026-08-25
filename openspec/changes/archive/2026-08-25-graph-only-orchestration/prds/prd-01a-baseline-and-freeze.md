# 叶子 PRD 01a：Baseline、Inventory 与 Architecture Freeze

## 目标

建立 Graph-only cutover 的可审计基线，冻结旧 Workflow authority 的生产入口，并明确每个 legacy asset 的处置方式。此叶子只做 inventory、分类、freeze contract 和 evidence，不提前删除 runtime。

## 任务来源与前置

- 根任务：`tasks.md` 1.1-1.9。
- 前置：无；这是所有其他叶子 PRD 的入口。
- 后续：01b 必须消费本叶子的 inventory 和 freeze baseline。

## 允许修改

- `openspec/changes/graph-only-orchestration/evidence/**` 的 inventory、freeze、golden Graph 和 provenance 文件。
- `tests/architecture/**` 中的 subtract-only freeze contract。
- `proposal.md`、`design.md` 或 `tasks.md` 中与 owner decision、inventory 状态直接相关的记录。

## 不允许修改

- 不删除 `framework/workflow`、不切换 production writer/reader、不做数据迁移。
- 不新增 Workflow compatibility facade、dual declaration reader 或 feature flag。

## 完成标准

1. inventory 覆盖 source、imports、exports、registry、reflection、CLI/API/MCP/SDK entrypoints、persisted manifest/event/checkpoint/replay/index/cursor schema。
2. 每条记录有 `keep/adapt/migrate/delete/quarantine`、replacement owner、caller、数据处置、phase 和验证命令。
3. freeze gate 只允许 subtract，不允许新增 `framework.workflow`、`WorkflowRunner`、`WorkflowExecutor` 或 legacy writer。
4. Research golden Graph definition、normalized checksum、gate evidence、terminal manifest 和 offline replay baseline 可复现。

## 验证与证据

```powershell
python -m scripts.dev compile
python -m pytest tests/architecture -q
rg -n "WorkflowRunner|WorkflowExecutor|framework\.workflow" framework business interfaces infrastructure scripts --glob '*.py'
```

提交 `evidence/phase-0-baseline.md`、机器可读 inventory/freeze contract 和一份 path-scoped commit；不得勾选后续任务。
