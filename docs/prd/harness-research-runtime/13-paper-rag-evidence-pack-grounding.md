# 阶段 13：Paper RAG 证据组与等价证据评测 PRD

## 背景

阶段 12 已经把 Paper RAG 从模板题推进到 `blind_semantic` 盲测，并引入 `paper_blind_semantic_rag_v1`、field embedding、结构扩展、轻量 reranker 和 promotion checklist。

在原始 38 篇论文集上，policy promotion 已经通过：

- Hit@10：0.761
- MRR：0.520
- answer success：0.650
- gold audit：30 passed / 0 warning / 0 failed
- promotion checklist：ready

但在另一批近期 arXiv 新论文 50 篇上，检索层能过线，回答层没有过线：

- papers：50
- chunks：9963
- QA pairs：650
- test split：10 篇 / 140 pairs
- Hit@10：0.708
- MRR：0.567
- answer success：0.500
- failure reasons：`missing_gold_in_retrieval=8`、`fact_match_low=2`
- promotion checklist：not ready，唯一失败项是 answer success 低于 0.55

分类型看，新论文集上图表和实验结果表现稳定，但公式和 citation 仍然弱：

| QA 类型 | Hit@10 | MRR | 观察 |
| --- | ---: | ---: | --- |
| `figure_qa` | 0.958 | 0.895 | 已基本稳定 |
| `table_qa` | 0.824 | 0.770 | 已基本稳定 |
| `experiment_result_qa` | 0.867 | 0.838 | 已基本稳定 |
| `formula_explanation_qa` | 0.704 | 0.484 | 解释段和公式 chunk 仍会拆开 |
| `formula_qa` | 0.481 | 0.260 | 公式自然锚点弱，召回不稳 |
| `citation_qa` | 0.500 | 0.328 | claim 所在 chunk 定位不稳 |

本阶段目标不是继续简单调权重，而是把 Paper RAG 从“命中单个 chunk”升级为“命中可验证证据组”。

## 真实根因

### 1. `gold_chunk_id` 过于刚性

当前 answer eval 更偏向：

```text
gold_chunk_id 没在 retrieved/context/citation 里
  -> missing_gold_in_retrieval
```

但真实失败样本里，有些答案已经写出正确公式，`fact_coverage=1.0`，只是引用的是相邻段落、父段落或等价公式内容，不是 benchmark 标定的那个精确 chunk id。

这类样本不应该直接算“找不到证据”，而应该进入等价证据判断。

### 2. 公式和解释上下文没有稳定成组

公式类问题常见情况：

```text
命中解释段，但没带公式 chunk
命中公式 chunk，但没带解释段
命中相近公式，但 gold formula chunk 没进 top10
```

这说明当前结构扩展还不够强，缺少显式的 `formula evidence pack`。

### 3. citation QA 缺少 claim-level index

当前 citation QA 主要在 paragraph / body 上找词面相似。问题是 citation 问法通常是：

```text
Which passage grounds the paper's claim about ...
```

如果 claim 关键词很通用，retriever 容易命中相关段落，但不是原 claim 所在 chunk。需要把 paragraph 里的关键 claim 单独抽出来建索引，再回到 chunk。

### 4. answer eval 还没有区分“证据缺失”和“等价证据支持”

当前 failure reason 里 `missing_gold_in_retrieval` 混合了两类问题：

- 真没找到能支持答案的证据。
- 找到了等价证据，但没有命中精确 gold id。

这会让指标低估系统真实能力，也会误导优化方向。

## 产品目标

1. 公式、图表、表格、citation 证据不再只依赖单个 `gold_chunk_id`。
2. 每个复杂 evidence QA 能生成 `supporting_evidence_group`，包含 primary evidence、解释上下文、引用上下文和 locator。
3. 检索命中任一核心证据后，能自动扩展到同组证据。
4. answer eval 能识别 `equivalent_gold_supported`，减少误报的 `missing_gold_in_retrieval`。
5. citation QA 支持 claim-level 检索，提高 claim 所在 passage 定位能力。
6. benchmark report 明确区分：
   - strict gold id hit
   - equivalent evidence hit
   - claim supported by context
   - true missing gold evidence

## 非目标

- 不把不相关证据强行算作正确。
- 不降低 answer success 门槛。
- 不用 LLM judge 替代 deterministic gate；LLM judge 只能做抽检或辅助诊断。
- 不把新 policy 直接切成默认策略。
- 不训练新模型作为第一版目标。
- 不把所有 parent section 都塞进 context，避免 answer context 噪声暴涨。

## 核心方案

```text
QA pair / gold evidence
  -> build evidence group
  -> equivalent evidence ids
  -> retrieval structural expansion
  -> answer context evidence pack
  -> answer generation with required evidence group
  -> answer eval with strict + equivalent grounding
  -> benchmark report / promotion gate
```

核心原则：

- 评测要保留 strict gold id 指标，但 promotion 不能只看 strict id。
- 等价证据必须来自可解释结构边或 claim-level 支持，不能任意放宽。
- 证据组扩展要有 budget、dedup、reason 和 source locator。
- 对公式/citation 的优化优先，因为它们是新 50 篇盲测的主要短板。

## 数据模型设计

### Evidence Group

新增或扩展 benchmark 产物中的 evidence group：

```json
{
  "group_id": "eg_...",
  "paper_id": "2606.27029",
  "qa_type": "formula_qa",
  "primary_evidence_ids": ["chunk_formula"],
  "equivalent_evidence_ids": [
    "chunk_formula",
    "chunk_parent_paragraph",
    "chunk_nearby_explanation"
  ],
  "interpretation_context_ids": ["chunk_explanation"],
  "locator_context": [
    {
      "chunk_id": "chunk_formula",
      "source_locator": "arxiv://2606.27029/latex",
      "chunk_type": "formula"
    }
  ],
  "relations": [
    {
      "from_chunk_id": "chunk_formula",
      "to_chunk_id": "chunk_explanation",
      "edge": "formula_parent_context"
    }
  ]
}
```

### Evidence QA Pair

扩展当前 `EvidenceQAPair`：

```json
{
  "gold_chunk_ids": ["chunk_formula"],
  "equivalent_gold_chunk_ids": ["chunk_formula", "chunk_parent", "chunk_explanation"],
  "supporting_evidence_group_id": "eg_...",
  "required_primary_evidence_ids": ["chunk_formula"],
  "acceptable_support_evidence_ids": ["chunk_parent", "chunk_explanation"],
  "gold_claim_ids": ["claim_..."]
}
```

语义说明：

- `gold_chunk_ids`：严格 gold，保留原指标。
- `equivalent_gold_chunk_ids`：可接受等价证据，用于 answer eval 的 supported 判断。
- `required_primary_evidence_ids`：公式/图表/表格本体，回答时优先进入 context。
- `acceptable_support_evidence_ids`：能解释答案但不是本体的证据。
- `gold_claim_ids`：citation QA 对应的 claim-level gold。

### Claim Index

新增 claim-level index：

```json
{
  "claim_id": "claim_001",
  "paper_id": "2606.26997",
  "chunk_id": "chunk_abc",
  "section_title": "Introduction",
  "claim_text": "Large language model post-training for reasoning increasingly relies on reinforcement learning with verifiable rewards...",
  "source_locator": "arxiv://2606.26997/latex",
  "claim_type": "abstract_claim"
}
```

claim 来源：

- abstract 第一批核心 claim。
- introduction / conclusion 的高信息密度句子。
- citation QA golden set 当前使用的 snippet。

## V1：Benchmark Gold Evidence Group

### 目标

先把评测数据从“单 gold chunk”升级为“gold evidence group”，但不改变默认 retrieval 行为。

### 交付

- 为每条 answerable QA 生成 `supporting_evidence_group`。
- 为 formula/table/figure/citation QA 生成 `equivalent_gold_chunk_ids`。
- report 同时输出：
  - `strict_gold_hit`
  - `equivalent_gold_hit`
  - `true_missing_gold`

### 规则

公式类：

```text
formula chunk
  + parent paragraph
  + nearby explanation paragraph
  + referenced_by paragraphs
```

表格类：

```text
table chunk
  + caption
  + table rows
  + nearby result paragraph
  + conclusion/analysis paragraph
```

图像类：

```text
figure chunk
  + image_ref
  + caption
  + visual_description
  + referenced_by paragraph
```

citation 类：

```text
claim chunk
  + claim sentence
  + source paragraph
  + abstract/introduction source locator
```

### 涉及文件

- `business/research/rag/evaluation/paper_evidence_eval.py`
- `business/research/rag/evaluation/paper_gold_builder.py`
- `business/research/rag/evaluation/paper_benchmark_suite.py`
- `tests/business/research/rag/test_evidence_eval.py`
- `tests/business/research/rag/test_benchmark_suite.py`

### 验收

- golden set JSON 包含 `supporting_evidence_group_id`。
- 每条 formula/table/figure/citation QA 都能输出非空 evidence group。
- report 包含 strict vs equivalent 指标。
- 新 50 篇 benchmark 中 `missing_gold_in_retrieval` 能拆分为 true missing 和 equivalent supported。

## V2：检索后的 Evidence Pack 扩展

### 目标

命中某个证据后，自动补齐同组证据，让 answer context 能同时包含本体和解释。

### 设计

检索结果进入 answer context 前执行：

```text
for hit in retrieved_chunks:
  find evidence_group(hit.chunk_id)
  add primary_evidence
  add interpretation_context
  add locator_context
  dedup
  enforce context budget
```

扩展原因写入 metadata：

```json
{
  "expanded_from_chunk_id": "chunk_explanation",
  "expanded_to_chunk_id": "chunk_formula",
  "expansion_reason": "formula_group_primary_evidence",
  "group_id": "eg_..."
}
```

### 涉及文件

- `business/research/rag/retrieval/paper_retriever.py`
- `business/research/rag/retrieval/paper_answer_generator.py`
- `business/research/rag/adapters/paper_context_projection.py`
- `business/research/rag/adapters/paper_source_locator.py`

### 验收

- 命中 formula explanation 后，context 能补入 formula chunk。
- 命中 formula chunk 后，context 能补入解释段。
- 命中 table chunk 后，context 能补入 result/conclusion 段。
- answer sample metadata 输出 `evidence_group_id`、`expansion_reason`。
- context 不超过预算，且无重复 chunk。

## V3：Claim-Level Index for Citation QA

### 目标

让 citation QA 从 paragraph-level 检索升级为 claim-level 检索。

### 设计

构建 claim records：

```text
PaperChunk -> split sentences -> filter claim-like sentence -> ClaimRecord
```

claim-like 规则：

- 长度在合理范围内。
- 包含方法、贡献、结果、结论、定义等信号词。
- 排除纯引用列表、公式残片、表格残片。

检索路径：

```text
citation_query
  -> claim index search
  -> claim_id
  -> source chunk_id
  -> evidence group
  -> answer context
```

### 涉及文件

- `business/research/rag/retrieval/paper_retriever.py`
- `business/research/rag/retrieval/paper_policy.py`
- `business/research/rag/evaluation/paper_evidence_eval.py`
- 新增：`business/research/rag/retrieval/paper_claim_index.py`
- 新增测试：`tests/business/research/rag/test_claim_index.py`

### 验收

- citation QA report 输出 `claim_index_hits`。
- citation QA Hit@10 在新 50 篇上高于当前 0.50。
- answer eval 中 citation 类 `missing_gold_in_retrieval` 下降。
- 每个 claim hit 能追溯回 source chunk 和 source locator。

## V4：Answer Eval 支持等价证据

### 目标

把 answer eval 从“只认 strict gold id”升级为“strict + equivalent + claim support”。

### 新指标

```text
strict_gold_context_coverage
equivalent_gold_context_coverage
strict_gold_citation_coverage
equivalent_gold_citation_coverage
claim_support_coverage
true_missing_gold_rate
equivalent_supported_rate
```

### Failure Reason 调整

当前：

```text
missing_gold_in_retrieval
```

升级后拆分：

```text
true_missing_gold_in_retrieval
gold_id_missed_but_equivalent_supported
context_missing_primary_evidence
context_missing_interpretation_evidence
claim_not_supported
fact_match_low
```

promotion 逻辑：

```text
answer_success =
  fact_passed
  and equivalent_or_strict_citation_passed
  and substantive_answer
```

但 report 必须继续保留 strict 指标，防止指标虚高。

### 涉及文件

- `framework/rag/evaluation/answer_metrics.py`
- `framework/rag/evaluation/failure_reason.py`
- `business/research/rag/evaluation/paper_answer_eval.py`
- `business/research/rag/evaluation/paper_evaluation_report.py`
- `business/research/rag/adapters/evaluation_scorecard_adapter.py`

### 验收

- 同一个答案如果事实正确且引用了等价证据，不再被标记为 `missing_gold_in_retrieval`。
- report 能看到 strict coverage 和 equivalent coverage 差异。
- 新 50 篇 answer eval 中 `missing_gold_in_retrieval` 明显下降。
- 不能把事实不匹配的答案误判为成功。

## V5：Promotion Gate 升级

### 目标

把新指标纳入 promotion checklist，避免只靠一组样本误判。

### Gate 建议

| 指标 | 目标 |
| --- | ---: |
| overall Hit@10 | >= 0.55 |
| overall MRR | >= 0.30 |
| formula_qa Hit@10 | >= 0.45 |
| citation_qa Hit@10 | >= 0.60 |
| answer success | >= 0.60 |
| equivalent_supported_rate | 可见且可解释 |
| true_missing_gold_rate | 低于当前新 50 篇 baseline |
| strict/equivalent gap | 必须报告 |
| gold audit warning/fail | 0 |

### 验收

- promotion checklist 输出 strict/equivalent 指标。
- 新 50 篇 benchmark 不只看 answer success，还能解释 answer success 的变化来自哪里。
- 如果 answer success 提升但 strict gold hit 暴跌，gate 必须提示风险。

## 实施顺序

### 第一版：先修评测语义

交付：

- `equivalent_gold_chunk_ids`
- `supporting_evidence_group`
- strict vs equivalent report
- failure reason 拆分

预期：

- 不一定立刻提升 retrieval。
- 但能判断当前 `missing_gold_in_retrieval` 里有多少是误判。

### 第二版：公式 evidence pack

交付：

- formula chunk 与解释段双向绑定。
- 命中公式/解释任一方，自动补齐 evidence pack。
- answer context metadata 输出扩展边。

预期：

- `formula_qa`、`formula_explanation_qa` answer success 提升。
- `context_missing_primary_evidence` 下降。

### 第三版：claim-level citation index

交付：

- claim extraction。
- claim index search。
- citation QA 走 claim route。

预期：

- `citation_qa Hit@10` 从当前 0.50 提升。
- citation 类 `missing_gold_in_retrieval` 下降。

### 第四版：answer eval 与 promotion gate 合并

交付：

- answer eval 使用 strict + equivalent + claim support。
- policy promotion checklist 增加新指标。
- benchmark markdown/JSON 输出完整诊断。

预期：

- answer success 更符合真实 grounded answer 能力。
- 不再把“等价证据支持”误判为“找不到证据”。

### 第五版：真实新论文集回归

交付：

- 固定 `new50-20260629` 作为 held-out 回归集。
- 再补一个不同时间/领域的新 50 篇集。
- 每次 policy 变更同时跑历史 38 篇和新 50 篇。

预期：

- 减少对原始 38 篇过拟合。
- 能判断优化是否真的泛化。

## 测试计划

### 单元测试

- evidence group 构建不跨 paper。
- formula chunk 能找到 parent/nearby explanation。
- table chunk 能找到 result/conclusion context。
- claim index 能从 paragraph 提取 claim 并映射回 chunk。
- equivalent evidence coverage 不会把无关 chunk 算对。
- failure reason 能区分 true missing 和 equivalent supported。

### 集成测试

- 小型 fixture 跑完整 golden set -> retrieval -> answer eval。
- 验证 report 包含 strict/equivalent 指标。
- 验证 answer sample metadata 包含 evidence group、expansion reason、source locator。
- 验证 promotion checklist 能读取新指标。

### 真实 benchmark

固定三组：

```text
historical_38
new50_20260629
new50_future_blind
```

命令模板：

```powershell
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe -m business.research.rag.cli.run_benchmark_suite `
  --papers-dir .newsroom\papers-blind-new50-20260629 `
  --output-dir .newsroom\eval\rag-evidence-pack-v1-new50-YYYYMMDD `
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
| 等价证据过宽导致虚高 | 等价证据只能来自结构边、claim 映射或同源 locator，不允许任意相似 chunk |
| context 扩展导致噪声太多 | evidence pack 有预算，按 primary > interpretation > nearby 排序 |
| citation claim 抽取质量不稳 | 首版用 deterministic 规则，LLM judge 只抽检，不进入核心 gate |
| strict 指标下降但 equivalent 指标上升 | report 同时展示 strict/equivalent gap，promotion gate 必须检查 |
| 公式自然锚点仍然太弱 | 后续可加 equation-specific field reranker 或 formula symbol index |
| 新 50 篇集仍可能偏领域 | 保留多个 held-out 新论文集，按领域/时间拆分报告 |

## 最终形态

用户问：

```text
这个公式是什么意思？
哪段支撑这个 claim？
实验结果说明什么？
```

系统不再只找一个孤立 chunk，而是形成证据组：

```text
primary evidence: 公式 / 表格 / 图 / claim passage
interpretation context: 解释段 / 结果段 / conclusion
locator context: source_locator / image_ref / page / bbox
relations: formula_parent_context / referenced_by / claim_source
```

回答时引用证据组里的关键证据；评测时同时检查 strict gold id、等价证据、事实覆盖和引用 grounding。

这能把 Paper RAG 从“单点召回”推进到“可追溯证据链召回”，也是解决新论文泛化里 answer layer 不稳的关键一步。
