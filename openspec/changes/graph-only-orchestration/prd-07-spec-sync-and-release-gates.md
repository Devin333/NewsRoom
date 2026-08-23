# 子 PRD 07：Canonical Spec 同步与 Release Gates

## 目标

把 Graph-only implementation 反映到 canonical OpenSpec、架构文档、运行手册和接口文档，并完成最终 compile、smoke、strict validation、全量验收和 release review。

## 前置

完成 `prd-01` 至 `prd-06`，且所有前置任务的代码、测试、evidence 和 path-scoped commits 已经可追溯。

## 任务来源

对应 `tasks.md` 的 **10.1-10.8、11.1-11.9**。

## 范围

- 将 Graph-only delta 同步到 `harness-graph`、`harness-runtime`、`research-runtime`、AgentLoop、Artifact、architecture、interface、cleanup 和 storage capabilities。
- 删除或 supersede 仍要求 WorkflowRunner、WorkflowExecutor、AgentLoopStepRunner、DataBuffer、Workflow schema 或 compatibility import 的 canonical requirements。
- 更新架构文档、运行手册、CLI/API/MCP 文档、Research composition 文档、migration/quarantine 说明和 release review evidence。
- 执行 Graph static/dynamic Research E2E、approval wait/resume、crash recovery、offline replay、artifact inspection、legacy rejection 和 zero-side-effect 验收。

## 不在范围内

不借助文档修改掩盖 source/test 缺口，不伪造 production qualification、managed-environment sign-off、rollback drill 或 pointer switch。发现实现缺口时回退到对应子 PRD，而不是放宽验收。

## 完成标准

- `python -m scripts.dev compile`、`python -m scripts.dev smoke`、focused/full tests、source validation、architecture suite、zero-reference scan 全部通过。
- `openspec validate graph-only-orchestration --strict` 和 `openspec validate --all --strict` 通过，且 canonical specs 与 active source 的 Graph authority 一致。
- replay 的 worker/tool/LLM/retrieval/memory-write/publication count 满足 zero-side-effect 规则；legacy input 只能 quarantine。
- 每个职责 slice 有独立提交和 evidence；最终 review 确认无 compatibility facade、fallback executor、legacy writer、hidden feature flag 或未登记 history store。

## 建议验证

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec validate graph-only-orchestration --strict
openspec validate --all --strict
```

## 交付物

canonical spec/doc 更新、完整 release evidence、最终 checklist 和归档前 review。只有本子 PRD 完成后，才能讨论 archive `graph-only-orchestration`。
