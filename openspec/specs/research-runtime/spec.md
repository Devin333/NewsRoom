## Purpose
Define the Research runtime domain boundary, single-paper analysis loop, reader repair memory, backend interface, production data-source expectations, and UI scope exclusions.

## Requirements

### Requirement: Research Domain Boundary
Research runtime SHALL live under `business/research` and SHALL express Research domain models, ports, use cases, workflow specs, and business rules. `business/research` MUST NOT import `business/boards/paper_radar`, `interfaces`, or concrete `infrastructure` modules.

#### Scenario: Research imports stay inside allowed boundaries
- **WHEN** import boundary tests scan `business/research`
- **THEN** no import may target `business.boards.paper_radar`, `interfaces`, or `infrastructure`
- **AND** Research may depend only on domain-neutral framework contracts and Research-owned modules

### Requirement: Research Product Scenarios Precede Domain Modeling
Research implementation SHALL first define product scenarios for paper card, taxonomy, reader, reading session, code repository, benchmark, method graph, agent intelligence, and Research RAG before domain models and workflows are finalized.

#### Scenario: Domain modeling consumes scenarios
- **WHEN** stage 5 domain modeling begins
- **THEN** the Research product scenario artifact from stage 5A MUST exist
- **AND** domain models MUST map back to those scenarios rather than old paper_radar payloads

### Requirement: Research Single Paper Loop
Research runtime SHALL support a single-paper analysis loop controlled by Harness. The loop SHALL use Research domain models, Research ports, bounded context, deterministic gates, and fake LLM in tests.

#### Scenario: Single paper analysis is Harness-controlled
- **WHEN** a fake LLM returns candidate analysis for one paper
- **THEN** Harness MUST verify the candidate with Research gates before producing a report artifact
- **AND** the LLM result MUST NOT decide routing, memory writes, or publication

### Requirement: Reader Repair Memory
Reader repair experiences SHALL first be recorded as episodic or procedural memory and MAY later seed skill evolution only through Harness-controlled consolidation and promotion.

#### Scenario: Repair success does not patch active skill
- **WHEN** a reader repair run succeeds for a malformed paper source
- **THEN** the repair result MUST be written as memory through Harness policy
- **AND** no active skill package may be modified during that ordinary Research run

### Requirement: Research Backend Interface
Research backend access SHALL be exposed through Research-specific application service and API router paths. The Research service and router MUST NOT reuse old paper API service classes, old paper cache payloads, or `interfaces/api/routers/papers.py`.

#### Scenario: Research API uses Research service
- **WHEN** a Research API endpoint handles a single-paper analysis request
- **THEN** it MUST call the Research application service
- **AND** it MUST NOT instantiate `PapersApplicationService` or read old paper_radar public payloads

### Requirement: Research Production Data Sources
Production Research code SHALL use real data sources, real domain models, and real runtime paths. Tests MAY use fake LLMs, fake repositories, fake readers, and in-memory stores to reduce development cost.

#### Scenario: Test fake does not leak into production service
- **WHEN** production Research service composition is inspected
- **THEN** fake LLM, fake repository, and fixture-only readers MUST NOT be the default production dependencies

### Requirement: Research UI Out Of Scope
This change SHALL NOT implement or migrate UI surfaces for Research. Frontend paper UI and old paper reader UI compatibility are outside the Harness + Research runtime scope.

#### Scenario: Backend phase leaves UI unchanged
- **WHEN** stages 0 through 7 are completed
- **THEN** no frontend Research migration or paper UI compatibility adapter is required for acceptance
