# 阶段 6：Research 单篇论文闭环

## 阶段目标

用新 Harness 跑通 Research 单篇论文后端闭环。使用 fake LLM、fake repository、fake source provider、fake artifact store。阶段 6 不做 UI，不接旧 paper API，不复用旧 paper_radar。

Research 单篇论文闭环必须使用 Harness 的 `PLAN -> EXECUTE -> VERIFY` 有界状态机。每轮分析、验证、返工都要经过纯函数 gate，超过 `max_replans` 或 `max_turns` 时必须受控 `halted`，不能无限修复。

Research 可以消费 active skill version，并把运行结果记录为 `SkillExperience`，但普通论文分析 run 不允许自动晋升或发布 skill。Skills 自进化必须作为独立离线/admin workflow 运行。

Reader payload 构建失败时，阶段 6 只需要能产出明确 failure 和 trace；完整 Reader Repair Memory / Repair RAG 闭环在阶段 6A 实现。

阶段 6 的证据构建和 claim 验证应使用阶段 3B 的 Bounded Agentic RAG。Research 负责构造论文领域 `ResearchRetrievalGoal` 和 `ResearchRAGPolicy`，Harness 负责多轮检索、读取、补查、VERIFY gate、预算和 transcript。

## 目标流程

```text
load_paper_source
-> compile_document
-> run_bounded_research_rag
-> build_evidence_pack
-> analyze_structure
-> analyze_contribution
-> analyze_experiments
-> verify_claims
-> quality_gate
-> build_reader_payload
-> publish_artifacts
```

## Application Service

新增或完善：

```text
business/research/application/analyze_paper.py
business/research/application/build_reader.py
business/research/application/ask_paper.py
```

### AnalyzePaperUseCase

输入：

```text
paper_id
source_ref 或 paper metadata
run_id
options
```

输出：

```text
ResearchAnalysisResult
run_id
analysis
quality
reader_payload_ref
artifact_refs
trace_ref
```

职责：

- 组装 HarnessRunSpec。
- 注入 Research workflow spec。
- 调用 Harness。
- 将 Harness 输出投影成 Research result。

不允许：

- 直接调用 LLM。
- 直接写 infrastructure。
- 调用旧 paper_radar orchestrator。

### Research RAG 使用边界

`AnalyzePaperUseCase` 可以把论文分析需求投影成：

```text
ResearchRetrievalGoal
ResearchEvidenceNeed
ResearchRAGPolicy
```

然后交给 Harness RAG session controller 执行。

不允许：

- 在 `business/research` 里手写 while loop 做无限补查。
- 让 LLM 根据回答决定是否继续检索。
- 让 RetrievalPort 直接决定 claim 是否通过。
- 绕过 RAG gate 直接把检索结果塞进 final analysis。

## Fake 数据和真实业务规则

生产代码不能写假业务能力。测试里可以使用 fake：

```text
FakeResearchPaperRepository
FakeResearchSourceProvider
FakeResearchDocumentCompiler
FakeResearchLLMWorker
FakeResearchArtifactStore
FakeResearchRAGRuntime
```

fake 论文内容应体现真实论文结构：

```text
title
abstract
introduction
method
experiments
limitations
references
```

不要用 `"foo"`、`"bar"` 这类无法表达业务规则的数据。

## LLM Worker 使用边界

LLM worker 只允许生成候选：

```text
candidate_summary
candidate_contributions
candidate_experiment_claims
candidate_limitations
candidate_reader_answer
```

Harness 和 Research services 决定：

```text
是否采纳
是否证据足够
是否返工
是否通过质量门
是否写 artifact
```

## Skill 使用边界

Research workflow 可以调用 versioned skills：

```text
research-document-structure
research-claim-extraction
research-evidence-checking
research-contribution-analysis
research-experiment-analysis
research-reader-answering
```

要求：

- 每次 skill 调用记录 `skill_name`、`skill_version`、`package_hash`。
- Research run 可以把成功/失败样本、gate result、artifact ref 写成 `SkillExperience`。
- `SkillExperience` 只进入候选经验池，不改变 active skill。
- skill evolution run 只能由显式 Harness workflow 触发。

禁止：

- `AnalyzePaperUseCase` 直接调用 `SkillPromotionPort`。
- 为了让当前论文分析通过而临时改 skill。
- 用户普通分析请求触发 skill 发布。

## Quality Gate

至少检查：

| 检查 | 失败处理 |
| --- | --- |
| 每个主要 claim 有 evidence | 返工或失败。 |
| analysis 不为空 | 失败。 |
| reader payload 有章节导航 | 失败。 |
| source lineage 存在 | 失败。 |
| LLM 输出没有非法流程字段 | 忽略并记录 warning。 |
| reader payload 可修复问题有 issue signature | route_to_repair 或 halted，完整修复在阶段 6A。 |

## Research VERIFY Gates

Research 闭环至少启用这些纯函数 gate：

| Gate | 校验内容 | 失败处理 |
| --- | --- | --- |
| `ResearchToolAllowlistGate` | 当前 step 只能使用 workflow 声明的 worker/tool。 | replan 或 fail。 |
| `ResearchClaimDedupGate` | 同一 paper/run 内不能重复 claim、重复 evidence item、重复 reader answer block。 | replan 或 drop duplicate。 |
| `ResearchScoreRangeGate` | novelty、evidence、reproducibility、reader confidence 等分数必须在合法范围内。 | replan 或 fail。 |
| `ResearchEvidenceCoverageGate` | 主要 claim 必须有 evidence refs 和 lineage。 | route_to_repair 或 halt。 |
| `ResearchBudgetGate` | 不超过 `max_turns`、`max_replans`、`max_retries_per_step`。 | halted。 |
| `ResearchReaderPayloadGate` | reader payload schema、navigation、source lineage 合法。 | route_to_reader_repair 或 fail。 |

Research RAG 至少启用这些 gate：

| Gate | 校验内容 | 失败处理 |
| --- | --- | --- |
| `ResearchRAGScopeGate` | 检索范围不能越过当前 paper/source/project 声明。 | replan 或 fail。 |
| `ResearchRAGQueryDedupGate` | 同一 RAG session 内 query 不重复。 | drop duplicate 或 replan。 |
| `ResearchRAGSourceLineageGate` | evidence 必须有 section/table/figure/span source refs。 | drop source 或 fail。 |
| `ResearchRAGEvidenceNeedGate` | required evidence type 必须覆盖 method、experiment、limitation、claim support。 | replan 或 insufficient_evidence。 |
| `ResearchRAGConflictGate` | 冲突证据必须进入 conflict report，不能静默丢弃。 | replan 或人工 gate。 |
| `ResearchRAGBudgetGate` | 不超过 RAG session 和 Harness run 预算。 | halted。 |

建议 Research 默认预算：

```text
max_turns: 24
max_replans: 3
max_retries_per_step: 2
max_worker_calls: 32
rag_max_rounds: 6
rag_max_queries: 12
rag_max_source_reads: 24
rag_max_memory_hits: 8
```

预算可以由 use case options 覆盖，但必须有安全上限。

## Artifact

至少产出：

```text
research-analysis.json
research-reader-payload.json
research-quality-result.json
harness-trace.json
harness-transcript.json
research-rag-context-pack.json
research-rag-gap-report.json 如果 evidence 不足
reader-issue.json 如果 reader payload gate 失败
```

阶段 6 用 fake artifact store 即可，但 domain/application 不应依赖具体 store。

## 测试要求

新增：

```text
tests/business/research/application/test_analyze_paper_use_case.py
tests/business/research/application/test_build_reader_use_case.py
tests/business/research/application/test_ask_paper_use_case.py
tests/business/research/integration/test_single_paper_loop_fake_runtime.py
tests/business/research/integration/test_research_rag_loop_fake_runtime.py
```

必须覆盖：

- 单篇论文完整闭环成功。
- fake LLM 返回 `next_step` 不影响流程。
- evidence 缺失时 quality gate 失败。
- quality gate 失败时 Harness retry 或 fail。
- max_replans 耗尽后 run halted，且 transcript 记录 halted reason。
- RAG max rounds / max queries / max source reads 耗尽后 run halted 或返回 insufficient_evidence，且 transcript 可复盘。
- 重复 claim 被去重 gate 拒绝或规范化。
- 重复 RAG query 被拒绝或规范化。
- source lineage 缺失的 evidence 不能进入 accepted evidence。
- 冲突 evidence 进入 conflict report。
- 分数越界被 score gate 拒绝。
- artifact refs 完整。
- trace 能解释每个 step。
- skill experience 被记录但不会触发 skill promotion。
- reader payload gate 失败时产出 reader issue ref，但不在阶段 6 展开 repair RAG。
- 不依赖旧 paper_radar。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness tests/business/research -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Fake runtime 跑通单篇论文完整闭环。
- 输出 ResearchAnalysis、ResearchReaderPayload、ResearchQualityResult。
- Harness trace 可导出。
- Harness transcript 可导出并能复盘 PLAN/EXECUTE/VERIFY。
- Research RAGContextPack 可导出，并能解释 evidence 来源、拒绝原因、冲突和 gap。
- Research 可以产出 SkillExperience refs，但不会自动发布新 skill。
- Reader payload gate 失败时有明确 issue signature 和 trace，供阶段 6A 修复。
- 质量门失败路径可测试。
- replan/halt 路径可测试。
- 不做 UI，不接旧 API。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/06-research-single-paper-loop.md。
要求：
1. 用新 Harness 跑通 Research 单篇论文闭环。
2. 实现 AnalyzePaperUseCase、BuildReaderUseCase、AskPaperUseCase 的后端应用层逻辑。
3. 使用 fake LLM、fake repository、fake source provider、fake compiler、fake artifact store 测试，不接真实 UI。
4. build_evidence_pack 和 verify_claims 必须通过阶段 3B 的 Bounded Agentic RAG 获取 RAGContextPack，Research 只构造 ResearchRetrievalGoal / ResearchRAGPolicy。
5. LLM 只生成候选内容和 retrieval plan candidate，不能决定流程、证据采纳、停止检索或写 memory。
6. 每个 Research step 必须经过 PLAN/EXECUTE/VERIFY，VERIFY 使用纯函数 gate。
7. 添加 ResearchToolAllowlistGate、ResearchClaimDedupGate、ResearchScoreRangeGate、ResearchEvidenceCoverageGate、ResearchBudgetGate、ResearchReaderPayloadGate。
8. 添加 ResearchRAGScopeGate、ResearchRAGQueryDedupGate、ResearchRAGSourceLineageGate、ResearchRAGEvidenceNeedGate、ResearchRAGConflictGate、ResearchRAGBudgetGate。
9. max_replans、max_turns、rag_max_rounds、rag_max_queries 或 rag_max_source_reads 耗尽时必须受控 halted 或返回 insufficient_evidence，并写入 transcript。
10. 每次 Research skill 调用记录 skill_name、skill_version、package_hash，并可产出 SkillExperience refs。
11. Research 普通分析 run 不允许调用 SkillPromotionPort，不允许发布新 skill。
12. 输出 ResearchAnalysis、ResearchReaderPayload、ResearchQualityResult、ResearchRAGContextPack、Harness trace、Harness transcript、SkillExperience refs 和 artifact refs。
13. 添加完整闭环、RAG loop、质量门失败、非法 LLM 流程字段、replan/halt、claim/query 去重、分数越界、source lineage、conflict report、artifact、trace/transcript、skill experience 不晋升、reader issue 生成测试。
14. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness tests/business/research -q、openspec validate harness-research-runtime --strict。
15. 修改完成后提交。
全部回复和问题用中文。
```
