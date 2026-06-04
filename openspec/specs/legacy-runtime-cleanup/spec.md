## Purpose
Define cleanup requirements for retiring obsolete board, paper, scoring, interface, and legacy test assets after Harness + Research replacements are accepted.

## Requirements

### Requirement: Stage Zero Audit Inventory
Stage 0 SHALL produce `docs/prd/harness-research-runtime/audit-inventory.md` with keep, adapt, and delete classifications for `framework`, `business`, `interfaces`, `tests`, `openspec/specs`, and `docs/architecture`.

#### Scenario: Delete candidate has cleanup metadata
- **WHEN** an inventory row is categorized as `delete`
- **THEN** it MUST include a reason, replacement, deletion phase, and tests action

### Requirement: Preserve Useful Framework Assets
Legacy cleanup SHALL preserve or adapt useful domain-neutral assets for LLM, tools, memory, skills, artifacts, events, workers, scoring, governance, shared primitives, specs, and workflow utilities when they serve Harness + Research.

#### Scenario: Neutral framework asset is kept
- **WHEN** a framework module has reusable runtime value and no business dependency
- **THEN** the inventory MUST classify it as `keep` or `adapt`
- **AND** cleanup MUST NOT delete it only because old board workflows also used it

### Requirement: Delete Obsolete Legacy Business Assets
Legacy business assets that exist only for old board, paper_radar, old paper API, old reader payload, old UI compatibility, or superseded control flow SHALL be deleted in stage 8 or stage 9 after replacement Harness + Research coverage exists.

#### Scenario: Old paper_radar compatibility is removed
- **WHEN** Research service and API replacements are accepted
- **THEN** cleanup MUST remove old paper_radar compatibility paths that no longer serve Harness + Research
- **AND** cleanup MUST NOT keep adapters solely for old paper payloads or old UI consumers

### Requirement: Delete Obsolete Interface Assets
Old paper-specific service and API routes SHALL be deleted when Research backend interfaces replace them. Interface layers SHALL call application services rather than reaching into executors, stores, or old business runners directly.

#### Scenario: Old papers router is retired
- **WHEN** Research API routes provide the accepted backend surface
- **THEN** `interfaces/api/routers/papers.py` and old `interfaces/services/paper_*.py` paths marked for deletion MUST be removed or replaced according to the inventory

### Requirement: Replace Or Remove Legacy Tests
Tests for old behavior SHALL be replaced with Harness + Research tests or deleted only when the old behavior is explicitly deprecated. Tests MUST NOT be deleted to hide unrelated failures.

#### Scenario: Deprecated paper API test is removed with replacement
- **WHEN** a paper API behavior is deprecated by Research API behavior
- **THEN** the old test MAY be deleted in the cleanup phase
- **AND** the replacement Research test MUST cover the new accepted behavior

### Requirement: Cleanup Maintains Architecture Boundaries
Cleanup SHALL enforce that framework does not import business, interfaces, or concrete infrastructure; `business/research` does not import old paper_radar, interfaces, or concrete infrastructure; and interface services remain entry-layer coordinators.

#### Scenario: Boundary test blocks compatibility leak
- **WHEN** a compatibility adapter introduces a forbidden dependency across these boundaries
- **THEN** boundary tests MUST fail
- **AND** cleanup MUST remove or relocate the adapter rather than preserving the leak
