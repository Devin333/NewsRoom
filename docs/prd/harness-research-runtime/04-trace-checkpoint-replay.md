# 阶段 4：Trace / Checkpoint / Replay

## 阶段目标

让 Harness 运行可审计、可恢复、可回放。阶段 4 仍然使用 fake worker，不接 Research。

## 新增或完善目录

```text
framework/harness/control_plane/
  event_log.py
framework/harness/runtime/
  checkpoint.py
  checkpoint_store.py
  replay.py
  durable_state.py
framework/harness/control_plane/
  trace.py
```

## Event Log

每个 Harness event 至少记录：

```text
event_id
run_id
step_id
event_type
status_before
status_after
decision
worker_type
input_ref
output_ref
retry_count
error
timestamp
metadata
```

要求：

- event append-only。
- event 不存大 payload，大 payload 用 artifact ref。
- event 可导出 dict。
- event_id 稳定可生成，便于 replay。

## Trace Export

Trace 是对 event log 的可读投影。

必须能回答：

- run 为什么进入某个 step？
- step 为什么重试？
- quality gate 为什么失败？
- run 为什么成功或失败？
- worker 产出了什么 artifact ref？

Trace 输出建议：

```text
run_id
workflow_id
status
steps[]
decisions[]
errors[]
artifacts[]
metrics
```

## Checkpoint

Checkpoint 保存 HarnessState 的恢复点。

字段建议：

```text
checkpoint_id
run_id
state
last_event_id
created_at
checksum
metadata
```

要求：

- 可序列化。
- 支持 in-memory fake store。
- 后续可接文件或数据库 store。
- checksum 用于发现损坏或错配。

## Replay

ReplayRunner 使用 event log 或 checkpoint + fake worker 复现状态推进。

阶段 4 的 replay 不要求重放真实 LLM，只要求：

- 根据 event log 重建状态。
- 根据 checkpoint 恢复后继续运行 fake workflow。
- replay 不产生新的外部 side effect。

## 与已有框架复用

可参考：

```text
framework/events
framework/workflow/checkpoint
framework/workflow/inspection/replay.py
framework/artifacts
```

但不要让旧 workflow runtime 接管 Harness 状态。可以复用模型思想、store pattern、checksum 工具，不要复用旧控制流。

## 测试要求

新增：

```text
tests/framework/harness/runtime/test_event_log.py
tests/framework/harness/runtime/test_trace_export.py
tests/framework/harness/runtime/test_checkpoint_store.py
tests/framework/harness/runtime/test_replay.py
tests/framework/harness/runtime/test_resume_from_checkpoint.py
```

必须覆盖：

- 每个 step 产生 event。
- trace 能解释成功和失败。
- checkpoint 可 roundtrip。
- 从 checkpoint 恢复后继续执行。
- replay 不调用真实 worker side effect。
- checksum 不匹配时拒绝恢复。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Harness 每次运行都有 event log。
- 可以导出 trace。
- 可以保存和恢复 checkpoint。
- 可以 replay fake workflow。
- 不接业务，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/04-trace-checkpoint-replay.md。
要求：
1. 实现 Harness event log、trace export、checkpoint、checkpoint store、replay。
2. 复用旧 framework/events 或 checkpoint 思路可以，但旧 workflow runtime 不能接管 Harness 状态。
3. Event 不存大 payload，大内容使用 artifact ref。
4. 添加 event、trace、checkpoint、resume、replay 测试。
5. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
6. 修改完成后提交。
全部回复和问题用中文。
```
