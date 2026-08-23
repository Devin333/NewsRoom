# 叶子 PRD 02c：Side-effect、Memory 与 Governance Authority

## 目标

把 tool authorization、memory write/consolidation、artifact publication、approval side effect 和其他 external side effect 接回 Harness-owned deterministic gate/handler。

## 任务来源与前置

- 根任务：`tasks.md` 3.7。
- 前置：02a、02b；必须使用 exact Graph/node/activity/attempt identity。
- 后续：04b、04c 和 06b 依赖 zero-side-effect contract。

## 允许修改

- `framework/harness/side_effects/**`、approval/governance handler、memory adapter boundary、artifact terminal handler。
- Research reader repair memory side-effect、tool authorization 和 identity tests。

## 不允许修改

- AgentLoop、LLM、Tool、Research worker 不能直接写 memory、发布 artifact、授权 tool 或决定 promotion。
- 不允许 caller-supplied approval decision、state patch、`step_id` durable authority 或 synthetic terminal step。

## 完成标准

1. Intent/Decision/Outcome wire schema 保存 Graph/run/node/activity/attempt；旧 `step_id` wire field 被拒绝或只作为诊断 label。
2. worker 阶段 memory-write、publication、authorization count 为零；只有 deterministic VERIFY 后 terminal handler 可 commit。
3. duplicate delivery、cross-identity tamper、replay、VERIFY failure 和 terminal approval 都 fail closed 或保持幂等。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/side_effects tests/framework/tool tests/infrastructure/research -q
python -m pytest tests/business/research/reader_repair tests/business/research/integration/test_graph_artifact_cutover.py -q
```

提交 side-effect identity/zero-write evidence；这是 P0 slice，完成后单独提交。
