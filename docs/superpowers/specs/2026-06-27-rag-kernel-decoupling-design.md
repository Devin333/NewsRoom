# NewsRoom RAG Kernel 拆分 PRD

## 1. 文档状态

本文采用已讨论通过的方案 C：**抽象内核 + 保留适配层**。

目标不是把 `business/research/rag` 整个搬到根目录，也不是把论文业务塞进 framework，而是在现有代码上拆出一个可复用的 `framework/rag` 内核，让 Research 继续保留论文领域能力，让 Harness 继续负责有界编排。

## 2. 背景

当前 `business/research/rag` 已经承担了完整 Paper RAG 能力：

- `retriever.py`：论文 chunk 检索、字段权重、图表/公式/section 上下文扩展、排序策略。
- `benchmark_suite.py`、`evidence_eval.py`、`answer_eval.py`：benchmark、gold evidence、answer-level evaluation。
- `page_visual_chunks.py`、`describe_visual_artifacts.py`：图表视觉 chunk、visual description。
- `run_benchmark_suite.py`、`run_evidence_eval.py`：CLI 入口。
- `models.py`、`retrieval_port.py`、`field_text.py`：Paper RAG 的数据模型、端口和字段文本抽取。

同时，`framework/harness/rag` 已经存在通用 Agentic RAG 编排层：

- `models.py` 定义 `RAGSessionSpec`、`RetrievalGoal`、`EvidenceCandidate`、`RAGContextPack`。
- `session.py` 定义 `BoundedRAGSessionController`。
- `gates.py` 定义 `RAGGateSuite`。
- `context_pack_assembler.py` 定义 `RAGContextPackAssembler`。

问题是：Research 侧已经长出了很多通用 RAG 能力，但这些能力和论文专有语义混在一起。未来如果 Projects、Community、Source Intelligence 或其他模块也需要 RAG，就会被迫依赖 `business/research/rag`，形成反向耦合。

## 3. 核心问题

### 3.1 目录职责过宽

`business/research/rag` 现在同时做四类事情：

- 论文领域适配：paper id、section、formula、table、figure、caption、source locator。
- 通用检索策略：query intent、field scoring、rerank、nearby expansion、dedup。
- 通用上下文组装：parent/child 扩展、budget、citation、context pack 候选。
- 通用评测：Hit@K、MRR、answer success、failure reason、report。

这些能力里，第一类应该留在 Research，后三类可以逐步沉淀到通用 RAG kernel。

### 3.2 复用方向不清晰

如果其他业务模块想用 RAG，当前选择很尴尬：

- 直接 import `business.research.rag`：会把论文领域模型带过去。
- 复制一份 retriever/eval 逻辑：会导致重复和指标漂移。
- 直接用 `framework/harness/rag`：它负责编排，但不应该承载具体检索、评分、评测算法。

因此需要新增 `framework/rag`，作为 Harness 和业务适配层之间的通用 RAG kernel。

### 3.3 容易和 Harness 职责混淆

`framework/harness/rag` 的职责是有界状态机和 gate，不是具体业务检索算法。它应该控制：

- 是否检索。
- 检索几轮。
- 是否补查。
- evidence 是否进入 context pack。
- 超预算、证据不足、冲突时如何 halt/replan。

它不应该知道：

- 论文公式怎么提取。
- figure caption 怎么和图片对齐。
- table result conclusion 怎么扩上下文。
- 某个 benchmark gold evidence 如何生成。

这些要么属于 `framework/rag` 的通用算法，要么属于 `business/research/rag` 的领域适配。

## 4. 目标

本 PRD 的目标是完成 RAG 边界拆分设计：

1. 新增 `framework/rag`，沉淀 domain-neutral RAG kernel。
2. 保留 `framework/harness/rag`，继续作为 Agentic RAG 编排层。
3. 收敛 `business/research/rag`，让它成为 Paper RAG adapter，而不是通用 RAG 的实际拥有者。
4. 让 Research 当前真实 benchmark 能在迁移中持续通过，并避免指标不可解释地回退。
5. 为后续 Projects、Community、Source Intelligence 复用 RAG 能力留下稳定边界。

## 5. 非目标

本次拆分不做以下事情：

- 不新增根目录 `rag/`，避免绕开现有 `framework` / `business` 分层。
- 不把 `business/research/rag` 整体搬进 `framework/rag`。
- 不把 `PaperChunk`、arXiv、PDF、formula、table、figure、caption 等论文语义放进 `framework/rag`。
- 不替换 `framework/harness/rag`。
- 不在第一阶段重写现有 ranking 算法。
- 不删除当前 benchmark CLI，迁移完成前保持可运行。
- 不引入新的 production fake path。

## 6. 推荐架构

目标结构：

```text
business/research/rag
  -> framework/rag
  -> framework/harness/rag
```

三层职责如下：

| 层 | 职责 | 不负责 |
| --- | --- | --- |
| `framework/rag` | 通用 RAG 数据模型、检索评分、rerank、context assembly、citation、budget、retrieval/answer metrics、failure reason。 | 不知道 Research、PaperChunk、PDF、arXiv、公式、图表、caption。 |
| `framework/harness/rag` | 有界 Agentic RAG session、PLAN/EXECUTE/VERIFY、gate、budget、replan、halt、transcript。 | 不实现论文检索算法，不生成 gold，不做 benchmark 业务规则。 |
| `business/research/rag` | Paper RAG 领域适配：paper chunk 映射、论文字段文本、公式/表格/图片/caption、visual chunks、paper benchmark、paper gold。 | 不拥有通用 RAG scoring/eval/context 规则。 |

## 7. 目标目录结构

### 7.1 新增通用 RAG kernel

```text
framework/rag/
  __init__.py
  core/
    __init__.py
    models.py
    ports.py
    policy.py
    ids.py
  retrieval/
    __init__.py
    scoring.py
    field_score.py
    rerank.py
    expansion.py
    dedup.py
    query_intent.py
  context/
    __init__.py
    assembler.py
    budget.py
    citation.py
    source_span.py
    nearby_context.py
  generation/
    __init__.py
    contracts.py
    grounding.py
  evaluation/
    __init__.py
    retrieval_metrics.py
    answer_metrics.py
    failure_reason.py
    report.py
```

### 7.2 收敛后的 Paper RAG adapter

```text
business/research/rag/
  __init__.py
  adapters/
    __init__.py
    paper_chunk_adapter.py
    paper_field_text.py
    paper_source_locator.py
    paper_context_projection.py
  retrieval/
    __init__.py
    paper_retriever.py
    paper_policy.py
    paper_visual_retrieval.py
  evaluation/
    __init__.py
    paper_gold_builder.py
    paper_benchmark_suite.py
    paper_answer_eval.py
    paper_evidence_eval.py
  visual/
    __init__.py
    page_visual_chunks.py
    describe_visual_artifacts.py
  cli/
    __init__.py
    run_benchmark_suite.py
    run_evidence_eval.py
  models.py
  retrieval_port.py
```

### 7.3 保留 Harness RAG

```text
framework/harness/rag/
  __init__.py
  models.py
  planner.py
  policy.py
  session.py
  gates.py
  source_verifier.py
  context_pack_assembler.py
  fake.py
```

Harness RAG 不被搬迁。后续只允许它依赖 `framework/rag` 的通用 contracts，不能依赖 `business/research/rag`。

## 8. 依赖方向规则

必须满足：

```text
business/research/rag -> framework/rag
framework/harness/rag -> framework/rag
business/research services/composition -> framework/harness/rag
```

禁止出现：

```text
framework/rag -> business/research
framework/rag -> business/research/rag
framework/harness/rag -> business/research
framework/rag -> arxiv/pdf/nougat/surya/PaperChunk
```

允许出现：

```text
business/research/rag/adapters -> framework/rag/core
business/research/rag/retrieval -> framework/rag/retrieval
business/research/rag/evaluation -> framework/rag/evaluation
framework/harness/rag -> framework/rag/core
```

## 9. 核心数据模型

### 9.1 通用 `RAGChunk`

放在 `framework/rag/core/models.py`。

```python
@dataclass(frozen=True)
class RAGChunk:
    chunk_id: str
    document_id: str
    text: str
    chunk_type: str
    fields: Mapping[str, str]
    source_locator: SourceLocator | None
    metadata: Mapping[str, Any]
```

约束：

- `chunk_type` 是通用字符串，例如 `paragraph`、`section`、`table`、`figure`、`equation`、`caption`。
- `fields` 是通用字段容器，例如 `title`、`abstract`、`caption`、`body`、`formula`、`visual_description`。
- `metadata` 可以携带业务信息，但 `framework/rag` 只能按通用 key 读取。
- `framework/rag` 不 import `PaperChunk`。

### 9.2 通用 `SourceLocator`

放在 `framework/rag/context/source_span.py` 或 `framework/rag/core/models.py`。

```python
@dataclass(frozen=True)
class SourceLocator:
    source_id: str
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    section_path: tuple[str, ...] = ()
    span_start: int | None = None
    span_end: int | None = None
```

说明：

- `page/bbox` 是可选能力，给 PDF reader 或 trace 使用。
- 对网页、文本、API 结果，也可以只用 `source_id` 和 span。
- 前端自研阅读器不强依赖原 PDF bbox，但结构化 locator 仍用于引用、追溯、调试和 benchmark。

### 9.3 通用 `RAGQuery`

```python
@dataclass(frozen=True)
class RAGQuery:
    query: str
    intent: str
    required_chunk_types: tuple[str, ...] = ()
    preferred_fields: tuple[str, ...] = ()
    filters: Mapping[str, Any] = field(default_factory=dict)
```

说明：

- `intent` 可以是 `method`、`figure`、`table`、`formula`、`experiment_result`、`citation`、`summary` 等通用标签。
- Research 可以通过 adapter 把 paper-specific intent 映射进来。

### 9.4 通用 `RAGEvidence`

```python
@dataclass(frozen=True)
class RAGEvidence:
    evidence_id: str
    chunk_id: str
    document_id: str
    text: str
    score: float
    score_breakdown: Mapping[str, float]
    source_locator: SourceLocator | None
    metadata: Mapping[str, Any]
```

说明：

- `score_breakdown` 用来解释 `child_similarity`、`parent_relevance`、`field_score`、`section_heading_score`、`position_bonus` 等分数。
- Research 当前已有 deterministic score 的思路，迁移后要固化为通用结构。

### 9.5 Research adapter 模型

Research 保留自己的领域模型，例如：

- `PaperChunk`
- `PaperSection`
- `ResearchFigure`
- `ResearchTable`
- `ResearchEquation`
- `PaperRAGQuestion`
- `PaperBenchmarkCase`

Research adapter 负责转换：

```text
PaperChunk -> RAGChunk
Research question -> RAGQuery
ResearchFigure/Table/Equation -> RAGChunk fields + metadata
RAGEvidence -> Research-facing answer context
```

## 10. 关键流程

### 10.1 Ingest / Index 阶段

```text
PDF / arXiv / paper artifact
  -> Research document parser
  -> PaperChunk / figure / table / equation / caption
  -> PaperChunkAdapter
  -> RAGChunk
  -> ChunkStore / VectorStore / VisualIndex
```

原则：

- PDF 解析、Nougat、Surya、CLIP、visual description 都属于 Research 文档处理或 Research RAG adapter。
- `framework/rag` 只接收已经抽象后的 `RAGChunk`。

### 10.2 Retrieval 阶段

```text
User question
  -> Research query adapter
  -> RAGQuery
  -> framework/rag retrieval policy
  -> candidate chunks
  -> scoring / rerank / expansion / dedup
  -> RAGEvidence[]
```

Research 可以定制：

- paper fields 的权重。
- formula/table/figure 的 intent 映射。
- visual chunk 是否参与检索。
- section role 的业务含义。

通用 kernel 负责：

- field scoring 公式。
- score breakdown。
- parent/child 扩展策略。
- nearby context 扩展。
- referenced_by / references 扩展接口。
- dedup。
- budget trimming。

### 10.3 Harness Agentic RAG 阶段

```text
ResearchRAGRequest
  -> ResearchRAGSessionSpecMapper
  -> RAGSessionSpec
  -> BoundedRAGSessionController
  -> RetrievalPort backed by framework/rag + research adapter
  -> RAGGateSuite
  -> RAGContextPack
```

原则：

- Harness 决定多轮检索、gate、replan、halt。
- `framework/rag` 提供检索、评分、上下文组装能力。
- Research 提供业务 corpus、adapter 和 policy。

### 10.4 Answer / Evaluation 阶段

```text
RAGContextPack / RAGEvidence[]
  -> answer generator
  -> answer text + citations
  -> framework/rag evaluation metrics
  -> business/research paper evaluation report
```

通用 metrics：

- Hit@K
- MRR
- nDCG
- EvidenceCoverage
- ContextRecall
- SourceLocatorCoverage
- AnswerFaithfulness
- AnswerRelevance
- CitationGrounding
- AbstentionAccuracy

Research metrics：

- citation QA coverage
- formula QA coverage
- table QA coverage
- figure QA coverage
- experiment/result/conclusion QA coverage
- paper-specific gold audit warnings

## 11. 版本递进计划

### V0：整理 `business/research/rag` 内部边界

目标：不改行为，只把现有职责先按目录分组。

范围：

- 将当前大文件中的明确领域能力和通用能力标注清楚。
- 创建 `business/research/rag/adapters`、`retrieval`、`evaluation`、`visual`、`cli` 目录。
- 保持 public imports 可控，避免一次性大范围调用点修改。
- 不移动 `framework/harness/rag`。

验收：

- 现有 Research RAG tests 通过。
- `run_benchmark_suite.py` 和 `run_evidence_eval.py` 仍可运行。
- 没有指标公式变化。
- 没有 production fake path。

建议检查：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m pytest tests\business\research\rag -q
```

### V1：新增 `framework/rag/core` contracts

目标：先抽模型和端口，不抽算法。

范围：

- 新增 `RAGChunk`、`RAGQuery`、`RAGEvidence`、`SourceLocator`、`RAGScoreBreakdown`。
- 新增 `RAGRetrieverPort`、`RAGChunkStorePort`、`RAGRerankerPort`、`RAGContextAssemblerPort`。
- 新增 `PaperChunkAdapter`，把 `PaperChunk` 投影成 `RAGChunk`。
- Research retriever 内部可以开始使用通用 DTO，但外部行为不变。

验收：

- `framework/rag` 不 import `business.research`。
- `PaperChunk` 只出现在 `business/research` 或 tests fixture。
- Research benchmark 输出字段不丢失。

新增测试：

```text
tests/framework/rag/core/test_models.py
tests/business/research/rag/adapters/test_paper_chunk_adapter.py
```

### V2：抽通用 context assembly / citation / budget

目标：把 parent-child、nearby context、citation locator、context budget 变成通用能力。

范围：

- 新增 `framework/rag/context/assembler.py`。
- 新增 `framework/rag/context/budget.py`。
- 新增 `framework/rag/context/citation.py`。
- 新增 `framework/rag/context/nearby_context.py`。
- Research 保留 paper-specific binding：figure/table/formula 和 paper paragraph 的关系。
- overlap 的 `main_span`、`overlap_spans`、`origin_chunk_id` 可作为通用 citation metadata 承载。

验收：

- 命中 child 后扩 parent 时，最终 context item 有 score breakdown 和 source locator。
- context trimming 不删除 citation/source refs。
- Research 的 table/result/conclusion、formula explanation、figure caption 扩展仍可表达。

新增测试：

```text
tests/framework/rag/context/test_context_assembler.py
tests/framework/rag/context/test_budget.py
tests/framework/rag/context/test_citation.py
tests/business/research/rag/test_paper_context_projection.py
```

### V3：抽通用 retrieval scoring / rerank / expansion

目标：把当前 Research 中可复用的评分和扩展逻辑沉淀到 `framework/rag/retrieval`。

范围：

- 新增 `framework/rag/retrieval/scoring.py`。
- 新增 `framework/rag/retrieval/field_score.py`。
- 新增 `framework/rag/retrieval/rerank.py`。
- 新增 `framework/rag/retrieval/expansion.py`。
- 新增 `framework/rag/retrieval/dedup.py`。
- 保留 Research policy 配置字段权重，例如 table 问题提高 caption/table rows 权重，formula 问题提高 formula/formula_description 权重。

推荐默认公式：

```text
final_score =
  child_similarity * 0.50
  + parent_relevance * 0.25
  + field_score * 0.15
  + section_heading_score * 0.07
  + position_bonus * 0.03
```

说明：

- 权重作为 policy 配置，不硬编码在 Research 里。
- Reranker 分数进入 `score_breakdown`。
- 无 reranker 时保留 deterministic fallback。

验收：

- 每条 evidence 都能解释排序原因。
- field-level score 可观测。
- 迁移后 benchmark 不因无意改算法而明显回退。

新增测试：

```text
tests/framework/rag/retrieval/test_scoring.py
tests/framework/rag/retrieval/test_field_score.py
tests/framework/rag/retrieval/test_expansion.py
tests/framework/rag/retrieval/test_dedup.py
tests/business/research/rag/retrieval/test_paper_policy.py
```

### V4：抽通用 evaluation / report

目标：把可跨业务复用的指标计算移动到 `framework/rag/evaluation`，Research 只保留 paper gold 和 paper benchmark。

范围：

- 新增 `retrieval_metrics.py`：Hit@K、MRR、nDCG、EvidenceCoverage、ContextRecall。
- 新增 `answer_metrics.py`：faithfulness、answer relevance、fact coverage、citation grounding、abstention accuracy 的通用 DTO 和 deterministic calculator。
- 新增 `failure_reason.py`：统一 failure reason taxonomy。
- 新增 `report.py`：通用 markdown/json report builder。
- Research 的 `paper_benchmark_suite.py` 调用通用 metrics。

验收：

- paper benchmark 指标字段保持兼容。
- 通用 metrics 不依赖 paper-specific QA type。
- Research 能继续按 citation/formula/table/figure/experiment_result 输出分类指标。

新增测试：

```text
tests/framework/rag/evaluation/test_retrieval_metrics.py
tests/framework/rag/evaluation/test_answer_metrics.py
tests/framework/rag/evaluation/test_failure_reason.py
tests/business/research/rag/evaluation/test_paper_benchmark_suite.py
```

### V5：接入 Harness contracts，移除临时桥

目标：让 `framework/harness/rag` 和 `framework/rag` 通过通用 contracts 协作。

范围：

- `BoundedRAGSessionController` 使用 `framework/rag` 的 retrieval/context contracts。
- Research composition 层负责把 paper request 映射成 `RAGSessionSpec`。
- Research adapter 实现 retrieval port。
- 删除迁移期兼容桥和重复 DTO。

验收：

- `framework/harness/rag` 不 import `business.research`。
- `business/research` 不直接构造低层 framework internals，只通过 mapper/composition 组装。
- RAGContextPack 中 accepted evidence 有 source refs/span refs/artifact refs。
- Harness transcript 可解释 query、accepted/rejected evidence、gap、repair、halt。

新增测试：

```text
tests/framework/harness/rag/test_rag_with_framework_kernel.py
tests/business/research/integration/test_paper_rag_harness_kernel_integration.py
```

## 12. 迁移基准

迁移不能只看代码能跑，还要看 RAG 质量是否保持。

以最近一次会话内 benchmark 结果作为迁移参考线，正式实现前需要重新从当前 artifacts 固化 baseline：

```text
candidate Hit@10: 0.848
candidate MRR: 0.817
answer success rate: 0.700
```

说明：

- 固定窗口 baseline 已不再作为默认投入方向，只保留必要的显式 A/B 开关。
- 迁移期重点看 candidate 指标、answer success、failure reasons、gold audit warning。
- 如果指标回退，必须先定位是模型/数据/策略变化，还是纯迁移 bug。

建议质量门槛：

| 指标 | V0/V1 | V2/V3 | V4/V5 |
| --- | --- | --- | --- |
| candidate Hit@10 | 不低于 baseline 3 个百分点 | 不低于 baseline 2 个百分点 | 不低于 baseline 1 个百分点 |
| candidate MRR | 不低于 baseline 3 个百分点 | 不低于 baseline 2 个百分点 | 不低于 baseline 1 个百分点 |
| answer success rate | 不低于 baseline 5 个百分点 | 不低于 baseline 3 个百分点 | 不低于 baseline 2 个百分点 |
| missing_gold_in_retrieval | 不增加超过 20% | 不增加超过 10% | 不增加 |
| production fake path | 0 | 0 | 0 |

## 13. OpenSpec 策略

实现阶段建议拆成 3 个 OpenSpec change，而不是一次性大改：

### 13.1 `rag-kernel-core-contracts`

覆盖 V0/V1：

- `framework/rag/core`。
- Paper adapter。
- import boundary tests。
- 不改检索算法。

### 13.2 `rag-kernel-context-retrieval`

覆盖 V2/V3：

- context assembly。
- citation/budget。
- scoring/rerank/expansion/dedup。
- Research policy adapter。

### 13.3 `rag-kernel-evaluation-harness-integration`

覆盖 V4/V5：

- generic evaluation。
- report/failure reason。
- Harness contracts。
- 删除临时桥。

每个 change 都必须执行：

```powershell
openspec validate <change> --strict
```

## 14. 边界验收规则

### 14.1 Import boundary

必须增加自动检查：

```powershell
rg "business\\.research" framework\\rag
rg "business\\.research" framework\\harness\\rag
rg "PaperChunk|arxiv|Nougat|Surya|PDF" framework\\rag
```

预期：

- `framework/rag` 不命中 Research 业务 import。
- `framework/harness/rag` 不命中 Research 业务 import。
- `framework/rag` 不出现论文解析专有名词。

### 14.2 Public API boundary

`framework/rag` 对外只暴露：

- data contracts。
- pure scoring/evaluation functions。
- retriever/context assembler ports。
- policy objects。

不暴露：

- Research CLI。
- Paper benchmark。
- PDF artifacts。
- local `.newsroom` 路径。

### 14.3 Research adapter boundary

`business/research/rag` 可以：

- import `framework/rag`。
- 持有 paper-specific policy。
- 解释公式、图表、表格、caption 的领域关系。
- 生成 paper benchmark gold。

不可以：

- 重新实现一套通用 Hit@K/MRR calculator。
- 复制一套通用 score breakdown 结构。
- 直接控制 Harness session 的 replan/halt。

## 15. 测试计划

### 15.1 Unit tests

新增：

```text
tests/framework/rag/core/
tests/framework/rag/retrieval/
tests/framework/rag/context/
tests/framework/rag/evaluation/
```

覆盖：

- DTO serialization。
- score calculation。
- field weighting。
- rerank fallback。
- context budget trimming。
- citation/source span preservation。
- metrics calculation。
- failure reason mapping。

### 15.2 Adapter tests

新增或调整：

```text
tests/business/research/rag/adapters/
tests/business/research/rag/retrieval/
tests/business/research/rag/evaluation/
```

覆盖：

- `PaperChunk -> RAGChunk`。
- figure/table/formula/caption fields。
- source locator projection。
- paper-specific policy。
- benchmark gold shape。

### 15.3 Integration tests

保留并扩展：

```text
tests/business/research/integration/
tests/framework/harness/rag/
```

覆盖：

- Paper RAG 通过 framework kernel 检索。
- Harness session 使用 framework kernel port。
- RAGContextPack 保留 accepted/rejected evidence。
- answer evaluation 能从 context pack 和 gold evidence 算出结果。

### 15.4 Regression benchmark

每个迁移阶段完成后跑：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m pytest tests\framework\rag tests\business\research\rag tests\framework\harness\rag -q
.\.venv\Scripts\python.exe -m business.research.rag.run_benchmark_suite --split test
```

如果 benchmark CLI 当前不是 module 形式运行，实施阶段应保留现有运行方式并在 PR 中写明实际命令。

## 16. 数据与产物约定

迁移后通用 RAG report 输出应包含：

```json
{
  "run_id": "...",
  "policy_name": "...",
  "query_count": 0,
  "evidence_count": 0,
  "metrics": {},
  "failure_reasons": [],
  "score_breakdown_summary": {},
  "source_locator_coverage": 0.0
}
```

Research paper benchmark report 继续额外包含：

```json
{
  "paper_count": 0,
  "chunk_count": 0,
  "qa_type_counts": {},
  "gold_audit_warnings": [],
  "paper_ids": []
}
```

通用层不读取 `.newsroom`。Research/infrastructure 层负责从 `.newsroom` 读写 artifact。

## 17. 错误处理与可观测性

### 17.1 错误分类

`framework/rag/evaluation/failure_reason.py` 应提供通用失败分类：

- `missing_gold_in_retrieval`
- `low_rank_gold`
- `context_missing_gold`
- `citation_missing_source`
- `fact_match_low`
- `answer_not_grounded`
- `abstention_expected`
- `budget_exhausted`
- `reranker_unavailable`

Research 可以扩展：

- `paper_parser_missing_figure`
- `paper_parser_missing_formula`
- `caption_image_alignment_failed`
- `table_result_context_missing`

### 17.2 Score breakdown

每条 evidence 必须能解释：

```json
{
  "child_similarity": 0.0,
  "parent_relevance": 0.0,
  "field_score": 0.0,
  "section_heading_score": 0.0,
  "position_bonus": 0.0,
  "rerank_score": 0.0,
  "final_score": 0.0
}
```

这样后续调参时可以回答：

- 是 embedding 没召回？
- 是字段权重太低？
- 是 reranker 不重视图表？
- 是 parent 扩展带来噪声？
- 是 section heading 误导排序？

## 18. 风险与规避

| 风险 | 表现 | 规避 |
| --- | --- | --- |
| 过度抽象 | `framework/rag` 变成泛泛 DTO 堆积，业务仍然复制逻辑。 | 每次抽取必须有至少一个 Research 调用点和一个 framework unit test。 |
| 论文语义泄漏 | `framework/rag` 出现 `PaperChunk`、arXiv、formula parser。 | import boundary test + keyword scan。 |
| 行为回退难定位 | 迁移后指标下降但不知道原因。 | 固化 baseline，保留 score breakdown，分阶段迁移。 |
| 大文件一次性改坏 | `retriever.py` 体积大，改动容易波及排序。 | V0 只整理，V1 只抽 contracts，V3 才抽 scoring。 |
| Harness 职责膨胀 | `framework/harness/rag` 开始做业务检索。 | Harness 只依赖 ports 和 contracts，不实现 paper policy。 |
| 兼容层长期残留 | 临时 bridge 变成永久 layer。 | 每个 bridge 标注 removal phase，V5 必须删除。 |

## 19. 交付物

最终交付后应具备：

1. `framework/rag` 通用内核。
2. `business/research/rag` Paper RAG adapter。
3. `framework/harness/rag` 使用通用 contracts 的有界编排。
4. Paper RAG benchmark 在迁移后保持可运行。
5. 可解释 score breakdown。
6. 通用 evaluation metrics。
7. import boundary tests。
8. OpenSpec changes 和实现提交。

## 20. 实施顺序建议

推荐顺序：

1. 先做 `rag-kernel-core-contracts`，把 DTO 和 adapter 接起来。
2. 再做 `rag-kernel-context-retrieval`，迁移 context/scoring/expansion。
3. 最后做 `rag-kernel-evaluation-harness-integration`，迁移 metrics/report 并接 Harness。

每一步都要先保持现有行为，再逐步删除重复实现。不能一开始就追求“漂亮目录”，因为当前 RAG 已经有真实 benchmark 和真实论文路径，稳定性比目录美观更重要。

## 21. Review Gate

用户 review 本 PRD 后，如果方向确认，再进入 implementation plan。实现计划应按 OpenSpec change 拆分任务、测试、提交边界和回滚策略。
