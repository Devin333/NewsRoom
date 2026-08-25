# 叶子 PRD 04a：Research Graph Composition

## 目标

把 Research composition 从 Workflow declaration 迁为 `HarnessGraphDefinition`，固定 static `Parallel-All + VerifiedAggregation` Graph，并让所有 production activity 使用 exact Graph binding。

## 任务来源与前置

- 根任务：`tasks.md` 5.1-5.3、5.6。
- 前置：03d、03e；使用 01b/01c 的 Graph definition/compiler。
- 后续：04b/04c、05a 消费 Research composition contract。

## 允许修改

- `business/research/graphs/**`、Research application/composition、graph builder/fixtures/tests。
- static graph checksum、gate version、physical activity/output/artifact/event port wiring。

## 不允许修改

- 不保留 `business/research/workflows` 作为 active import，不把 builder 返回 Workflow spec。
- 不让 Research service 决定 routing、quality gate、publication 或 memory write。

## 完成标准

1. Research production composition 返回 explicit `HarnessGraphDefinition`，无 legacy routing fields。
2. static path 固定 `Parallel-All + VerifiedAggregation`，Graph checksum/gate version pinned。
3. composition 只安装 exact physical dispatcher、node output、artifact/event ports。
4. `business/research` import scan 不命中旧 Workflow/paper-radar authority。

## 验证与证据

```powershell
python -m pytest tests/business/research/application tests/business/research/graphs tests/interfaces/composition -q
python -m pytest tests/architecture/test_research_boundaries.py tests/interfaces/composition/test_research_composition.py -q
```

提交 Research static composition evidence 和 Graph checksum。
