# Business Runtime Acceptance

## 1. Current Status

Business full productization now includes:

- productized board workflows
- productized board runners
- board artifacts
- subscription payload
- feedback events
- learning signals
- improvement recommendations
- improvement proposals
- eval runner
- cross-board intelligence
- weekly trend analysis

## 2. Runtime Acceptance Goals

Runtime acceptance verifies:

- each board can run from fixture signals
- each board writes full artifacts
- each board output is subscription-ready
- each board output includes skill trace metadata
- each board output includes feedback / improvement trace
- cross-board can aggregate four board outputs
- weekly can consume persisted daily/cross-board outputs
- eval suite passes
- smoke command runs offline

## 3. Acceptance Matrix

| Area | Acceptance Item | Test | Status |
|---|---|---|---|
| board runtime | four productized boards run offline | tests/business/boards | Covered |
| artifacts | required artifacts exist and parse | test_productized_artifact_schema_acceptance.py | Covered |
| subscription | payload targets and delivery plans exist | tests/interfaces/services | Covered |
| feedback | feedback events are emitted | tests/business/boards | Covered |
| improvement | recommendations, proposals, and approved overrides are traceable | tests/business/foundation | Covered |
| eval | productized eval suite runs with metrics | tests/business/evaluation | Covered |
| cross-board | four board outputs aggregate into intelligence | test_cross_board_productized_acceptance.py | Covered |
| weekly | weekly consumes persisted daily outputs and publishes enhanced artifacts | weekly_intelligence tests | Covered |
| CLI | news business acceptance smoke commands run offline | tests/interfaces/cli | Covered |
| API/service | services consume productized subscription payloads | tests/interfaces/services | Covered |
| persistence | LocalJson proposal store persists state transitions | tests/business/foundation | Covered |
