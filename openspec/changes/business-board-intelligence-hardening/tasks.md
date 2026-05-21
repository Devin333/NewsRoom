## 1. OpenSpec Validation

- [x] 1.1 Validate `business-board-intelligence-hardening` with `openspec validate --strict`.

## 2. Board Intelligence

- [x] 2.1 Implement board-specific scoring features, badges, quality checks, and ranking reasons for AI News, Project Radar, Paper Radar, and Community Pulse.
- [x] 2.2 Wire concrete board services and workflows to apply their board-specific policies, ranking rules, and presenters before returning BoardRunResult.

## 3. Layer Decoupling

- [x] 3.1 Move extraction logic into entity/topic/technology/claim extractors and taxonomy classifier, leaving ExtractionPipeline as orchestration.
- [x] 3.2 Move relation candidate logic into named linkers and validator, leaving RelationPipeline as orchestration.
- [x] 3.3 Move analysis scoring logic into trend/quality/maturity/impact/radar analyzers, leaving AnalysisPipeline as orchestration.

## 4. Cross-Board and Feedback

- [x] 4.1 Strengthen technology journey ordering, insight guard results, and blocking metadata for weak or broken cross-board chains.
- [x] 4.2 Convert board and cross-board quality failures into feedback events, learning signals, and manual policy candidates.

## 5. Tests and Acceptance

- [x] 5.1 Add or update unit tests for board-specific ranking/presentation, independent layer helpers, cross-board guards, and no-raw interface contracts.
- [x] 5.2 Run compile, phase tests, interface tests, business tests, and `python -m scripts.dev test`; fix failures forward.
