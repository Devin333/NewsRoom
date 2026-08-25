# 叶子 PRD 04c：Research E2E、Recovery 与 Boundary Acceptance

## 目标

用 production-shaped composition tests 验证 static/dynamic/reader-repair/gated-failure/artifact-publication/replay/recovery，并证明 Research 不越过 Harness 边界。

## 任务来源与前置

- 根任务：`tasks.md` 5.7-5.8。
- 前置：04a、04b、03a-03e。
- 后续：06d、07c 使用本叶子的 E2E baseline。

## 允许修改

- Research integration/service/composition tests、boundary scan、offline fixture/evidence。
- 必要的 production wiring bug fix，但不扩张到 public interface 或 legacy deletion。

## 不允许修改

- 不用 fake success 掩盖缺失 physical dispatcher、Graph identity、gate evidence 或 artifact read-back。
- replay/recovery 测试不得调用真实 worker/LLM/tool/retrieval/memory/publication。

## 完成标准

1. static/dynamic/reader repair 三条路径都经过 physical activity -> node output -> deterministic VERIFY。
2. gated failure、crash reopen、parallel/retry、artifact publication、offline replay 有明确结果和 identity。
3. Research import boundary 对旧 `paper_radar`、`workflows`、interfaces/infrastructure legacy runtime 零 active caller。

## 验证与证据

```powershell
python -m pytest tests/business/research tests/interfaces/composition -q
python -m pytest tests/architecture/test_research_boundaries.py tests/architecture/test_harness_graph_authority.py -q
```

提交 Research E2E matrix、worker/side-effect count 和 boundary scan。
