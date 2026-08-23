# 子 PRD 04：Research Graph 与 AgentLoop

## 目标

把 Research 和 AgentLoop 接入唯一 Graph outer orchestration：Research 只声明 Graph，AgentLoop/ SubAgent/TaskPlan 只作为受 Harness 控制的 leaf activity，RAG/context、reader repair 和 memory candidate 不得拥有外层控制权。

## 前置

完成 `prd-01`、`prd-02`、`prd-03`，尤其是 physical dispatcher、node-output、artifact/event ports 和 deterministic gate contract。

## 任务来源

对应 `tasks.md` 的 **5.1-5.8、6.1-6.7**。

## 范围

- `business/research/workflows` 到 `business/research/graphs` 的迁移，Research composition 返回 `HarnessGraphDefinition`。
- static `Parallel-All + VerifiedAggregation`、opt-in dynamic TaskPlan、reader repair、artifact publication、gated failure、replay 和 recovery 的 Graph caller 收口。
- RAG/context/session/snapshot/cache/materializer 使用 exact Graph stage/execution identity；standalone RAG 必须显式使用 standalone scope，不伪造 Graph authority。
- AgentLoop 的 LLM/tool/judge loop、SubAgent v3、conversation/message、cursor、iteration checkpoint、transcript、receipt 和 output artifact 使用 node-instance/activity/attempt identity。
- AgentLoop 只能返回 candidate/evidence；不能决定 routing、quality、budget、approval、memory write、tool authorization 或 publication。

## 不在范围内

本切片不删除全部 legacy runtime，也不重新设计 public approval API；只迁移 Research/AgentLoop caller 并提供 production E2E evidence。

## 完成标准

- static/dynamic/reader-repair Graph E2E 都经过 physical activity -> node output -> deterministic VERIFY。
- worker 阶段 memory-write、publication、approval resume 和 routing count 为零；VERIFY/replay/duplicate delivery 不产生非 Harness side effect。
- retry/loop/parallel 的 message、context、artifact、TaskPlan、SubAgent transcript 和 receipt 不混淆 node instance。
- `business/research` 不导入旧 `business/research/workflows`、`paper_radar`、legacy interface/infrastructure runtime。

## 建议验证

```powershell
python -m scripts.dev compile
python -m pytest tests/business/research tests/framework/agent tests/framework/harness/task_plan tests/interfaces/composition -q
python -m pytest tests/architecture/test_research_boundaries.py tests/architecture/test_harness_graph_authority.py -q
```

## 交付物

Research/AgentLoop production wiring、static/dynamic/recovery E2E、memory/side-effect boundary evidence、旧 caller scan 和 `tasks.md` 的 5.x/6.x 更新。
