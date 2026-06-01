## 1. OpenSpec

- [x] 1.1 Create source-comparison/evolution proposal, tasks, and specs.
- [x] 1.2 Validate `paper-reader-source-compare-evolution` with strict OpenSpec validation.

## 2. Source Comparison Runtime

- [x] 2.1 Add a deterministic `PaperSourceComparer` that compares compiled blocks/assets against source/native paper invariants.
- [x] 2.2 Persist `source-comparison-report.json` and include the report in compile status/result payloads.
- [x] 2.3 Treat content/asset/source-traceability failures as hard publication blockers.
- [x] 2.4 Keep AI review as non-blocking diagnostics for all verdicts, including fail/unavailable.

## 3. Evolution Memory

- [x] 3.1 Convert source-comparison pass/fail lessons into EvidenceMemory, DecisionMemory, and EventMemory records.
- [x] 3.2 Ensure memory writes are best-effort and never hide the comparison report artifact when memory storage is unavailable.
- [x] 3.3 Add a reusable skill document for paper reader source comparison practices.

## 4. Verification

- [x] 4.1 Add source-comparison unit tests for pass, hard failure, source bbox, visual asset completeness, and AI review non-gating.
- [x] 4.2 Add memory-ingestion tests for source-comparison lessons.
- [x] 4.3 Run targeted paper reader/compiler tests.
- [x] 4.4 Run `python -m scripts.dev compile`.
- [x] 4.5 Commit the completed code and OpenSpec change.
