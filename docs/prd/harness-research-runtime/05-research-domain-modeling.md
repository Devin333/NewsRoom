# 阶段 5：Research 业务层建模

## 阶段目标

新增 `business/research` 业务上下文，先服务论文业务，但命名保留未来研究工作台扩展空间。阶段 5 做领域模型、端口、服务骨架和 workflow spec，不做 UI，不复用旧 paper_radar。

## 新增目录

```text
business/research/
  __init__.py
  domain/
    __init__.py
    paper.py
    document.py
    evidence.py
    analysis.py
    quality.py
    reader.py
    reader_repair.py
  ports/
    __init__.py
    repositories.py
    source_provider.py
    document_compiler.py
    retrieval.py
    memory.py
    llm_worker.py
    artifact_store.py
    repair_memory.py
  services/
    __init__.py
    evidence_builder.py
    section_extractor.py
    claim_extractor.py
    quality_gate.py
    citation_verifier.py
    profile_builder.py
    reader_issue_detector.py
    reader_repair_gate.py
  workflows/
    __init__.py
    paper_analysis_workflow.py
    paper_reader_workflow.py
    reader_repair_workflow.py
  application/
    __init__.py
    analyze_paper.py
    build_reader.py
    ask_paper.py
```

## 依赖边界

`business/research` 允许依赖：

```text
framework/harness
framework/shared
framework/artifacts models only if domain-neutral
```

`business/research` 禁止依赖：

```text
business/boards/paper_radar
interfaces
infrastructure
frontend
apps
```

如果需要 repository、source provider、compiler、artifact store，只定义 port，不接真实实现。

## 核心领域模型

### ResearchPaper

字段建议：

```text
paper_id
title
authors
abstract
published_at
source
source_url
pdf_url
code_url
topics
metadata
```

### ResearchDocument

字段建议：

```text
paper_id
source_hash
sections
figures
tables
equations
references
metadata
```

### ResearchSection

字段建议：

```text
section_id
title
level
text
page_start
page_end
source_ref
metadata
```

### ResearchClaim

字段建议：

```text
claim_id
text
claim_type
section_id
evidence_ids
confidence
metadata
```

### ResearchEvidencePack

字段建议：

```text
paper_id
items
coverage
missing_information
lineage
metadata
```

### ResearchAnalysis

字段建议：

```text
paper_id
summary
contributions
methods
experiments
limitations
reproducibility
related_work
claims
evidence_pack_id
quality
metadata
```

### ResearchReaderPayload

字段建议：

```text
paper
document
analysis
evidence
navigation
annotations
quality
metadata
```

### ReaderIssue

字段建议：

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
metadata
```

### ReaderRepairCase

字段建议：

```text
repair_case_id
issue
repair_strategy
successful
verification_results
payload_before_ref
payload_after_ref
source_refs
constraints
failure_reason
metadata
```

### ReaderRepairStrategy

字段建议：

```text
strategy_id
issue_type
applicability
steps
constraints
known_failures
confidence
source_case_refs
status
metadata
```

## 服务职责

| 服务 | 职责 |
| --- | --- |
| `SectionExtractor` | 从 `ResearchDocument` 标准化章节结构。 |
| `ResearchEvidenceBuilder` | 从 document/sections/claims 构建 evidence pack。 |
| `ClaimExtractor` | 提取候选 claim，LLM 可参与但不能直接通过。 |
| `CitationVerifier` | 验证 claim 是否有证据支持。 |
| `ResearchQualityGate` | 产出质量 verdict。 |
| `ResearchProfileBuilder` | 生成分析/reader payload 的确定性组合逻辑。 |
| `ReaderIssueDetector` | 从 reader payload、schema result、source lineage 中检测 reader 构建问题。 |
| `ReaderRepairGate` | 验证修复没有破坏 schema、source lineage、citation、table/formula fidelity。 |

## Workflow Spec

`paper_analysis_workflow.py` 只定义 workflow，不执行 workflow。

建议 step：

```text
load_paper_source
compile_document
build_evidence_pack
analyze_structure
analyze_contribution
analyze_experiments
verify_claims
quality_gate
build_reader_payload
publish_artifacts
```

该 workflow 应该可被 `framework/harness` 读取。

`reader_repair_workflow.py` 只定义 reader 修复 workflow，不发布 skill。

建议 step：

```text
detect_reader_issue
build_repair_memory_query
recall_repair_memory
build_repair_context_pack
propose_repair_candidate
verify_repair_candidate
apply_repair
verify_reader_payload
commit_repair_episode_memory
```

阶段 5 只建模，不实现完整 repair RAG loop；完整闭环在阶段 6A。

## 测试要求

新增：

```text
tests/business/research/domain/test_models.py
tests/business/research/services/test_evidence_builder.py
tests/business/research/services/test_quality_gate.py
tests/business/research/reader_repair/test_models.py
tests/business/research/workflows/test_paper_analysis_workflow.py
tests/business/research/workflows/test_reader_repair_workflow.py
tests/architecture/test_research_boundaries.py
```

必须覆盖：

- domain model 可序列化。
- evidence pack 记录 lineage。
- quality gate 能识别无证据 claim。
- reader issue / repair case / repair strategy model 可序列化。
- workflow spec step id 不重复。
- reader repair workflow spec 不发布 skill，不直接写 memory，只声明受控 step。
- `business/research` 不 import 旧 `business.boards.paper_radar`、`interfaces`、`infrastructure`。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/business/research tests/architecture/test_research_boundaries.py -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- `business/research` 建模完成。
- 无旧 paper_radar 依赖。
- 无 interface/infrastructure 反向依赖。
- workflow spec 能被 Harness 契约表达。
- 不做 UI，不接旧 API。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/05-research-domain-modeling.md。
要求：
1. 新增 business/research，建立 domain、ports、services、workflows、application 结构。
2. 定义 ResearchPaper、ResearchDocument、ResearchSection、ResearchClaim、ResearchEvidencePack、ResearchAnalysis、ResearchQualityResult、ResearchReaderPayload。
3. 预留 ReaderIssue、ReaderRepairCase、ReaderRepairStrategy、ReaderRepairContextPack 等 reader repair 领域模型。
4. business/research 不允许依赖 business/boards/paper_radar、interfaces、infrastructure。
5. 定义单篇论文 analysis workflow spec 和 reader repair workflow spec，但不实现完整运行闭环。
6. 添加 domain、service、workflow、架构边界测试。
7. 运行 python -m scripts.dev compile、python -m pytest tests/business/research tests/architecture/test_research_boundaries.py -q、openspec validate harness-research-runtime --strict。
8. 修改完成后提交。
全部回复和问题用中文。
```
