## Context

The archived final-target change created the expected business-layer shape: foundation contracts, five pipeline layers, board vertical slices, cross-board services, and interface-safe DTOs. Several modules still delegate most behavior to generic base pipelines, so the next increment is to move deterministic rules into the named modules and make board outputs visibly different by business purpose.

## Goals / Non-Goals

**Goals:**
- Make each of the four boards apply board-specific ranking features, badges, quality checks, and presentation metadata.
- Move extraction, relation, and analysis rules behind named extractor/linker/analyzer classes so each can be tested without private pipeline calls.
- Require cross-board insights to pass ordered evidence-chain and multi-board support guards before being treated as strong insights.
- Feed quality failures into the existing feedback and policy candidate objects without automatic activation.

**Non-Goals:**
- No new public DTO schema, no raw payload exposure, and no interface bypass around board services.
- No real LLM calls, web console, agent swarm, automatic policy activation, or `business/evolution` package.
- No broad worker integration beyond compatibility with existing service calls.

## Decisions

- Board services will keep inheriting `BoardServiceBase`, but each concrete service will override post-processing hooks to apply its board-specific policy, ranking, presenter, and quality behavior. This keeps the runtime path stable while making board differences explicit.
- Existing DTO fields will carry richer semantics: `ranking_features`, `ranking_reason`, `badges`, `metrics`, `metadata`, and `quality`. New helper models can be internal to each board package.
- `ExtractionPipeline`, `RelationPipeline`, and `AnalysisPipeline` will become orchestration surfaces over public helper classes. Compatibility methods can remain temporarily, but tests will target helper classes directly.
- Cross-board guard results will be attached in metadata and quality summaries rather than changing the interface DTO wire shape.
- Feedback learning remains manual: quality failures generate feedback events and policy candidates, but activation stays operator-controlled.

## Risks / Trade-offs

- Deterministic rules can look simplistic compared with PRD intelligence language -> keep them explainable and testable, with policy parameters ready for later tuning.
- Refactoring pipeline internals can break existing tests that call private methods -> preserve private wrappers where practical while adding public helpers.
- Richer board metadata could accidentally leak raw inputs -> add explicit tests asserting no `raw_payload` in interface-facing DTOs.
- Cross-board guards can over-block sparse data -> start with transparent guard reasons and warning/block severity rather than silent filtering.
