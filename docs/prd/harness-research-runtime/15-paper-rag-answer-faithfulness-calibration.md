# 阶段 15：Paper RAG Answer Faithfulness 与人工抽检校准闭环 PRD

## 背景

阶段 14 已经补齐 Paper RAG 的 gold evidence judge 和人工抽检入口。回答层仍需要更细的可信度闭环：不仅要知道 answer success 是否通过，还要知道答案里的每条 claim 是否被 context 支持、引用是否指向正确 evidence，以及 LLM judge 是否和人工抽检一致。

参考外部方法：

- RAGAS：自动评估 faithfulness、answer relevancy、context precision/recall。
- ARES：用少量人工标注校准自动 judge。
- RAGChecker：把回答拆成 claim，诊断 retrieval 和 generation。
- RAGTruth / GaRAGe：强调 hallucination 标注与 grounding passage 对齐。

本阶段采用 ARES + RAGChecker 风格：deterministic answer eval 仍是主门禁，LLM judge 输出 claim-level 诊断，人审 annotation 用来校准 judge。

## 目标

1. `--answer-judge llm` 输出结构化 claim-level judge 结果。
2. 检查 citation 是否真的支撑对应 claim。
3. human spot check schema 增加 retrieval/context/faithfulness/citation 字段。
4. 汇总 judge-human agreement、precision、recall、false positive、false negative。
5. 输出 answer judge 失败样本和 `answer_fix_manifest.json`。
6. matrix report 汇总 answer judge 关键指标。

## 非目标

- 不训练新 judge 模型。
- 不做 word-level hallucination 标注。
- 不让 LLM 自动修改答案、gold evidence 或 active retrieval policy。
- 不要求第一版接前端人工标注系统；先用 JSONL。

## 交付

### V1：结构化 Answer Judge

- `GenerationEvaluator` 返回每个 answer 的 `claims`、`citation_checks` 和聚合分数。
- 每条 claim 包含 `claim_text`、`verdict`、`support_chunk_ids`、`reason`。
- 聚合指标包含 `claim_support_rate`、`unsupported_claim_rate`、`contradiction_rate`、`answer_faithfulness`、`answer_relevance`。

### V2：Citation Grounding

- 每条 citation check 包含 `cited_chunk_ids`、`support_chunk_ids`、`citation_supports_claim`、`wrong_citation`、`missing_citation`。
- 报告输出 `citation_claim_support_rate`、`wrong_citation_rate`、`missing_citation_rate`、`grounded_answer_rate`。

### V3：Human Spot Check 正式化

- annotation JSONL 支持 `gold_evidence_ok`、`retrieval_ok`、`context_ok`、`answer_ok`、`faithfulness_ok`、`citation_ok`。
- report 输出 `human_answer_ok_rate`、`human_faithfulness_ok_rate`、`human_citation_ok_rate` 和 `human_by_qa_type`。

### V4：LLM Judge 与 Human 校准

- 用 `paper_id + qa_type + question` 对齐 human annotation 和 answer judge。
- 输出 `judge_human_agreement`、`judge_precision`、`judge_recall`、`judge_false_positive_rate`、`judge_false_negative_rate`。
- 输出 `human_spot_check_conflicts.jsonl`。

### V5：Answer Fix Manifest

- 输出 `answer_judge_report.json`、`answer_judge_samples.jsonl`、`answer_judge_failures.jsonl`、`answer_fix_manifest.json`。
- failure reason 使用标准化枚举，例如 `unsupported_claim`、`contradicted_claim`、`wrong_citation`、`missing_citation`、`judge_human_conflict`。
- suggested action 使用 `fix_answer_prompt`、`fix_citation_mapping`、`expand_context_assembler`、`improve_retrieval_policy`、`manual_review_required` 等。

## 验收

- 开启 `--answer-judge llm` 后，candidate output 包含 answer judge report、samples、failures 和 fix manifest。
- benchmark suite markdown 包含 claim/citation judge metrics。
- spot check annotation schema 能校验扩展字段。
- 有人工 annotation 且能和 LLM judge 对齐时，report 输出校准指标和冲突样本。
- matrix summary 输出 claim support、citation support、unsupported claim 和 judge-human agreement。
- 原有 deterministic answer eval、gold judge 和 retrieval metrics 不回退。
