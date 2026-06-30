# Tasks

- [x] 1.1 Add Stage 14 PRD for Gold Judge and human spot-check quality loop.
- [x] 1.2 Add OpenSpec requirements for matrix judge passthrough, stratified judge sampling, structured human annotations, gold quality gates, and fix manifests.
- [x] 2.1 Pass gold judge and answer judge settings through `BenchmarkMatrixConfig` and `run_benchmark_matrix.py`.
- [x] 2.2 Include gold quality summaries in `benchmark_matrix_report.json` and markdown.
- [x] 3.1 Stratify gold judge sampling by QA type with deterministic ordering and high-risk priority.
- [x] 3.2 Add `by_qa_type`, pass rate, and error rate to `GoldEvidenceJudgeReport`.
- [x] 4.1 Validate and summarize structured human spot-check annotations.
- [x] 4.2 Add human spot-check pass/warning/fail/schema-error metrics to reports.
- [x] 5.1 Add gold judge quality and optional human spot-check quality checks to promotion checklist.
- [x] 5.2 Write `gold_judge_failures.jsonl`, `gold_judge_warnings.jsonl`, and `gold_fix_manifest.json`.
- [x] 6.1 Add focused unit/integration tests for the new behavior.
- [x] 6.2 Run OpenSpec validation, focused RAG tests, and compile.
