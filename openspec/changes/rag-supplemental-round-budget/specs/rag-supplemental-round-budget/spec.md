## ADDED Requirements

### Requirement: Supplemental answer repair has an independent round budget
RAG generation SHALL bound supplemental answer repair with `generation_policy.max_supplemental_rounds` instead of consuming main retrieval `rounds` or `replans` budget.

#### Scenario: Main replan budget is exhausted
- **WHEN** an answer attempt fails with unsupported claims
- **AND** another generation attempt remains
- **AND** `generation_policy.max_supplemental_rounds` allows a repair round
- **THEN** the supplemental retrieval round SHALL run even if main retrieval `max_rounds` or `max_replans` are exhausted
- **AND** the budget snapshot SHALL NOT increment `rounds_used` or `replans_used` for that supplemental round

#### Scenario: Supplemental round budget is exhausted
- **WHEN** an answer attempt fails with unsupported claims
- **AND** `generation_policy.max_supplemental_rounds` is exhausted
- **THEN** the supplemental retrieval round SHALL be skipped
- **AND** the transcript event SHALL include a stable `reason_code`

### Requirement: Supplemental repair still obeys deterministic execution budgets
Supplemental answer repair SHALL still be checked by deterministic budget gates for query, source-read, memory-hit, context, and worker-call usage.

#### Scenario: Supplemental plan exceeds execution budget
- **WHEN** supplemental repair projects usage beyond the remaining execution budget
- **THEN** deterministic budget verification SHALL reject the plan before uncontrolled work runs

### Requirement: Supplemental skip reasons are reported in metrics
RAG session metrics SHALL aggregate supplemental skipped event reason codes.

#### Scenario: Supplemental repair is skipped
- **WHEN** one or more supplemental rounds are skipped
- **THEN** metrics SHALL include counts grouped by supplemental skip `reason_code`
