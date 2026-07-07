## Context

The project already has `paper_benchmark_ingest.ingest_benchmark_papers`, which fetches arXiv source packages, parses them, and writes `research_document.json`. The missing piece is selecting the exact ids needed by the curated golden set.

## Decisions

1. Implement the selection logic separately from the generic benchmark ingester.
   - Rationale: golden-set coverage is an evaluation/readiness concern, while fetching/parsing remains the benchmark ingester's job.

2. Default to missing-only behavior.
   - Rationale: this command should be safe to run as a repair step and avoid re-fetching already parsed papers unless `--force` is provided.

3. Return non-zero when any selected ingest fails.
   - Rationale: operators and CI-like scripts need a clear signal that corpus readiness is still incomplete.

## Non-Goals

- Commit generated `.newsroom/papers` artifacts.
- Change golden set membership.
- Replace `paper_benchmark_ingest`.
