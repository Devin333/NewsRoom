# 阶段 6A：Reader Repair Memory / Repair RAG

## 阶段目标

在 Research 单篇论文闭环之后，加入 Reader 构建问题的自修复与记忆闭环。目标是：论文从 source/document 变成 reader payload 时，如果出现结构、表格、公式、引用、章节、证据对齐等问题，Harness 可以召回历史修复经验，调用 LLM repair worker 生成候选修复，再用确定性 gate 验证；成功经验写入记忆，重复稳定经验再进入 skill evolution。

Repair RAG 必须复用阶段 3B 的 Bounded Agentic RAG。Reader Repair 只定义问题签名、召回目标、相似度规则、修复约束和业务 gate；多轮 memory recall、source read、context pack 组装、预算和停止条件由 Harness RAG session controller 控制。

Repair proposer 和 repair verifier 必须复用阶段 3C 子 Agent 隔离。修复者不能验证自己；verifier 只能看 repair candidate、source refs、schema/gate inputs，不能看 proposer private notes。

本阶段仍不做 UI，不接旧 paper_radar，不复用旧 reader payload adapter。

## 核心判断

Reader 修复经验是一种业务型自进化：

```text
一次具体问题 -> 写入 repair episode memory
多次相似问题 -> consolidate 成 repair strategy memory
稳定有效策略 -> 进入 skill evolution candidate
通过 eval 后 -> 固化到 reader repair skill
```

不要把所有经验都直接写进 skill。记忆和 skill 的边界：

| 去向 | 适合内容 | 更新速度 | 验证要求 |
| --- | --- | --- | --- |
| Memory | 具体错误、具体论文、具体修复案例、还不确定是否通用的经验。 | 快。 | 当前 run repair gate 通过即可写 episodic memory。 |
| Skill | 反复出现、稳定有效、可写成通用规则的修复方法。 | 慢。 | 必须走阶段 3A skill evolution、held-out eval、promotion gate、rollback。 |

## 项目层与业务层边界

### Framework / Harness 层

项目层只提供通用机制，不包含论文 reader 业务词：

```text
ProblemEpisode
RepairAttempt
RepairOutcome
RepairContextPack
RepairMemoryPort
RepairConsolidationPolicy
RepairQualityGatePort
```

项目层负责：

- 记录问题 episode。
- 召回相似 repair memory。
- 控制 repair workflow 的 `PLAN -> EXECUTE -> VERIFY`。
- 控制 `max_repair_attempts`、`max_repair_replans`、`max_repair_memory_hits`。
- 控制 `max_repair_rag_rounds`、`max_repair_source_reads`。
- 写 event/transcript/checkpoint。
- 决定是否 commit memory。
- 决定是否把重复经验送入 skill evolution candidate。

项目层不负责：

- 表格、公式、citation、reader payload 的业务规则。
- 判断论文内容是否正确。
- 直接修改 Research domain model。

### Research 业务层

Research 层定义 reader 业务问题和修复规则：

```text
ReaderIssue
ReaderIssueSignature
ReaderRepairCase
ReaderRepairStrategy
ReaderRepairAttempt
ReaderRepairResult
ReaderRepairMemoryQuery
ReaderRepairContextPack
ReaderRepairRAGPolicy
```

Research 层负责：

- 检测 reader 构建问题。
- 生成业务化 error signature。
- 构造 repair memory query。
- 判断召回案例是否相似。
- 验证修复是否破坏 source lineage、章节顺序、schema、citation、table/formula fidelity。
- 将成功/失败修复转换成 memory candidate。
- 定义哪些重复模式可以进入 skill evolution。

## 新增目录

```text
business/research/
  reader_repair/
    __init__.py
    models.py
    issue_detector.py
    issue_signature.py
    repair_memory.py
    repair_context.py
    repair_service.py
    repair_gates.py
    consolidation.py
    workflow.py
  memory/
    __init__.py
    reader_repair_memory.py
```

可选 Harness 通用目录：

```text
framework/harness/repair/
  __init__.py
  models.py
  ports.py
  gates.py
  fake.py
```

如果阶段 6A 实现时发现 `framework/harness/repair` 与现有 harness control plane 能力重复，可以不建通用 repair 包，只在 `business/research/reader_repair` 内定义业务模型，并通过 `MemoryPort`、`QualityGatePort`、`ArtifactPort` 接入。

## Reader 问题类型

第一批支持：

```text
pdf_text_extraction_error
section_boundary_error
missing_required_section
formula_render_error
table_parse_error
figure_caption_mismatch
citation_link_error
reference_parse_error
claim_evidence_alignment_error
reader_payload_schema_error
long_context_truncation_error
language_mixing_error
source_lineage_missing
```

每种问题都要有：

- `issue_type`
- `severity`
- `error_signature`
- `symptom`
- `step_id`
- `source_refs`
- `payload_before_ref`
- `detector_evidence`

## 核心模型

### ReaderIssue

字段：

```text
issue_id
paper_id
run_id
step_id
issue_type
severity
error_signature
symptom
source_refs
payload_ref
detector_evidence
created_at
metadata
```

约束：

- `error_signature` 必须稳定生成，不能包含随机文本。
- `source_refs` 必须指向原始 document / section / span。
- 大 payload 只存 artifact ref。

### ReaderRepairCase

字段：

```text
repair_case_id
issue
memory_kind
repair_strategy
repair_prompt_ref
repair_attempt_refs
successful
verification_results
payload_before_ref
payload_after_ref
constraints
failure_reason
created_at
tags
metadata
```

约束：

- 成功和失败案例都要保存。
- 失败案例用于避免重复坏策略。
- 成功案例可以参与 RAG。

### ReaderRepairStrategy

字段：

```text
strategy_id
issue_type
applicability
steps
constraints
known_failures
evidence_requirements
confidence
source_case_refs
status
created_at
metadata
```

`status` 建议：

```text
candidate
validated
promoted_memory
skill_candidate_ready
deprecated
```

### ReaderRepairContextPack

字段：

```text
current_issue
similar_successful_cases
similar_failed_cases
promoted_strategies
repair_constraints
source_refs
budget_snapshot
metadata
```

要求：

- 给 LLM repair worker 的上下文只来自 context pack。
- 每个历史案例都要有 `why_retrieved` 和相似度/匹配原因。
- 不把完整历史 payload 直接塞给 LLM，只给摘要和 artifact refs。
- context pack 必须记录 RAG session id、accepted/rejected memory refs、failure case coverage 和 gap report。

## Repair RAG 流程

```text
compile_document
-> build_reader_payload
-> reader_quality_gate
-> detect_reader_issue
-> build_repair_memory_query
-> run_bounded_repair_rag
-> build_repair_context_pack
-> propose_repair_candidate
-> verify_repair_candidate
-> apply_repair
-> verify_reader_payload
-> commit_repair_episode_memory
-> consolidate_repair_memory
-> maybe_create_skill_evolution_candidate
```

### detect_reader_issue

由确定性 detector 和 schema validator 先发现问题：

- reader payload schema 失败。
- 章节导航缺失或顺序异常。
- 表格 caption 和表格内容断开。
- citation 指向不存在的 reference。
- formula 被 LLM 改写成不可信自然语言。
- source lineage 缺失。

LLM 可以辅助解释 symptom，但不能作为唯一 detector。

### recall_repair_memory

查询条件：

```text
namespace: research.reader_repair
kind: episodic/procedural
issue_type
error_signature
step_id
paper_domain
source_format
symptom
```

召回结果必须分组：

```text
similar_successful_cases
similar_failed_cases
promoted_strategies
```

不允许只召回成功案例。失败案例是避免重复踩坑的重要上下文。

### run_bounded_repair_rag

Reader Repair 召回必须进入独立 RAG session：

```text
goal: repair current ReaderIssue
allowed_memory_namespaces:
  - research.reader_repair
allowed_corpora:
  - current_paper_source
  - current_reader_payload_artifacts
operations:
  - recall_memory
  - read_source
  - verify_source
  - assemble_context
budget:
  max_rounds
  max_queries
  max_memory_hits
  max_source_reads
  max_context_items
```

Repair RAG 必须同时召回：

```text
similar_successful_cases
similar_failed_cases
promoted_strategies
current_source_context
```

Harness gate 必须检查：

| Gate | 校验内容 |
| --- | --- |
| `RepairRAGNamespaceGate` | 只能访问 `research.reader_repair` 等 workflow 允许的 namespace。 |
| `RepairRAGIssueSimilarityGate` | memory hit 必须和当前 issue_type/signature/source_format 相似。 |
| `RepairRAGFailureCaseGate` | context pack 必须包含可用失败案例或明确说明没有失败案例。 |
| `RepairRAGSourceLineageGate` | 当前 source context 必须带 source refs/span refs。 |
| `RepairRAGBudgetGate` | 不超过 repair RAG 预算。 |

LLM 不能决定哪些 memory hit 最终采用。LLM 可以解释相似性候选，但 Harness/Research gate 决定 accepted/rejected memory context。

### repair context engineering

Reader Repair 不能直接把历史案例拼进 prompt。历史修复经验必须经过：

```text
ReaderIssue
-> ReaderRepairMemoryQuery
-> Bounded Repair RAG
-> ReaderRepairContextPack
-> ContextAssembler
-> ContextEnvelope
-> Repair proposer / verifier
```

Reader Repair 的 Evidence / Memory Segment 推荐顺序：

```text
current_issue
promoted procedural repair strategies
similar successful cases
similar failed cases
current source context
repair constraints
```

要求：

- 每个 recalled case 必须有 `why_retrieved`、similarity reason、success/failure outcome 和 source refs。
- failed cases 不能因为 token 超限被优先全部删除；可以压缩摘要，但必须保留失败原因和适用边界。
- verifier 的 ContextEnvelope 只能包含 repair candidate、source refs、gate inputs 和必要历史策略摘要，不能包含 proposer private notes。
- repair context snapshot 必须写入 transcript，便于复盘为什么采用某个修复策略。
- 压缩不能丢失 issue signature、source lineage、payload_before_ref、payload_after_ref、verification result。

### propose_repair_candidate

LLM repair worker 只能输出候选：

```text
repair_summary
target_region_refs
patch_operations
expected_effect
risks
confidence
```

禁止输出：

```text
publish=true
quality_passed=true
write_memory=true
promote_skill=true
```

### verify_repair_candidate

必须使用纯函数 gate：

| Gate | 校验内容 |
| --- | --- |
| `ReaderPayloadSchemaGate` | 修复后 reader payload schema 合法。 |
| `ReaderSourceLineageGate` | 修复不丢 source refs、section refs、span refs。 |
| `ReaderLocalizedPatchGate` | 修复只作用于 issue 指向区域，不大范围重写。 |
| `ReaderCitationIntegrityGate` | citation/ref 链接仍然存在且不伪造。 |
| `ReaderTableFidelityGate` | 表格修复保留 caption、列结构、原始文本 ref。 |
| `ReaderFormulaFidelityGate` | 公式修复保留原始公式或 placeholder，不胡编公式含义。 |
| `ReaderSectionOrderGate` | 章节顺序、层级和导航不被破坏。 |
| `ReaderRepairBudgetGate` | 不超过 repair attempt/replan/memory hit 预算。 |

### commit_repair_episode_memory

写入条件：

- 当前 repair workflow 有 transcript。
- issue signature 稳定。
- repair result 有 verification result。
- 成功/失败都记录 outcome。
- memory candidate 通过 privacy/provenance gate。

写入类型：

```text
MemoryKind.EPISODIC
MemoryScope.PROJECT
namespace: research.reader_repair
```

### consolidate_repair_memory

Consolidator 定期或显式运行：

```text
query similar repair cases
group by issue_type + signature pattern
compute success rate
extract common strategy
detect failed strategy to avoid
promote strategy memory
```

晋升为 procedural memory 的条件：

- 至少 N 个相似案例。
- 成功率超过阈值。
- 没有关键 gate 回归。
- 策略可表达为通用规则。
- 有失败边界说明。

写入类型：

```text
MemoryKind.PROCEDURAL
MemoryScope.PROJECT
namespace: research.reader_repair
```

### maybe_create_skill_evolution_candidate

当 procedural repair memory 稳定后，才进入阶段 3A：

```text
ReaderRepairStrategy
-> SkillExperience / SkillPatchSet seed
-> reader-repair skill candidate
-> static gates
-> held-out eval
-> promotion gate
-> versioned skill release
```

禁止：

- repair 成功一次就写进 skill。
- 普通 reader build run 直接发布 skill。
- LLM repair worker 直接修改 `SKILL.md`。

## 与四层记忆的关系

```text
Working Memory:
  当前 reader payload、当前 issue、当前 repair context pack。

Episodic Memory:
  每次 reader issue、repair attempt、success/failure outcome。

Semantic Memory:
  从 reader 结果中固化出的论文结构、claim、evidence、section/source relations。

Procedural Memory:
  重复验证有效的 reader repair strategy，后续可变成 reader repair skill。
```

## 与 Skill Evolution 的关系

阶段 6A 产生的是业务经验和 procedural memory，不直接修改 skill。

只有当策略足够稳定时，才把它作为阶段 3A 的输入：

```text
ReaderRepairCase -> ReaderRepairStrategy -> SkillCandidate seed
```

最终 skill 可能是：

```text
research-reader-repair
research-table-repair
research-citation-repair
research-formula-repair
```

这些 skill 的发布仍然必须走 held-out eval、promotion gate 和 rollback。

## 测试要求

新增：

```text
tests/business/research/reader_repair/test_issue_detector.py
tests/business/research/reader_repair/test_repair_memory_query.py
tests/business/research/reader_repair/test_repair_rag_policy.py
tests/business/research/reader_repair/test_repair_context_pack.py
tests/business/research/reader_repair/test_repair_context_engineering.py
tests/business/research/reader_repair/test_repair_gates.py
tests/business/research/reader_repair/test_repair_memory_commit.py
tests/business/research/reader_repair/test_repair_consolidation.py
tests/business/research/integration/test_reader_repair_rag_loop.py
```

必须覆盖：

- reader payload schema 问题能生成稳定 `ReaderIssue`。
- table/citation/formula/section/source lineage 问题能生成不同 `issue_type`。
- repair memory query 能召回成功和失败案例。
- repair RAG context pack 必须包含成功案例、失败案例或明确的 failure-case gap。
- repair context pack 进入 proposer/verifier 前必须写 ContextSnapshot。
- context budget 超限时可以压缩历史案例摘要，但不能删除失败案例覆盖、issue signature、source refs 和 verification result。
- repair RAG namespace 越权被拒绝。
- repair RAG budget 耗尽时受控 halted。
- LLM repair candidate 不能直接决定质量通过、写 memory 或发布 skill。
- 修复只允许作用于 issue 指向区域。
- 修复后 source lineage 不能丢。
- 修复成功后写入 episodic repair memory。
- 修复失败也写入 failed repair case，用于后续避免重复坏策略。
- 多个相似成功案例可 consolidate 成 procedural repair strategy。
- procedural repair strategy 不会自动发布 skill。
- max repair budget 耗尽时 run 受控 halted。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness tests/business/research -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Reader repair issue、case、strategy、context pack 模型完整。
- Reader repair RAG 能召回历史成功/失败修复案例。
- Reader repair context snapshot 能解释 proposer/verifier 当时看到的历史案例、失败边界和 source refs。
- Reader repair RAG 受阶段 3B Harness RAG session controller 控制，Research 不自行实现无限补查循环。
- LLM 只生成 repair candidate，不决定通过、不写记忆、不发布 skill。
- 修复结果经过 reader repair gates。
- 成功和失败修复都能写入 episodic memory。
- 多次成功修复可 consolidate 成 procedural repair strategy。
- procedural repair strategy 只作为 skill evolution 输入，不直接修改 active skill。
- 不做 UI，不接旧 API。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/06a-reader-repair-memory.md。
要求：
1. 在 business/research 下实现 Reader Repair Memory / Repair RAG 业务自进化闭环，不做 UI，不复用旧 paper_radar。
2. 新增 reader_repair 和 memory 子模块，定义 ReaderIssue、ReaderIssueSignature、ReaderRepairCase、ReaderRepairStrategy、ReaderRepairAttempt、ReaderRepairResult、ReaderRepairContextPack。
3. Reader 构建失败时先由确定性 detector 生成 issue，再通过阶段 3B Bounded Agentic RAG 召回 research.reader_repair namespace 下的成功和失败修复案例。
4. ReaderRepairContextPack 进入 proposer/verifier 前必须通过阶段 3D ContextAssembler，写入 ContextSnapshot；不能直接拼 prompt。
5. Repair proposer 和 repair verifier 必须复用阶段 3C SubAgent Isolation；verifier 不能看到 proposer private notes、raw history 或 hidden prompt。
6. Repair RAG 必须有 ReaderRepairRAGPolicy，并启用 RepairRAGNamespaceGate、RepairRAGIssueSimilarityGate、RepairRAGFailureCaseGate、RepairRAGSourceLineageGate、RepairRAGBudgetGate。
7. LLM repair worker 只能生成 repair candidate，不能决定 quality_passed、write_memory、publish、promote_skill。
8. 实现 ReaderPayloadSchemaGate、ReaderSourceLineageGate、ReaderLocalizedPatchGate、ReaderCitationIntegrityGate、ReaderTableFidelityGate、ReaderFormulaFidelityGate、ReaderSectionOrderGate、ReaderRepairBudgetGate。
9. 修复成功和失败都要写入 episodic repair memory，包含 issue signature、repair strategy、verification result、payload refs、source refs。
10. 多个相似成功案例可 consolidate 成 procedural repair strategy，但不能自动发布 skill。
11. procedural repair strategy 只能作为阶段 3A skill evolution candidate 的输入。
12. 添加 issue detector、repair memory query、repair RAG policy、repair context pack、repair context engineering、repair gates、memory commit、consolidation、repair RAG loop、repair proposer/verifier 隔离测试。
13. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness tests/business/research -q、openspec validate harness-research-runtime --strict。
14. 修改完成后提交。
全部回复和问题用中文。
```
