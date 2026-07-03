## ADDED Requirements

### Requirement: Generated paper RAG answers are gated-only
The paper RAG service SHALL NOT generate answers through the legacy direct answer generator.

#### Scenario: Gated answer is requested
- **WHEN** `rag_ask(generate=True)` is called
- **THEN** the service SHALL run the bounded gated Harness session
- **AND** the response generation mode SHALL be `gated_harness`

#### Scenario: Legacy direct generation is requested by a direct caller
- **WHEN** `rag_ask(generate=True, gated=False)` is called
- **THEN** the service SHALL fail closed before retrieval or answer generation

### Requirement: CLI does not expose legacy direct answer generation
The `paper ask` CLI SHALL NOT expose a flag that bypasses gated Harness answer generation.

#### Scenario: CLI answer mode is requested
- **WHEN** `paper ask <paper_id> <question> --answer` is parsed
- **THEN** the command SHALL have no legacy-direct bypass option

#### Scenario: Removed legacy flag is supplied
- **WHEN** `paper ask <paper_id> <question> --answer --legacy-direct-answer` is parsed
- **THEN** argument parsing SHALL reject the command
