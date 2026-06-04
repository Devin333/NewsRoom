# 阶段 4：Trace / Checkpoint / Replay

## 阶段目标

让 Harness 运行可审计、可恢复、可回放。阶段 4 仍然使用 fake worker，不接 Research。

阶段 4 必须把 `PLAN -> EXECUTE -> VERIFY` 的每次相位转移写入 durable transcript。transcript 是后续复盘和 replay 的权威记录。

## 新增或完善目录

```text
framework/harness/control_plane/
  event_log.py
  transcript.py
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
skill_name
skill_version
skill_candidate_id
rag_session_id
retrieval_round
retry_count
error
timestamp
metadata
```

相位事件必须额外记录：

```text
phase
phase_index
plan_id
plan_key
gate_results
budget_snapshot
halt_reason
replan_reason
evolution_action
promotion_decision
rollback_ref
rag_decision
retrieval_query_refs
accepted_evidence_refs
rejected_evidence_refs
memory_hit_refs
context_envelope_ref
context_snapshot_ref
context_cache_key
compression_record_refs
```

要求：

- event append-only。
- event 不存大 payload，大 payload 用 artifact ref。
- event 可导出 dict。
- event_id 稳定可生成，便于 replay。
- PLAN、EXECUTE、VERIFY、REPLAN、HALT 每次转移都必须落 event。
- Skill evolution 的 collect_experience、candidate_created、static_gate_failed、eval_completed、promotion_decided、release_published、rollback_completed 都必须落 event。
- Bounded Agentic RAG 的 session_started、plan_verified、step_executed、source_verified、context_pack_assembled、gate_failed、replanned、halted、context_pack_returned 都必须落 event。
- Context Engineering 的 context_assembly_started、context_budget_checked、context_compression_verified、context_snapshot_written、context_cache_key_created 都必须落 event。

## Transcript

Transcript 是面向复盘的完整运行记录，比 trace 更接近原始事实。

每条 transcript entry 必须包含：

```text
run_id
step_id
phase
decision
input_refs
output_refs
gate_results
budget_snapshot
worker_call_ref
artifact_refs
skill_refs
candidate_refs
rag_session_refs
retrieval_plan_refs
context_pack_refs
context_envelope_ref
context_snapshot_ref
compression_record_refs
evidence_refs
eval_refs
release_refs
timestamp
```

要求：

- append-only。
- 可按 run_id 导出。
- 不存大 payload，只存 refs 和摘要。
- replay 以 transcript/event log 为输入，不重新询问 LLM。
- halted 必须记录触发预算和最后一个失败 gate。
- skill candidate 被拒绝、晋升或回滚时，transcript 必须能指向对应 eval result、promotion decision 和 rollback plan。
- RAG session 每轮检索、读取、补查、context pack 组装和 halted 都必须能从 transcript 复盘。
- 每次 worker 调用使用的 context envelope 和 context snapshot 必须能从 transcript 追踪。
- 如果发生上下文压缩，transcript 必须记录 compression record refs、source refs、target level 和 gate result。

## Trace Export

Trace 是对 event log 的可读投影。

必须能回答：

- run 为什么进入某个 step？
- step 为什么进入 PLAN/EXECUTE/VERIFY？
- step 为什么重试？
- step 为什么 replan？
- run 为什么 halted？
- quality gate 为什么失败？
- run 为什么成功或失败？
- worker 产出了什么 artifact ref？
- RAG 为什么继续检索、停止、replan 或 halted？
- 哪些 evidence / memory hit 被接受、拒绝或标记冲突？
- skill candidate 为什么被拒绝或晋升？
- active skill version 为什么发生切换或回滚？

Trace 输出建议：

```text
run_id
workflow_id
status
steps[]
decisions[]
errors[]
artifacts[]
skills[]
skill_candidates[]
skill_releases[]
rag_sessions[]
retrieval_rounds[]
context_packs[]
context_snapshots[]
compression_records[]
phase_transitions[]
gate_results[]
budget_summary
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

## Context Snapshot / Compression Replay

阶段 4 必须接入阶段 3D 的 Context Engineering 记录。

每次上下文装配至少写入 event：

```text
context_assembly_started
context_segment_collected
context_budget_checked
context_compression_requested
context_compression_verified
context_snapshot_written
context_cache_key_created
context_envelope_returned
```

Context replay 要求：

- replay 不重新调用 LLM 生成上下文摘要。
- replay 不重新执行真实 retrieval、真实 memory recall、真实 MCP tool。
- replay 只使用 `ContextSnapshot`、`CompressionRecord`、event/transcript 和 artifact refs 重建上下文。
- checksum 不匹配时拒绝恢复。
- trace 必须能解释某个 worker 当时看到了哪些 context refs、哪些被裁剪、哪些被压缩、为什么压缩。
- stable prefix 的 cache key 必须能从 workflow version、worker contract version 和 policy version 重算。

## Replay

ReplayRunner 使用 event log 或 checkpoint + fake worker 复现状态推进。

阶段 4 的 replay 不要求重放真实 LLM，只要求：

- 根据 event log 重建状态。
- 根据 checkpoint 恢复后继续运行 fake workflow。
- replay 不产生新的外部 side effect。
- 能复盘 halted 前的全部 gate failure 和预算消耗。
- 能复盘 skill evolution run 的候选生成、eval、promotion、release 和 rollback。
- 能复盘 bounded RAG session 的 plan、query、source verification、context assembly、replan 和 halted。
- 能复盘 context assembly、compression、snapshot 和 cache key 生成过程。
- replay 不重新运行 optimizer LLM，也不重新发布 skill。
- replay 不重新执行真实检索、真实 MCP tool 或真实 memory write。
- replay 不重新调用 LLM compressor。

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
tests/framework/harness/runtime/test_transcript.py
tests/framework/harness/runtime/test_skill_evolution_transcript.py
tests/framework/harness/runtime/test_rag_transcript_replay.py
tests/framework/harness/runtime/test_context_snapshot_replay.py
tests/framework/harness/runtime/test_compression_record_replay.py
```

必须覆盖：

- 每个 step 产生 event。
- 每个 PLAN/EXECUTE/VERIFY 转移产生 transcript entry。
- trace 能解释成功和失败。
- trace 能解释 replan 和 halted。
- checkpoint 可 roundtrip。
- 从 checkpoint 恢复后继续执行。
- replay 不调用真实 worker side effect。
- checksum 不匹配时拒绝恢复。
- skill evolution transcript 能解释 candidate 拒绝、晋升、发布和回滚。
- replay skill evolution run 不产生新的 production skill release。
- RAG transcript 能解释 query、source verification、evidence acceptance、memory hit、replan 和 halted。
- replay RAG run 不产生新的真实检索、真实 MCP side effect 或真实 memory write。
- context snapshot 能解释 worker 当时看到的上下文 refs。
- replay context snapshot 不重新调用 LLM compressor。
- compression record 缺少 preserved refs 或 checksum 不匹配时拒绝 replay。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Harness 每次运行都有 event log。
- Harness 每次相位转移都有 transcript。
- 可以导出 trace。
- 可以保存和恢复 checkpoint。
- 可以 replay fake workflow。
- 可以 replay fake skill evolution workflow，且不会触发新发布。
- 可以 replay fake RAG workflow，且不会触发新检索或新写入。
- 可以 replay fake context assembly / compression workflow，且不会重新压缩或重新召回记忆。
- 不接业务，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/04-trace-checkpoint-replay.md。
要求：
1. 实现 Harness event log、transcript、trace export、checkpoint、checkpoint store、replay。
2. 复用旧 framework/events 或 checkpoint 思路可以，但旧 workflow runtime 不能接管 Harness 状态。
3. Event 和 transcript 不存大 payload，大内容使用 artifact ref。
4. PLAN、EXECUTE、VERIFY、REPLAN、HALT 每次转移都必须落 transcript。
5. Skill evolution 的 candidate、eval、promotion、release、rollback 也必须落 event/transcript。
6. Bounded Agentic RAG 的 session_started、plan_verified、step_executed、source_verified、context_pack_assembled、gate_failed、replanned、halted、context_pack_returned 也必须落 event/transcript。
7. Context Engineering 的 context_assembly_started、context_budget_checked、context_compression_verified、context_snapshot_written、context_cache_key_created 也必须落 event/transcript。
8. Replay 能复盘 gate failure、replan、halted、skill candidate 拒绝、skill 晋升、rollback、RAG query/source/evidence/memory hit 采纳或拒绝原因，以及 worker 当时看到的 context refs。
9. 添加 event、transcript、trace、checkpoint、resume、replay、skill evolution transcript、RAG transcript replay、context snapshot replay、compression record replay 测试。
10. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
11. 修改完成后提交。
全部回复和问题用中文。
```
