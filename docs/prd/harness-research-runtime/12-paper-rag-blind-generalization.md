# 阶段 12：Paper RAG 盲测泛化能力提升 PRD

## 背景

`paper-rag-blind-detemplated-benchmark` 已经把 Paper RAG 从模板化评测推进到盲测/去模板化评测。真实运行结果显示，当前系统在模板题上看起来可用，但在自然问法下泛化明显不足：

- benchmark 路径：`.newsroom/eval/rag-blind-detemplated-v1-20260628`
- 论文数：38
- chunk 数：7132
- QA pairs：638
- test split pairs：143
- blind profile：`blind_detemplated`
- candidate Hit@10：0.284
- candidate MRR：0.115
- answer success rate：0.200
- gold audit：30 passed / 0 warning / 0 failed

按 QA 类型看，最明显的问题是：

| QA 类型 | Hit@10 | MRR | 观察 |
| --- | ---: | ---: | --- |
| `formula_qa` | 0.000 | 0.000 | 公式问题几乎无法从自然描述召回 |
| `formula_explanation_qa` | 0.000 | 0.000 | 公式与解释上下文关联不够稳 |
| `figure_qa` | 0.348 | 0.125 | 图像/图注/正文引用召回仍偏弱 |
| `table_qa` | 0.370 | 0.147 | 表格主题和结果解释没有稳定一起召回 |
| `experiment_result_qa` | 0.357 | 0.122 | 表格、结果段、conclusion 段召回链路不够强 |
| `citation_qa` | 0.455 | 0.231 | 相对最好，但仍依赖 claim 词面相似 |

本 PRD 的目标不是继续调模板，也不是把评测做得更好看，而是让自然用户问题能稳定召回正确证据。

## 真实根因

### 1. 盲测问题去模板化过头

当前 `blind_detemplated` 去掉了 `Table 3`、`Figure 2`、公式 ID 和 caption 直抄，这是正确方向。但有些问题被改得过于抽象，例如：

```text
What visual evidence explains the model, process, or behavior discussed in the method section?
How does the paper define the key mathematical relation used in the method section?
What quantitative evidence does the paper use in the method section, and what is the takeaway?
```

这类问题的问题是：同一篇论文同一 section 里可能有多个图、多个表、多个公式。gold evidence 只指向一个具体 chunk，但问题本身没有足够语义锚点，retriever 只能猜。

正确的盲测应该是：**不暴露 label，不整句抄 caption，但保留自然主题词**。例如不说 `Table 1`，但可以保留 `BLEU scores`、`baseline`、`WMT14` 这类用户真实会问的语义锚点。

### 2. Query routing 太依赖字面触发词

当前 routing 更容易识别：

- `table`
- `figure`
- `equation`
- `formula`

但盲测自然问法经常写成：

- `quantitative evidence`
- `reported experiments`
- `visual evidence`
- `diagram`
- `mathematical relation`
- `objective`
- `loss`

如果 intent 识别不准，后续 field 权重、chunk type filter、table/figure/formula context expansion 都会跟着走错。

### 3. Field embedding 没有进入当前 benchmark 路径

当前 report 中：

- `title_embedding_score = 0`
- `abstract_embedding_score = 0`
- `caption_embedding_score = 0`
- `equation_embedding_score = 0`
- `body_embedding_score = 0`

这说明真实盲测主要仍靠 whole chunk text search + deterministic lexical field score。caption、equation、table rows、visual_description 这些字段没有形成独立语义召回通道。

### 4. 视觉和结构证据没有多路融合

当前视觉召回主要服务 `figure_query`，而真实问题里图、表、实验结果常常混在一起：

- 问实验结果，可能需要 table chunk + result paragraph + conclusion paragraph。
- 问图说明什么，可能需要 figure chunk + caption + referenced_by paragraph。
- 问公式含义，可能需要 formula chunk + nearby paragraph + referenced_by paragraph。

只靠最近段落或单一路由容易漏证据。

## 产品目标

1. 自然问题不显式包含 `Figure/Table/Equation label` 时，也能召回正确图表/公式/正文证据。
2. 盲测问题既不能泄漏答案，也不能抽象到不可判定。
3. 检索链路能解释：命中了哪个字段、哪个 route、哪个扩展边、哪个 reranker 信号。
4. 公式、图表、实验结果类问题的 Hit@10 和 MRR 分类型可见、可调、可回归。
5. 生产默认策略不能被一次 dev 调参直接覆盖；新策略必须通过 blind dev/test 后再切换。

## 非目标

- 不继续做 fixed-window baseline。后续只保留历史对比结果，不再把 fixed-window 作为每轮必跑 baseline。
- 不用 fake benchmark data 顶替真实论文。
- 不把 gold evidence 质量判断完全交给 LLM。LLM judge 只能做抽检和辅助，核心 gold 结构仍要可追溯。
- 不让 LLM 决定 production retrieval policy 是否上线。
- 不要求第一版训练新模型。
- 不要求第一版接完整多模态视觉 embedding；先把 `visual_description`、caption、image_ref 和结构引用链用好。

## 总体方案

```text
Blind semantic QA
  -> ambiguity audit
  -> query understanding
  -> multi-route retrieval
  -> field-level embedding
  -> structural expansion
  -> lightweight reranker
  -> answer context assembly
  -> blind dev/test evaluation
  -> gated policy promotion
```

核心原则：

- benchmark 先修正确，再调 retrieval。
- query 不只走单一路由；自然问题允许多路召回后融合。
- 字段级召回必须进入真实 benchmark，而不是只留在设计里。
- reranker 只 rerank 宽召回候选，不替代召回。
- 每轮优化必须按 `train/dev/test` 分离，调参只看 dev，最终只报 test。

## V1：盲测问题质量修复

### 目标

把 `blind_detemplated` 升级为更合理的 `blind_semantic` profile，做到：

- 不暴露 `Table 3`、`Figure 2`、`Equation id`。
- 不整句复制 caption、table claim 或 formula label。
- 保留 3-6 个自然语义锚点。
- 同一篇论文同一 QA 类型的问题不能大量重复。
- gold evidence 对问题应当唯一或近似唯一可定位。

### 设计

新增 question profile：

```text
template
blind_detemplated
blind_semantic
```

`blind_semantic` 生成规则：

| QA 类型 | 问题生成策略 |
| --- | --- |
| `figure_qa` | 从 caption / visual_description / referenced paragraph 抽取主题词，不暴露 figure label |
| `table_qa` | 从 caption / table rows / semantic_text 抽取指标、数据集、模型或任务词 |
| `experiment_result_qa` | 保留实验主题、指标、对比对象，避免只问 “reported experiments” |
| `formula_qa` | 保留公式自然名称、loss/objective/relation、关键变量词，不暴露 equation id |
| `formula_explanation_qa` | 保留公式主题 + nearby explanation 关键词 |
| `citation_qa` | 保留 claim 的关键词短语，但不复制完整 claim |

### Ambiguity Audit

新增 blind QA 质量审计：

```text
ambiguous_question_rate
duplicate_question_rate
missing_semantic_anchor_rate
gold_not_uniquely_identifiable_rate
label_leakage_rate
caption_copy_rate
```

判定规则：

- 同一 paper 内，同一个 question 文本对应多个不同 gold chunk -> ambiguous。
- 问题少于 2 个领域关键词 -> missing semantic anchor。
- 问题包含 `Figure 3`、`Table 2`、`Equation abc` -> label leakage。
- 问题连续复制 caption 超过阈值 -> caption copy。

### 涉及文件

- `business/research/rag/evaluation/paper_evidence_eval.py`
- `business/research/rag/evaluation/paper_benchmark_suite.py`
- `business/research/rag/cli/run_benchmark_suite.py`
- `tests/business/research/rag/test_evidence_eval.py`
- `tests/business/research/rag/test_benchmark_suite.py`

### 验收

- CLI 支持 `--question-profile blind_semantic`。
- report 明确写入 `question_profile=blind_semantic`。
- 真实 benchmark 的 ambiguity audit 输出到 JSON/Markdown。
- `label_leakage_rate = 0`。
- `caption_copy_rate` 低于阈值。
- `duplicate_question_rate` 明显低于当前 `blind_detemplated`。

## V2：Query Understanding 和多路召回

### 目标

让自然问题能进入正确 evidence route，而不是依赖 `table/figure/equation` 字面词。

### Query Intent 规则增强

新增或增强 intent 识别：

| 自然表达 | 目标 intent |
| --- | --- |
| `quantitative evidence`, `reported experiments`, `performance`, `score`, `accuracy`, `BLEU`, `F1` | `table_query` + `numerical_result` |
| `visual evidence`, `diagram`, `plot`, `mask`, `architecture figure`, `example images` | `figure_query` |
| `mathematical relation`, `objective`, `loss`, `optimization`, `variable`, `define`, `relation` | `formula_query` |
| `takeaway`, `suggest overall`, `what do results show` | `numerical_result` + `conclusion_context` |

### 多路召回

一个自然问题可以触发多个 route：

```text
experiment_result_qa:
  route 1: table chunks
  route 2: experiment/result paragraphs
  route 3: conclusion/analysis paragraphs

figure_qa:
  route 1: figure chunks
  route 2: caption fields
  route 3: referenced_by paragraphs

formula_qa:
  route 1: formula chunks
  route 2: equation fields
  route 3: nearby/referenced explanation paragraphs
```

多路结果统一进入 fusion：

```text
final_candidate_score =
  semantic_score
  + field_score
  + route_match_score
  + structural_edge_score
  + position_score
```

### 涉及文件

- `business/research/rag/retrieval/paper_policy.py`
- `business/research/rag/retrieval/paper_retriever.py`
- `business/research/rag/retrieval_port.py`
- `tests/business/research/rag/*retriev*.py`

### 验收

- `mathematical relation` 类问题能识别为 `formula_query`。
- `visual evidence` 类问题能识别为 `figure_query`。
- `quantitative evidence` 类问题能识别为 table/result 相关 route。
- report 输出 intent confusion / route distribution。
- `formula_qa Hit@10` 不再为 0。

## V3：Field-Level Embedding 进入真实 benchmark

### 目标

让 `caption`、`equation`、`table_rows`、`visual_description`、`body` 都能单独语义召回，而不是只靠 whole chunk content。

### 字段设计

在现有字段基础上扩展：

```text
title
abstract
caption
equation
body
table_rows
table_columns
visual_description
referenced_text
```

每个非空字段单独建向量：

```text
field_doc_id = <chunk_id>:<field_name>
paper_id
chunk_id
field_name
field_text
source_locator
```

### Benchmark Wiring

当前 `_build_live_retriever` 只接了 in-memory chunk store 和 visual store。V3 必须把 field index 接进去：

```text
_InMemoryFieldEmbeddingStore
  -> index fields from PaperChunk
  -> search_field_vectors(...)
  -> merge hits by chunk_id
```

report 必须看到非零字段 embedding：

```text
caption_embedding_score > 0
equation_embedding_score > 0
body_embedding_score > 0
best_embedding_field
field_embedding_hits
```

### 涉及文件

- `business/research/rag/adapters/paper_field_text.py`
- `business/research/ports/field_embedding_index.py`
- `business/research/rag/cli/run_evidence_eval.py`
- `business/research/rag/evaluation/paper_benchmark_suite.py`
- `business/research/rag/retrieval/paper_retriever.py`
- `infrastructure/storage/vector/paper_field_chunk_store.py`

### 验收

- benchmark report 中 field embedding scores 不再全为 0。
- 分类型输出 `best_embedding_field` 分布。
- `formula_qa` 的 top candidates 主要来自 `equation` / `body` 字段。
- `figure_qa` 的 top candidates 主要来自 `caption` / `visual_description` 字段。
- `table_qa` 和 `experiment_result_qa` 的 top candidates 能看到 `caption` / `table_rows` / `body` 字段贡献。

## V4：结构扩展和上下文组装

### 目标

命中一个结构化元素后，能拿到解释它的上下文。

### 图表扩展

命中 `figure`：

```text
figure chunk
  -> caption
  -> visual_description
  -> nearby_context_chunk_id
  -> referenced_by_chunks
  -> parent paragraph
```

命中 `table`：

```text
table chunk
  -> table rows / caption
  -> nearby_context_chunk_id
  -> referenced_by_chunks
  -> experiment/result paragraph
  -> analysis/conclusion paragraph
```

命中 `formula`：

```text
formula chunk
  -> formula_latex
  -> formula_description
  -> nearby paragraph
  -> referenced_by_chunks
  -> variable definition sentences
```

### Context Assembly

答案上下文不直接塞全部 parent，而是按证据类型组装：

```text
primary_evidence: 命中的表/图/公式
interpretation_context: referenced/nearby/result/conclusion 段落
locator_context: source_locator / image_ref / page / bbox
```

### 涉及文件

- `business/research/rag/retrieval/paper_retriever.py`
- `business/research/rag/retrieval/paper_answer_generator.py`
- `business/research/rag/adapters/paper_context_projection.py`
- `business/research/rag/evaluation/paper_answer_eval.py`

### 验收

- `experiment_result_qa` 命中 table 后，context 中包含 table chunk 和 result/conclusion paragraph。
- `formula_explanation_qa` 命中 formula 后，context 中包含 formula chunk 和 explanation paragraph。
- `figure_qa` 命中 figure 后，context 中包含 image_ref、caption、referenced paragraph。
- answer failure reason 中 `missing_gold_in_retrieval` 明显下降。

## V5：轻量 reranker

### 目标

在宽召回后，用 reranker 判断 query 与候选证据是否真正相关。

### Rerank 输入

每个 candidate 构造 structured passage：

```text
Title: ...
Section: ...
Chunk type: ...
Caption: ...
Equation: ...
Table rows: ...
Visual description: ...
Body: ...
Referenced context: ...
```

### Rerank 范围

- 只 rerank top 50-100 candidates。
- 不直接扩大 LLM answer context。
- rerank score 写入 metadata。

### Score Fusion

```text
candidate_final_score =
  recall_score * 0.35
  + field_embedding_score * 0.25
  + rerank_score * 0.30
  + structural_edge_score * 0.10
```

权重必须在 retrieval policy 中可配置，不直接覆盖默认策略。

### 涉及文件

- `business/research/rag/retrieval/paper_retriever.py`
- `business/research/ports/reranker.py`
- `business/research/rag/evaluation/paper_benchmark_suite.py`
- `tests/business/research/rag/*rerank*.py`

### 验收

- report 输出 reranker enabled、rerank_count、rerank_score 分布。
- dev split 上 MRR 提升，test split 不允许显著回退。
- 失败样本可看到 reranker 是提升还是误排。

## V6：Policy Promotion 和防过拟合闭环

### 目标

新 retrieval policy 不能靠一次 test 结果上线，必须经过 held-out 验证。

### Policy

新增策略：

```text
paper_blind_semantic_rag_v1
```

默认策略保持不变。新策略只能通过 CLI 或环境变量显式启用。

### 评测协议

每次报告必须包含：

```text
question_profile
retrieval_policy
train/dev/test split
gold_audit
ambiguity_audit
route_distribution
field_embedding_distribution
rerank_distribution
by_qa_type Hit@K / MRR
answer success
failure reasons
```

调参只看 dev。最终汇报只报 test。

### 通过门槛

初始建议门槛：

| 指标 | V1 目标 | V3 目标 | V5 目标 |
| --- | ---: | ---: | ---: |
| overall Hit@10 | >= 0.35 | >= 0.45 | >= 0.55 |
| overall MRR | >= 0.15 | >= 0.23 | >= 0.30 |
| `formula_qa Hit@10` | > 0.00 | >= 0.25 | >= 0.40 |
| `figure_qa Hit@10` | >= 0.38 | >= 0.48 | >= 0.58 |
| `table_qa Hit@10` | >= 0.40 | >= 0.50 | >= 0.60 |
| answer success | >= 0.25 | >= 0.40 | >= 0.55 |
| ambiguity warning | 下降 | 下降 | 稳定低位 |

这些不是最终业务 SLA，而是防止盲目上线的工程门槛。

## 实施顺序

### 第一版：修 benchmark 本身

交付：

- `blind_semantic` profile。
- ambiguity audit。
- report 展示盲测问题质量。
- 不再跑 fixed-window baseline。

预期：

- 指标可能不一定立刻提升，但评测更可信。

### 第二版：query understanding

交付：

- 自然问题 intent 识别。
- 多 route recall。
- route distribution report。

预期：

- `formula_qa Hit@10` 从 0 起步。
- `figure/table/result` 类问题少走错 route。

### 第三版：field embedding index

交付：

- in-memory field index 接入 benchmark。
- production field vector adapter 对齐现有 port。
- field embedding score 可观测。

预期：

- caption/equation/table_rows 语义召回明显增强。

### 第四版：结构扩展

交付：

- figure/table/formula 命中后的 context expansion。
- answer context 按 primary/interpreting/locator 分层。

预期：

- answer success 提升。
- `missing_gold_in_retrieval` 下降。

### 第五版：reranker

交付：

- structured passage rerank。
- policy-level 权重配置。
- dev/test 分离评估。

预期：

- MRR 提升。
- top 1-3 证据排序更稳。

### 第六版：promotion gate

交付：

- `paper_blind_semantic_rag_v1` policy。
- dev 调参、test 汇报、历史报告留档。
- policy promotion checklist。

预期：

- 新策略可以安全地和默认策略并存。

## 测试计划

### 单元测试

- `blind_semantic` 不泄漏 label。
- `blind_semantic` 保留 semantic anchors。
- ambiguity audit 能识别重复/过泛问题。
- query intent 能识别自然表达。
- field index 能按字段召回并 merge by `chunk_id`。
- structural expansion 不重复、不越 paper。

### 集成测试

- 用小型 fixture 跑 benchmark suite。
- 验证 report 包含 profile、route、field、rerank metadata。
- 验证 no fixed-window baseline 时报告仍完整。

### 真实 benchmark

命令模板：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m business.research.rag.cli.run_benchmark_suite `
  --papers-dir .newsroom\papers `
  --output-dir .newsroom\eval\rag-blind-semantic-v1-YYYYMMDD `
  --question-profile blind_semantic `
  --retrieval-policy paper_blind_semantic_rag_v1 `
  --answer-eval `
  --answer-eval-sample-size 20 `
  --spot-check-sample-size 20 `
  --gold-audit-sample-size 30
```

## 风险与对策

| 风险 | 对策 |
| --- | --- |
| `blind_semantic` 又变成模板 | 增加 label leakage / caption copy / duplicate audit |
| 问题太抽象导致 gold 不唯一 | 增加 ambiguity audit，低质量问题不进入 test |
| field embedding 增加成本 | 只索引非空字段，benchmark 先用 in-memory，production 可按 paper 删除/重建 |
| reranker 增加延迟 | 只 rerank top 50-100，policy 可关闭 |
| dev 过拟合 | train/dev/test 固定 split，调参只看 dev，最终只报 test |
| 图表/公式仍缺上下文 | structural expansion 必须输出 expansion reason 和 edge |

## 最终形态

最终系统面对用户自然问题时，不需要用户说出 `Figure 3`、`Table 2` 或 `Equation 5`，也能通过主题词、字段语义、结构关系和 reranker 找到正确证据。

理想链路是：

```text
用户问：实验结果说明了什么？
  -> query understanding: numerical_result + table context
  -> multi-route recall: table + result paragraph + conclusion
  -> field embedding: caption/table_rows/body 命中
  -> structural expansion: referenced_by + nearby_context
  -> reranker: table/result/conclusion 排序
  -> answer context: primary table + interpretation paragraph
  -> answer eval: facts grounded, citations valid
```

这才是 Paper RAG 从“能答模板题”走向“能答真实用户问题”的关键一步。
