# 阶段 3B：Bounded Agentic RAG

## 阶段目标

在 Harness 控制平面下实现有界 Agentic RAG。目标不是做一次性检索，也不是让 Agent 自己决定搜什么、读什么、何时停止，而是让 Harness 按 `PLAN -> EXECUTE -> VERIFY` 控制多轮检索、读取、验证、补查、上下文组装和停止条件。

本阶段仍然属于框架层，不接 Research 业务细节，不做 UI，不依赖旧 paper_radar。

## 核心定义

普通 RAG 是：

```text
query -> retrieve -> stuff context -> generate
```

Bounded Agentic RAG 是：

```text
retrieval_goal
-> plan_retrieval
-> verify_plan
-> execute_retrieval
-> verify_sources
-> identify_evidence_gaps
-> optionally_replan
-> assemble_context_pack
-> verify_context_pack
```

核心原则：

| 原则 | 要求 |
| --- | --- |
| Harness 控制检索流程 | Harness 决定是否搜索、搜索几轮、读取哪些 source、何时停止。 |
| LLM 只生成候选计划 | LLM 可以提出 query expansion、source reading suggestion、evidence gap summary，但不能执行路由决策。 |
| RetrievalPort 只做检索 | RetrievalPort 返回候选证据和 source refs，不决定 evidence 是否被采纳。 |
| VERIFY 使用纯函数 gate | 查询白名单、scope、去重、证据覆盖、来源质量、冲突、预算、上下文大小都由 deterministic gate 校验。 |
| RAG 全程可回放 | 每轮 query、source read、verification、replan、halt 都写 transcript/event log。 |
| Memory 受控接入 | RAG 可以召回 memory，但是否写入 memory、是否 consolidate 由 Harness 和 MemoryGate 决定。 |

## 新增目录

```text
framework/harness/rag/
  __init__.py
  models.py
  session.py
  planner.py
  context_assembler.py
  source_verifier.py
  gates.py
  policy.py
  fake.py
```

如果实现时发现 `planner.py`、`source_verifier.py` 或 `context_assembler.py` 更适合放在已有 `framework/harness/retrieval` 下，可以保留包边界为 `framework/harness/rag`，内部通过 adapter 调用已有 retrieval 模块。不要把多轮 RAG 控制逻辑写进 `business/research`。

## 核心模型

### RAGSessionSpec

字段建议：

```text
session_id
run_id
workflow_id
step_id
goal
allowed_corpora
allowed_memory_namespaces
allowed_tools
source_policy
budget
context_policy
metadata
```

约束：

- `allowed_corpora` 必须显式声明，不能让 LLM 自由选择数据源。
- `allowed_memory_namespaces` 必须显式声明，例如 `research.reader_repair`。
- `allowed_tools` 必须来自 workflow spec 或 Harness policy。

### RetrievalGoal

字段建议：

```text
goal_id
question
required_evidence_types
target_entities
known_context_refs
missing_information
constraints
metadata
```

### RetrievalPlanCandidate

由 LLM 或 deterministic planner 生成，但只作为候选。

字段建议：

```text
candidate_id
queries
source_reading_plan
memory_recall_plan
expected_evidence
expected_gaps
risks
confidence
metadata
```

禁止字段：

```text
next_step
quality_passed
write_memory
publish_artifact
halt_workflow
promote_skill
```

### RetrievalStepSpec

字段建议：

```text
step_id
operation
query
corpus
memory_namespace
source_refs
max_results
max_source_reads
timeout_seconds
metadata
```

`operation` 建议：

```text
search_corpus
read_source
recall_memory
verify_source
check_gap
assemble_context
```

### RetrievalStepResult

字段建议：

```text
step_id
operation
items
source_refs
memory_refs
artifact_refs
errors
latency_ms
metadata
```

### EvidenceCandidate

字段建议：

```text
evidence_id
title
summary
source_ref
span_refs
evidence_type
claim_refs
confidence
freshness
lineage
metadata
```

### RAGContextPack

字段建议：

```text
context_pack_id
goal
accepted_evidence
rejected_evidence
conflicting_evidence
memory_context
source_refs
gap_report
budget_snapshot
assembly_summary
metadata
```

要求：

- 给 LLM 的上下文必须来自 `RAGContextPack`。
- context pack 不存大 payload，大内容用 artifact/source refs。
- 每个 evidence 都要有 lineage。
- 被拒绝和冲突证据也要记录，便于复盘。
- `RAGContextPack` 不是最终 prompt；进入 LLMWorkerPort 前必须交给阶段 3D 的 `ContextAssembler`，变成 Evidence / Memory Segment。
- context pack 过大时，只能压缩 evidence / memory 摘要，不能丢失 source refs、accepted/rejected/conflicting 标记、gap report 和 budget snapshot。

### RAGBudget

字段建议：

```text
max_rounds
max_replans
max_queries
max_source_reads
max_memory_hits
max_context_items
max_context_tokens
max_worker_calls
```

预算必须同时受 run-level Harness budget 约束。超过预算必须进入受控 `halted` 或返回 `insufficient_evidence`，不能无限补查。

## PLAN / EXECUTE / VERIFY 流程

### PLAN

Harness 根据 `RAGSessionSpec`、workflow step、已有 state、memory policy 和 gate 结果生成本轮 retrieval plan。

LLM 可以作为 planner worker 生成 `RetrievalPlanCandidate`，但 Harness 必须先过 gate：

| Gate | 校验内容 |
| --- | --- |
| `RAGPlanSchemaGate` | plan candidate schema 合法，无非法流程字段。 |
| `RAGToolAllowlistGate` | 只使用 workflow 声明的 corpus、memory namespace 和 tool。 |
| `RAGQueryDedupGate` | query 不重复，不和本 session 已执行 query 等价。 |
| `RAGScopeGate` | 查询目标不越过允许的 corpus / paper / project scope。 |
| `RAGBudgetGate` | 本轮计划不会超过 rounds、queries、source reads、memory hits、worker calls。 |

### EXECUTE

Harness 逐个执行已批准的 `RetrievalStepSpec`：

```text
search_corpus -> RetrievalPort
read_source -> RetrievalPort 或 MCPToolPort
recall_memory -> MemoryPort
verify_source -> SourceVerifier
assemble_context -> ContextAssembler
```

要求：

- RetrievalPort 不能直接写 HarnessState 的最终决策。
- MemoryPort recall 只能返回 memory refs/context candidates。
- MCPToolPort 必须经过工具白名单、side effect policy、timeout 和审计。
- 大结果必须转成 artifact ref。

### VERIFY

每轮结果必须经过 deterministic gate：

| Gate | 校验内容 | 失败处理 |
| --- | --- | --- |
| `RAGSourceQualityGate` | source 是否可信、是否有 lineage、是否符合 freshness/source policy。 | replan、drop source 或 fail。 |
| `RAGEvidenceCoverageGate` | required evidence type 是否覆盖，主要 claim 是否有证据。 | replan 或 insufficient_evidence。 |
| `RAGEvidenceConflictGate` | 是否存在互相冲突证据，并记录 conflict report。 | replan 或要求人工 gate。 |
| `RAGContextSizeGate` | context items/token 不超过限制。 | trim、summarize 或 fail。 |
| `RAGMemoryRelevanceGate` | memory hit 是否和当前 goal/issue 相似。 | drop memory hit。 |
| `RAGLineageGate` | accepted evidence 必须保留 source refs/span refs。 | fail 或 replan。 |
| `RAGBudgetGate` | 不超过 session 和 run 预算。 | halted。 |

VERIFY 后 Harness 只能做显式决策：

```text
continue_retrieval
replan_queries
read_more_sources
assemble_context
return_context_pack
insufficient_evidence
wait_for_approval
halted
failed
```

## 与七层端口的关系

Bounded Agentic RAG 不替代阶段 3 的 RetrievalPort / MemoryPort / MCPToolPort，而是它们上方的一层 Harness orchestration：

```text
Harness Scheduler
-> RAG Session Controller
-> RetrievalPort / MemoryPort / MCPToolPort
-> SourceVerifier / ContextAssembler
-> RAG VERIFY Gates
-> RAGContextPack
-> ContextAssembler
-> ContextEnvelope
```

端口边界：

| 端口 | 在 RAG 中的职责 |
| --- | --- |
| `LLMWorkerPort` | 生成 retrieval plan candidate、gap summary、evidence summary candidate。 |
| `RetrievalPort` | 检索 corpus、读取 source、返回候选 evidence。 |
| `MemoryPort` | 召回 episodic / semantic / procedural memory。 |
| `MCPToolPort` | 访问外部工具或远程资料源，受白名单和审批控制。 |
| `QualityGatePort` | 执行 RAG gate 和 context pack gate。 |
| `ArtifactPort` | 保存大 source/result/context snapshot。 |

## 与 Context Engineering 的关系

阶段 3D 负责把 RAG 输出装配进 worker 上下文：

```text
RAGContextPack
-> ContextAssembler
-> Evidence / Memory Segment
-> ContextBudgetGate
-> ContextSnapshot
-> LLMWorkerPort
```

RAG session controller 不直接拼 prompt。它只产出可验证、可回放、带 provenance 的 context pack。

要求：

- RAG gate 决定 evidence 是否可进入 context pack。
- Context gate 决定 context pack 如何进入 worker 上下文。
- prompt token 超限时，优先压缩 rejected/conflicting evidence 摘要，再压缩 accepted evidence 摘要；不能删除 source refs。
- replay 时使用 `RAGContextPack`、`ContextSnapshot` 和 artifact refs 重建上下文，不重新检索。

## 与四层记忆的关系

```text
Working Memory:
  当前 RAG session、已执行 query、accepted/rejected evidence、budget snapshot。

Episodic Memory:
  一次检索失败、一次 reader repair 召回、一次证据冲突处理。

Semantic Memory:
  被验证后的论文事实、claim、section、evidence relation。

Procedural Memory:
  多次验证有效的检索策略、reader repair strategy、source selection rule。
```

RAG 的职责是召回和组装上下文，不是直接把所有经验写入长期记忆。写入必须经过 MemoryGate、provenance gate 和 Harness decision。

## 与 Skill Evolution 的关系

RAG session 可以产生 skill evolution experience：

```text
failed_query_pattern
successful_query_pattern
source_selection_strategy
evidence_gap_resolution_strategy
reader_repair_retrieval_strategy
```

这些经验先进入 memory 或 experience store。只有重复稳定、通过离线 eval 的策略，才能作为阶段 3A 的 skill candidate 输入。

禁止：

- RAG 成功一次就改 active skill。
- LLM planner 直接修改 skill。
- RAG gate 失败时通过放宽 skill 或 gate 来绕过问题。

## Research 接入方式

阶段 5/6/6A 接入时，Research 只表达业务目标和业务规则，不实现通用 RAG 调度器。

推荐接入点：

| Research 场景 | RAG 作用 |
| --- | --- |
| `build_evidence_pack` | 多轮读取论文 sections、tables、figures、references，形成 evidence pack。 |
| `verify_claims` | 针对 claim 补查 method、experiment、limitation、related work，验证是否有支撑。 |
| `ask_paper` | 根据用户问题构造 RetrievalGoal，召回论文事实和已验证分析。 |
| `reader_repair` | 召回历史 reader issue 成功/失败案例和 procedural repair strategy。 |
| `skill_evolution` | 汇总稳定检索/修复策略作为 skill candidate seed。 |

Research 层可以定义：

```text
ResearchRetrievalGoal
ResearchEvidenceNeed
ResearchRAGPolicy
ResearchRAGContextProjection
```

但不应该定义通用 RAG loop、retry loop 或 tool routing。

## Transcript / Trace 要求

每个 RAG session 必须写入：

```text
rag_session_started
rag_plan_candidate_created
rag_plan_verified
rag_step_executed
rag_source_verified
rag_context_pack_assembled
rag_gate_failed
rag_replanned
rag_halted
rag_context_pack_returned
```

Trace 必须能解释：

- 为什么发起这轮检索。
- 为什么选择这些 query。
- 哪些 source 被接受、拒绝或标记冲突。
- 为什么继续补查或停止。
- memory hit 为什么被采用或丢弃。
- context pack 为什么满足或不满足目标。
- 如果 halted，触发的是哪个预算或 gate。

## Fake implementation

新增 fake：

```text
FakeRAGPlanner
FakeRAGSessionController
FakeSourceVerifier
FakeContextAssembler
FakeRAGGateSuite
```

Fake 数据必须像真实研究材料：

```text
paper sections
method paragraphs
experiment table snippets
citation refs
reader repair cases
failed repair cases
procedural strategies
```

不要使用 `"foo"`、`"bar"` 这类无法表达检索规则的数据。

## 测试要求

新增：

```text
tests/framework/harness/rag/test_rag_models.py
tests/framework/harness/rag/test_rag_plan_gates.py
tests/framework/harness/rag/test_rag_session_controller.py
tests/framework/harness/rag/test_rag_context_assembler.py
tests/framework/harness/rag/test_rag_transcript.py
tests/framework/harness/rag/test_fake_rag_runtime.py
```

必须覆盖：

- LLM planner 返回非法 `next_step`、`write_memory`、`quality_passed` 时被 gate 拒绝或忽略。
- query 去重生效。
- corpus/tool/memory namespace 越权被拒绝。
- source 没有 lineage 被拒绝。
- evidence coverage 不足时触发 replan。
- max rounds / max queries / max source reads 耗尽时受控 halted。
- memory recall 同时保留成功和失败案例。
- context pack 不超过大小限制。
- RAG transcript 记录每次 plan、execute、verify、replan、halt。
- fake runtime 能返回可序列化的 RAGContextPack。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- `framework/harness/rag` 有完整模型、session controller、gate、policy、fake。
- RAG loop 由 Harness 控制，不在业务层自行循环。
- LLM 只生成 retrieval plan/context summary candidate。
- Retrieval/Memory/MCP 调用都受 workflow spec、policy、budget、gate 约束。
- 每轮 RAG 都能导出 transcript 和 trace。
- 预算耗尽进入受控 halted，不会无限补查。
- 不接 Research，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/03b-bounded-agentic-rag.md。
要求：
1. 在 framework/harness/rag 下实现 Bounded Agentic RAG 框架能力。
2. 定义 RAGSessionSpec、RetrievalGoal、RetrievalPlanCandidate、RetrievalStepSpec、RetrievalStepResult、EvidenceCandidate、RAGContextPack、RAGBudget。
3. 实现 RAG session controller，所有检索都必须走 PLAN -> EXECUTE -> VERIFY。
4. LLM 只能生成 retrieval plan candidate、gap summary、evidence summary candidate，不能决定 next_step、write_memory、quality_passed、publish_artifact、promote_skill。
5. RAG 调用 RetrievalPort、MemoryPort、MCPToolPort、QualityGatePort、ArtifactPort，不直接依赖真实实现。
6. 实现 RAGPlanSchemaGate、RAGToolAllowlistGate、RAGQueryDedupGate、RAGScopeGate、RAGSourceQualityGate、RAGEvidenceCoverageGate、RAGEvidenceConflictGate、RAGContextSizeGate、RAGMemoryRelevanceGate、RAGLineageGate、RAGBudgetGate。
7. max_rounds、max_replans、max_queries、max_source_reads、max_memory_hits、max_context_items、max_context_tokens、max_worker_calls 必须防止无限检索和无限补查。
8. 每次 rag plan、execute、verify、replan、halt、context_pack_returned 都要写 transcript/event log。
9. RAGContextPack 进入 LLM 前必须通过阶段 3D ContextAssembler，写入 ContextSnapshot，不能由 RAG 直接拼 prompt。
10. 添加 RAG models、plan gates、session controller、context assembler、transcript、fake runtime 测试。
11. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
12. 修改完成后提交。
全部回复和问题用中文。
```
