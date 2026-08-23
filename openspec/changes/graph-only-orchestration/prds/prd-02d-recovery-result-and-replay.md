# 叶子 PRD 02d：Result、Recovery 与 Replay

## 目标

让 Graph result、checkpoint、recovery、replay 和 duplicate delivery 都以 node-instance/activity/attempt 为权威，且 replay 不调用 worker 或 side effect。

## 任务来源与前置

- 根任务：`tasks.md` 3.8-3.10。
- 前置：02a、02b、02c。
- 后续：03b、03d、04c 依赖 result/recovery contract。

## 允许修改

- Graph result aggregation、node output/result receipt、checkpoint/replay/recovery、gate/version pinning 和 inspection read model。
- adversarial、crash-window、parallel/retry、missing terminal evidence tests。

## 不允许修改

- replay 不重新执行 LLM、Tool、worker、retrieval、memory 或 publication。
- 不落回 flat `HarnessState`、`LEGACY_UNBOUND`、synthetic step 或 `_graph_compat_state()`。

## 完成标准

1. 同 `step_id` 的多个 node instances、retry attempts 和 parallel branches 同时存在且不覆盖。
2. crash after decision/before projection、stale commit、missing terminal evidence、duplicate receipt 有明确恢复/quarantine 行为。
3. `HarnessRunResult`、gate context、Wait/resume、inspection 直接消费 Graph state/event projection。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/control_plane tests/framework/harness/runtime tests/framework/harness/graph -q
python -m pytest tests/framework/harness/control_plane/test_graph_checkpoint_replay.py tests/framework/harness/control_plane/test_graph_only_checkpoint_replay.py -q
```

提交 replay live-call count 和 recovery evidence。
