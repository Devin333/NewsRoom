## Why

The enterprise RAG review found that parser bake-off reports still lack a penalized fairness score and there is no explicit acceptance gate for validating the default parser cascade on a real multi-paper artifact set. Without these controls, a parser can look strong by omitting hard papers or by reporting raw quality averages that ignore ingest failures.

## What Changes

- Add penalized parser bake-off metrics that combine parse success, parser quality, RAG retrieval quality, warnings, and ingest failures into auditable scores.
- Add an acceptance gate for parser cascade bake-off artifacts, including a 20-paper minimum by default.
- Add report JSON and Markdown fields for penalized score, penalty details, and acceptance checks.
- Expose acceptance thresholds through the parser bake-off report CLI.
- Add tests covering penalized scoring, failure penalties, cascade acceptance pass/fail, and CLI argument parsing.

## Capabilities

### New Capabilities
- `parser-cascade-bakeoff-acceptance`: Parser bake-off reports include penalized scoring and cascade acceptance gates for real artifact sets.

### Modified Capabilities

## Impact

- Affected Research RAG evaluation code: `business/research/rag/evaluation/paper_parser_bakeoff_report.py`.
- Affected CLI: `business/research/rag/cli/run_parser_bakeoff_report.py`.
- Affected tests: parser bake-off report and CLI tests.
- No production parser routing or public API schema changes.
