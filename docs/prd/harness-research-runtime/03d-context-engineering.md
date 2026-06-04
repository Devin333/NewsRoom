# 阶段 3D：Context Engineering

## 阶段目标

在 Harness 控制平面下实现上下文装配、上下文预算、压缩链路、Prompt Prefix Cache 友好布局和上下文快照。目标不是让 LLM 自己“记得该看什么”，而是由 Harness 明确决定每个 worker、RAG session、SubAgent、Skill 调用能看到哪些上下文、哪些必须裁剪、哪些必须压缩、哪些必须保留为可回放 artifact。

本阶段仍属于框架层，不接 Research 业务实现，不做 UI，不依赖旧 paper_radar。

## 真实依赖与接口预留

| 类型 | 内容 |
| --- | --- |
| 真实实现依赖 | 阶段 3 的 worker/quality/artifact 端口，阶段 3C 的 `SubAgentContextEnvelope` 和 transcript refs。 |
| 真实输出 | `ContextEnvelope`、`ContextSnapshot`、`ContextBudget`、`ContextCachePolicy`、`CompressionRecord`。 |
| 接口预留 | 阶段 3B 会把 `RAGContextPack` 接入 Evidence / Memory Segment；阶段 3A 会把 skill eval、candidate 和 experience 输入接入 ContextEnvelope。 |
| 禁止提前实现 | 不在本阶段实现 RAG session controller、skill evolution 生命周期、Research 业务上下文。 |

## 参考原则

本阶段吸收这些外部架构思想，但不照搬：

| 来源 | 可借鉴点 | 在本项目中的落地方式 |
| --- | --- | --- |
| LangGraph | 长运行、有状态、可持久化、可追踪的 agent runtime。 | Harness state、context snapshot、checkpoint、trace 统一由控制平面管理。 |
| Google ADK workflow agents | workflow agent 用预定义逻辑编排 sub-agent，执行顺序不交给模型。 | ContextEnvelope 由 Harness 构造，LLM worker 不决定上下文段落和路由。 |
| OpenAI Agents manager pattern | manager 持有控制权，specialist agent 只处理有界子任务。 | 子 Agent 只收到独立 context envelope，输出 candidate，由 Harness gate 验收。 |
| Conductor workflow | 声明式任务、switch/dynamic route、human/wait/system task。 | 上下文策略写进 workflow spec，人工 gate 和 halt 都有 transcript。 |
| Temporal durable execution | event history、checkpoint、replay。 | 上下文装配、压缩、裁剪、cache key 都落 event/transcript，replay 不重新询问 LLM。 |
| MCP | tools/resources/prompts 边界和授权。 | MCP 资源进入上下文前必须有 provenance、consent、tool policy 和 size gate。 |
| Prompt caching 研究与厂商实践 | 静态前缀稳定、动态内容靠后、工具结果不要污染 cache prefix。 | 上下文分成 stable prefix 和 dynamic tail，只有稳定段参与 prefix cache。 |

## 核心判断

不建议强行做“七段式上下文”。Research 场景里，真正需要稳定复用的是规则、workflow 和 worker contract；真正会频繁变化的是 run state、证据、记忆和当前任务。所以本项目采用：

```text
6 段上下文装配
+ 5 级压缩链路
+ ContextEnvelope / ContextSnapshot / ContextBudget / ContextCacheKey
```

## 上下文六段

### 1. Global Policy Segment

稳定全局规则，所有 worker 都必须遵守。

内容：

```text
Harness 是唯一控制者
LLM 只生成 candidate
PLAN -> EXECUTE -> VERIFY
工具白名单
memory 写入规则
skill evolution 禁止事项
输出禁止字段
```

要求：

- 不能压缩。
- 不能由业务运行时动态改写。
- 不能混入当前论文、当前用户问题、工具结果。
- 适合放在 prompt cache stable prefix。

### 2. Workflow Segment

当前 workflow 的显式流程、当前 phase、step、预算和允许路由。

内容：

```text
workflow_id
step_id
phase
allowed_routes
max_turns
max_replans
max_retries_per_step
max_worker_calls
allowed_tools
allowed_memory_namespaces
quality_gates
```

要求：

- workflow spec 版本稳定时可进入 stable prefix。
- 当前 phase / step / budget snapshot 属于 dynamic tail。
- LLM 可以看到当前 step 的 allowed action，但不能返回 next_step 控制路由。

### 3. Worker Contract Segment

worker 或 SubAgent 的角色契约。

内容：

```text
worker_type
worker_id
input_schema
output_schema
forbidden_fields
tool_allowlist
memory_namespace_policy
artifact_policy
expected_candidate_kind
```

要求：

- schema 不能压缩。
- forbidden fields 必须显式列出。
- 对子 Agent，必须来自 `SubAgentContextEnvelope`。
- 对 skill worker，必须包含 skill name、version、package hash。

### 4. Run State Segment

当前 run 的短摘要和状态引用。

内容：

```text
run_id
paper_id 或 domain-neutral entity refs
completed_steps
current_failures
accepted_artifact_refs
last_gate_results
budget_snapshot
checkpoint_ref
```

要求：

- 只放当前 worker 必要信息。
- 不放完整 transcript。
- 大内容只放 artifact refs。
- 可以从 transcript/checkpoint 重新构造。

### 5. Evidence / Memory Segment

RAG、记忆、source refs 和 evidence refs。

内容：

```text
RAGContextPack
accepted_evidence
rejected_evidence
conflicting_evidence
memory_hits
source_refs
gap_report
why_retrieved
why_rejected
```

要求：

- 只能来自 Harness 批准的 RAGContextPack 或 MemoryPort recall 结果。
- 每条 evidence / memory hit 必须带 provenance。
- 成功案例和失败案例都要保留摘要，尤其是 reader repair。
- 不允许把未通过 gate 的 raw retrieval result 直接塞给 LLM。

### 6. Current Task Segment

当前 worker 的具体任务。

内容：

```text
current_instruction
input_payload
expected_output_format
quality_reminders
```

要求：

- 放在最后。
- 每次 worker call 都可以变化。
- 不参与 stable prefix cache。
- 不包含长期规则，避免和 Global Policy Segment 打架。

## Stable Prefix / Dynamic Tail

推荐布局：

```text
Stable Prefix:
  1. Global Policy Segment
  2. Workflow Segment 的稳定部分
  3. Worker Contract Segment 的稳定 schema/policy

Dynamic Tail:
  4. Run State Segment
  5. Evidence / Memory Segment
  6. Current Task Segment
```

实现要求：

- `ContextAssembler` 必须按固定顺序组装。
- stable prefix 必须有可计算的 `ContextCacheKey`。
- dynamic tail 变化不能改变 stable prefix 的文本顺序和结构。
- 工具结果、RAG 结果、用户笔记、reader payload、transcript 摘要都不能放进 stable prefix。
- 如果模型或 provider 不支持显式 prompt cache，也要保持同样布局，便于未来接入。

## 五级压缩链路

### C0 Raw

原始材料，只存在 artifact/source store，不直接长期塞进 prompt。

示例：

```text
raw transcript
tool result
PDF parse result
HTML source
LLM raw output
reader payload before/after
```

### C1 Canonical Records

结构化记录，可用于 replay、gate 和索引。

示例：

```text
HarnessEvent
TranscriptEntry
SourceRef
EvidenceCandidate
MemoryRecord
GateResult
WorkerCallRecord
```

### C2 Step Summary

单个 step 的输入、输出、失败、决策、引用摘要。

示例：

```text
step_id
phase
input_refs
output_refs
decision
gate_failures
accepted_refs
rejected_refs
```

### C3 Run Rolling Summary

当前 run 的滚动摘要，用于替代长 transcript。

示例：

```text
completed_steps
current_goal
known_gaps
important_decisions
open_failures
budget_usage
artifact_refs
```

### C4 Long-term Memory / Index

跨 run 固化后的记忆和索引。

示例：

```text
episodic memory
semantic memory
procedural memory
reader repair strategy
benchmark graph
method graph
skill experience index
```

## 不允许压缩的内容

这些内容必须保持原文或结构化 schema，不走 LLM 摘要压缩：

```text
Global Policy
workflow route table
input/output schema
forbidden_fields
quality gate definition
tool allowlist
memory namespace policy
skill promotion policy
source refs
artifact refs
budget values
```

原因很简单：这些是控制平面规则，压缩后语义漂移会让 Harness 失去确定性。

## 新增目录

```text
framework/harness/context/
  __init__.py
  models.py
  assembler.py
  budget.py
  cache.py
  compression.py
  snapshot.py
  gates.py
  fake.py
```

## 核心模型

### ContextEnvelope

字段建议：

```text
context_envelope_id
run_id
workflow_id
step_id
phase
worker_id
worker_type
segments
budget
cache_policy
snapshot_ref
metadata
```

约束：

- 每次 worker call 必须有一个 ContextEnvelope。
- ContextEnvelope 只描述本次调用能看到什么，不保存大 payload。
- 子 Agent 的 ContextEnvelope 必须和 `SubAgentContextEnvelope` 可互相投影。

### ContextSegment

字段建议：

```text
segment_id
segment_type
content_ref
summary
token_estimate
compression_level
provenance_refs
cache_scope
metadata
```

`segment_type` 建议：

```text
global_policy
workflow
worker_contract
run_state
evidence_memory
current_task
```

### ContextBudget

字段建议：

```text
max_input_tokens
max_output_tokens
max_context_segments
max_evidence_items
max_memory_items
max_artifact_refs
reserved_output_tokens
compression_threshold
metadata
```

### ContextCachePolicy

字段建议：

```text
cache_enabled
stable_prefix_segments
dynamic_tail_segments
cache_key
provider_hint
ttl_hint
metadata
```

### ContextSnapshot

字段建议：

```text
context_snapshot_id
context_envelope_id
run_id
step_id
phase
segment_refs
assembled_prompt_ref
token_estimate
cache_key
checksum
created_at
metadata
```

### CompressionRecord

字段建议：

```text
compression_id
run_id
source_ref
source_level
target_level
summary_ref
lost_fields
preserved_refs
gate_results
created_at
metadata
```

## Context Assembler 流程

```text
collect_policy_segments
collect_workflow_segments
collect_worker_contract
collect_run_state
collect_rag_and_memory_context
collect_current_task
apply_context_budget
compress_dynamic_history_if_needed
verify_context_envelope
write_context_snapshot
return_context_envelope
```

要求：

- `ContextAssembler` 不调用 LLM 做流程决策。
- 如果需要 LLM 压缩历史，只能生成 summary candidate，再由 gate 验证 source refs、lost fields 和 forbidden loss。
- 大 payload 必须先写 artifact，再通过 ref 进入 context。
- 每次装配都必须产生 snapshot 或 snapshot ref。

## Context Gates

| Gate | 校验内容 | 失败处理 |
| --- | --- | --- |
| `ContextSegmentOrderGate` | 六段顺序固定，stable prefix 在 dynamic tail 前。 | rebuild context 或 fail。 |
| `ContextStablePrefixGate` | stable prefix 不含工具结果、用户私有记忆、RAG 动态结果。 | move to dynamic tail 或 fail。 |
| `ContextSchemaPreservationGate` | schema、forbidden_fields、gate definition 未被压缩。 | fail。 |
| `ContextBudgetGate` | token、segment、evidence、memory、artifact ref 不超预算。 | compress dynamic tail、trim low-priority evidence 或 halted。 |
| `ContextProvenanceGate` | evidence、memory、tool result 均有 provenance/source refs。 | drop item 或 fail。 |
| `ContextPrivacyGate` | 用户笔记、阅读历史、私有 memory 符合 namespace 和 consent policy。 | redact 或 fail。 |
| `ContextCompressionLossGate` | 压缩不能丢 source refs、decision、gate failure、budget、error。 | reject summary。 |
| `ContextReplayGate` | context snapshot 能从 event/transcript/artifact refs 重建。 | fail。 |
| `ContextCacheKeyGate` | cache key 只由稳定段、workflow version、worker contract version 生成。 | fail。 |

## RAG 接入

Bounded Agentic RAG 输出的 `RAGContextPack` 不能直接等价于最终 prompt。必须经过 Context Engineering：

```text
RAGContextPack
-> ContextAssembler
-> Evidence / Memory Segment
-> ContextBudgetGate
-> ContextProvenanceGate
-> ContextSnapshot
-> LLMWorkerPort
```

Research reader repair 召回的历史成功/失败案例也是同理：

```text
ReaderRepairContextPack
-> Evidence / Memory Segment
-> failure case coverage gate
-> current task segment
```

## Memory 接入

记忆不是“越多越好”。MemoryPort recall 结果进入上下文前必须分层：

| 记忆层 | 是否进入当前上下文 | 默认策略 |
| --- | --- | --- |
| Working Memory | 是。 | 当前 step 必要状态，放 Run State Segment。 |
| Episodic Memory | 选择性进入。 | 只放相似案例摘要、成功/失败 outcome、refs。 |
| Semantic Memory | 选择性进入。 | 只放已验证事实和 source refs。 |
| Procedural Memory | 优先进入。 | 放稳定策略、适用条件、失败边界。 |

Reader Repair 的问题记忆推荐顺序：

```text
current issue
-> procedural repair strategy
-> similar successful cases
-> similar failed cases
-> current source context
```

## SubAgent 接入

子 Agent 的上下文必须通过阶段 3C 的隔离机制：

```text
ContextEnvelope
-> SubAgentContextEnvelope
-> SubAgentInvocation
```

要求：

- 子 Agent 不能看到 parent raw messages。
- 子 Agent 不能看到 sibling private notes。
- 子 Agent 不能继承 sibling tool allowlist。
- 子 Agent context snapshot 必须能被父 trace 引用。

## Trace / Checkpoint / Replay 接入

每次上下文装配必须写入：

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

Replay 要求：

- replay 不重新调用 LLM 生成摘要。
- replay 使用已有 `CompressionRecord`、`ContextSnapshot`、artifact refs 重建上下文。
- checksum 不匹配时拒绝 replay。
- trace 能解释某个 worker 当时看到了哪些 context refs，以及哪些内容被裁剪或压缩。

## Fake implementation

新增 fake：

```text
FakeContextAssembler
FakeContextBudgetEstimator
FakeContextCompressor
FakeContextSnapshotStore
FakeContextGateSuite
FakeContextCachePolicyBuilder
```

Fake 数据要像真实运行材料：

```text
workflow policy
paper section refs
reader issue refs
successful repair memory
failed repair memory
gate failure records
artifact refs
```

不要使用 `"foo"`、`"bar"` 这类无法表达上下文规则的数据。

## 测试要求

新增：

```text
tests/framework/harness/context/test_context_models.py
tests/framework/harness/context/test_context_assembler.py
tests/framework/harness/context/test_context_budget.py
tests/framework/harness/context/test_context_cache_policy.py
tests/framework/harness/context/test_context_compression.py
tests/framework/harness/context/test_context_snapshot.py
tests/framework/harness/context/test_context_gates.py
tests/framework/harness/context/test_fake_context_runtime.py
```

必须覆盖：

- ContextEnvelope 可序列化。
- 六段顺序固定。
- stable prefix 不包含动态 evidence、tool result、memory hit。
- schema、gate definition、tool allowlist、forbidden_fields 不会被压缩。
- ContextBudgetGate 能触发动态尾部压缩或裁剪。
- 压缩保留 source refs、artifact refs、gate failures、budget snapshot。
- cache key 只依赖稳定段和版本，不依赖当前论文内容。
- 每次 context assembly 都写 snapshot。
- replay 可根据 snapshot 和 artifact refs 重建 context。
- RAGContextPack 进入 prompt 前必须通过 ContextGate。
- SubAgent context 不包含 parent raw messages 或 sibling private notes。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- `framework/harness/context` 有完整模型、assembler、budget、cache、compression、snapshot、gate、fake。
- 每次 worker call 都有 ContextEnvelope 和 ContextSnapshot。
- 上下文分为 stable prefix 和 dynamic tail。
- 动态历史可以压缩，但控制规则、schema、gate、source refs 不会被压缩丢失。
- RAG、Memory、SubAgent、Skill worker 都通过 ContextEnvelope 接收上下文。
- Trace / replay 能解释每个 worker 当时看到的上下文。
- 不接 Research，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/03d-context-engineering.md。
要求：
1. 在 framework/harness/context 下实现 Context Engineering 框架能力。
2. 定义 ContextEnvelope、ContextSegment、ContextBudget、ContextCachePolicy、ContextSnapshot、CompressionRecord。
3. 实现 6 段上下文装配：Global Policy、Workflow、Worker Contract、Run State、Evidence / Memory、Current Task。
4. stable prefix 只能包含稳定规则、稳定 workflow、稳定 worker contract；dynamic tail 放 run state、RAG/memory、当前任务。
5. 实现 ContextAssembler、ContextBudgetEstimator、ContextCachePolicyBuilder、ContextCompressor、ContextSnapshotStore。
6. 实现 ContextSegmentOrderGate、ContextStablePrefixGate、ContextSchemaPreservationGate、ContextBudgetGate、ContextProvenanceGate、ContextPrivacyGate、ContextCompressionLossGate、ContextReplayGate、ContextCacheKeyGate。
7. 压缩只允许作用于动态历史、工具结果摘要、RAG evidence 摘要、memory 摘要；不允许压缩 Global Policy、schema、gate definition、tool allowlist、source refs、budget。
8. RAGContextPack、Memory recall、SubAgentContextEnvelope、Skill worker input 都必须通过 ContextEnvelope 进入 worker。
9. 每次 context assembly 必须写 ContextSnapshot 和 transcript/event log，replay 不重新调用 LLM 生成摘要。
10. 添加 context models、assembler、budget、cache policy、compression、snapshot、gates、fake runtime 测试。
11. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
12. 修改完成后提交。
全部回复和问题用中文。
```
