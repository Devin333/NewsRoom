## MODIFIED Requirements

### Requirement: Research Domain Boundary

Research runtime SHALL live under `business/research` and SHALL express Research domain models, ports, use cases, Graph definitions, and business rules. `business/research` MUST NOT import `business/boards/paper_radar`, `interfaces`, concrete `infrastructure` modules, `framework.workflow`, or the retired Harness Workflow namespace.

#### Scenario: Research imports stay inside allowed boundaries

- **WHEN** import boundary tests scan `business/research`
- **THEN** no import may target `business.boards.paper_radar`, `interfaces`, `infrastructure`, `framework.workflow`, or `framework.harness.workflow`
- **AND** Research may depend only on domain-neutral framework contracts and Research-owned Graph modules

### Requirement: Research Product Scenarios Precede Domain Modeling

Research implementation SHALL first define product scenarios for paper card, taxonomy, reader, reading session, code repository, benchmark, method graph, agent intelligence, and Research RAG before domain models and Graph definitions are finalized.

#### Scenario: Domain modeling consumes scenarios

- **WHEN** stage 5 domain modeling begins
- **THEN** the Research product scenario artifact from stage 5A MUST exist
- **AND** Graph definitions and domain models MUST map back to those scenarios rather than old paper_radar payloads

### Requirement: Research Single Paper Loop

Research runtime SHALL support a single-paper analysis loop controlled by Harness Graph. The loop SHALL use Research domain models, Research ports, bounded context, deterministic gates, and fake LLM in tests. Every quality gate declared by the paper-analysis, paper-RAG, and reader-repair Graph definitions MUST resolve to an exact Research-owned deterministic gate implementation and version before the run starts.

#### Scenario: Single paper analysis is Graph-controlled

- **WHEN** a fake LLM returns candidate analysis for one paper
- **THEN** Harness MUST verify the candidate with the exact Research gate declared for the current Graph node before producing a report artifact
- **AND** the LLM result MUST NOT decide routing, memory writes, or publication

#### Scenario: Research Graph declarations are executable

- **WHEN** Research composition loads a paper-analysis, paper-RAG, or reader-repair Graph definition
- **THEN** every declared gate reference MUST have one registered deterministic implementation and committed execution test
- **AND** a name-only metadata gate with no implementation MUST be removed or rejected rather than treated as passed

#### Scenario: Research gate registration is incomplete

- **WHEN** a Research Graph references an unknown or unavailable gate version
- **THEN** Harness MUST reject the run before any Research worker or external source is called
- **AND** no report, reader payload, memory write, or artifact publication may be accepted
