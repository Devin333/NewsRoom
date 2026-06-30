# 阶段 14：Paper RAG Gold Judge 与人工抽检闭环 PRD

## 背景

阶段 13 已经把 Paper RAG benchmark 从单一 `gold_chunk_id` 推进到 evidence group、equivalent evidence、claim-level citation retrieval 和三套 held-out benchmark matrix。

当前三套真实数据集都能通过 promotion gate，但每套仍有一个 warning：

```text
blind_semantic_without_gold_judge
```

这说明 `blind_semantic` 的 gold evidence 主要来自 deterministic 结构规则，例如公式 chunk、caption、nearby paragraph、claim chunk、evidence group，而还没有额外 judge 确认“这个 gold evidence 是否真的足够支撑问题和答案事实”。

这不是 blocker，但会降低 benchmark 可信度。后续需要补齐：

```text
deterministic gold audit
  -> LLM gold judge 抽检
  -> human spot check 复核
  -> gold quality gate
  -> gold fix manifest
```

## 外部方法参考

- RAGAS：用 LLM 自动评估 faithfulness、answer relevancy、context precision/recall，适合快速自动化评测。
- ARES：用少量人工标注校准 LLM judge，再扩大到自动评估，适合当前阶段。
- RAGChecker / RefChecker：把答案拆成 claim，逐条判断 claim 是否被 context 支持，适合细粒度诊断。
- RAGTruth / ALCE / CRAG / GaRAGe：强调人工标注、citation grounding 和 grounded answer，可信度更强但成本更高。

本项目首版采用 ARES 风格：LLM judge 做分层抽检，人工 spot check 复核高风险样本，deterministic gate 仍是主门禁。

## 目标

1. 消除三数据集 matrix 中的 `blind_semantic_without_gold_judge` warning。
2. matrix runner 支持 `gold_judge` 和 `answer_judge` 参数透传。
3. gold judge 按 `qa_type` 分层抽样，覆盖 citation、formula、table、figure、experiment result。
4. human spot check 使用结构化 annotation schema，并在 report 中聚合。
5. promotion checklist 增加 gold quality gate。
6. judge warning/fail 生成可修复 manifest，支持后续 gold 修复闭环。

## 非目标

- 不用 LLM judge 替代 deterministic gold audit。
- 不要求第一版全量人工标注。
- 不训练新 judge 模型。
- 不让 LLM 自动修改 gold evidence。
- 不把 arbitrary semantic similarity 当作 gold 修复依据。

## V1：Matrix 支持 Gold Judge

### 交付

- `BenchmarkMatrixConfig` 增加：
  - `gold_judge_mode`
  - `gold_judge_sample_size`
  - `gold_judge_max_evidence_chars`
  - `answer_judge_mode`
  - `answer_judge_sample_size`
  - `spot_check_annotations_path`
- `run_benchmark_matrix.py` CLI 增加对应参数。
- matrix summary 输出每个 dataset 的：
  - `gold_judge_sample_size`
  - `gold_judge_pass_rate`
  - `gold_judge_failed`
  - `gold_judge_error_rate`
  - `gold_quality.fully_audited`

### 验收

- matrix 启用 `--gold-judge llm` 后不再出现 `blind_semantic_without_gold_judge`。
- 每个 dataset 的 `benchmark_suite_report.json` 包含 `gold_judge`。
- `benchmark_matrix_report.json` 汇总 gold quality。

## V2：分层 Gold Judge 抽样

### 交付

gold judge 不再简单取前 N 条，而是按 `qa_type` 分层抽样：

```text
citation_qa
formula_qa
formula_explanation_qa
table_qa
figure_qa
experiment_result_qa
```

高风险样本优先：

- deterministic gold audit warning/fail
- figure/table/formula/citation 类样本
- answer facts 缺失
- source locator / image evidence 不足

### 验收

- `gold_judge.by_qa_type` 非空。
- 主要 QA 类型在样本足够时都被覆盖。
- 抽样使用 `split_seed`，可复现。

## V3：Human Spot Check 标注规范

### annotation schema

```json
{
  "paper_id": "2606.xxxxx",
  "qa_type": "formula_qa",
  "question": "...",
  "gold_evidence_ok": true,
  "answer_ok": true,
  "citation_ok": true,
  "label": "pass",
  "reason": "Gold formula and nearby explanation support the expected answer.",
  "annotator": "human",
  "reviewed_at": "2026-06-30"
}
```

允许 label：

```text
pass
warning
fail
needs_fix
```

### 验收

- annotation JSONL 解析时校验 label 和必填字段。
- report 输出：
  - `human_spot_check_pass_rate`
  - `human_spot_check_warning_count`
  - `human_spot_check_fail_count`
  - `by_qa_type`
  - `schema_error_count`
- 缺少 annotation 不阻塞 benchmark，但不能标记为 fully audited。

## V4：Promotion Gate 升级

新增 gate：

```text
gold_judge_sample_size >= requested sample size
gold_judge_pass_rate >= 0.90
gold_judge_failed == 0
gold_judge_error_rate <= 0.05
human_spot_check_pass_rate >= 0.90  如果提供人工标注
```

### 验收

- promotion checklist 包含 `gold_judge_quality`。
- 如果 blind semantic 没启用 gold judge，check 为 warning，而不是 silent pass。
- 如果 gold judge fail > 0，不能 promotion。

## V5：Gold Fix Loop

新增产物：

```text
gold_judge_failures.jsonl
gold_judge_warnings.jsonl
gold_fix_manifest.json
```

每条问题样本包含：

```json
{
  "paper_id": "...",
  "qa_type": "...",
  "question": "...",
  "status": "fail",
  "judge_reason": "...",
  "suggested_action": "replace_gold_chunk | add_equivalent_evidence | drop_question | rewrite_question"
}
```

### 验收

- judge warning/fail/error 会写入 manifest。
- manifest 汇总 action counts。
- 修复后可重新跑 judge 并比较失败数。

## 最终命令

```powershell
$env:OPENAI_BASE_URL="https://unity2.ai/v1"
$env:OPENAI_MODEL="gpt-5.4-mini"
$env:OPENAI_API_KEY="..."

.\.venv\Scripts\python.exe -m business.research.rag.cli.run_benchmark_matrix `
  --dataset-manifest .newsroom\eval\rag-evidence-pack-v5-required-datasets-20260629.json `
  --output-dir .newsroom\eval\rag-gold-judge-matrix `
  --question-profile blind_semantic `
  --retrieval-policy paper_blind_semantic_rag_v1 `
  --gold-judge llm `
  --gold-judge-sample-size 30 `
  --answer-eval `
  --answer-eval-sample-size 20 `
  --answer-judge llm `
  --answer-judge-sample-size 20 `
  --spot-check-sample-size 20 `
  --no-render-page-visual
```

## 最终形态

完成后，Paper RAG benchmark 的可信度分三层：

```text
deterministic gold audit
+ LLM gold judge
+ human spot check
```

这样 promotion 不再只是“系统自己按结构规则评自己”，而是有自动 judge 和人工抽检两层背书。
