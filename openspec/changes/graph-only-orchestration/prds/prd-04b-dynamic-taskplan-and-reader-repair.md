# 叶子 PRD 04b：Dynamic TaskPlan 与 Reader Repair

## 目标

把 dynamic analysis 限定为 frozen outer Graph 内的 opt-in bounded stage，并将 reader repair candidate、memory intent 和 promotion boundary 接入 Harness activity/gate contract。

## 任务来源与前置

- 根任务：`tasks.md` 5.4-5.5。
- 前置：04a、02b、02c；依赖 durable TaskPlan、side-effect 和 Research binding。
- 后续：04c 负责完整 static/dynamic/repair 验收。

## 允许修改

- `framework/harness/task_plan/**`、Research dynamic stage、reader repair workers/declarations、candidate/evidence/promotion contracts。
- dynamic TaskPlan event/result/checkpoint/queue/recovery tests。

## 不允许修改

- dynamic stage 不能新增 outer Graph node、决定 publication/authorization/memory write 或绕过 max turns/replans/retry budget。
- LLM 不能生成 candidate id、operation id、expected-before checksum 等 deterministic identity fields。

## 完成标准

1. `dynamic_analysis`/`dynamic_task_plan` 未显式开启时仍走 static path。
2. production dynamic run 需要 durable storage 和真实 binding；依赖缺失 fail closed 为 typed unavailable。
3. PlanCandidate 只有在 schema/DAG/policy/capability/budget/gate/binding 验证后成为 immutable ValidatedTaskPlan。
4. reader repair 只能提交 candidate/evidence；memory write/promotion 由 Harness terminal side-effect 完成。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/task_plan tests/business/research/graphs tests/business/research/reader_repair -q
python -m pytest tests/business/research/integration/test_research_rag_loop_fake_runtime.py tests/business/research/graphs/test_task_plan.py -q
```

提交 dynamic boundedness、repair candidate 和 zero-memory-write evidence。
