## MODIFIED Requirements

### Requirement: Research Single Paper Loop
Research runtime SHALL support a single-paper analysis loop controlled by Harness. The loop SHALL use Research domain models, Research ports, bounded context, deterministic gates, and fake LLM in tests. Every quality gate declared by the paper-analysis, paper-RAG, and reader-repair workflow specs MUST resolve to an exact Research-owned deterministic gate implementation and version before the run starts.

#### Scenario: Single paper analysis is Harness-controlled
- **WHEN** a fake LLM returns candidate analysis for one paper
- **THEN** Harness MUST verify the candidate with the exact Research gate declared for the current step before producing a report artifact
- **AND** the LLM result MUST NOT decide routing, memory writes, or publication

#### Scenario: Research workflow declarations are executable
- **WHEN** Research composition loads a paper-analysis, paper-RAG, or reader-repair workflow
- **THEN** every declared gate reference MUST have one registered deterministic implementation and committed execution test
- **AND** a name-only metadata gate with no implementation MUST be removed or rejected rather than treated as passed

#### Scenario: Research gate registration is incomplete
- **WHEN** a Research workflow references an unknown or unavailable gate version
- **THEN** Harness MUST reject the run before any Research worker or external source is called
- **AND** no report, reader payload, memory write, or artifact publication may be accepted
