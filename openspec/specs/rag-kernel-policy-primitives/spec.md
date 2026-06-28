# rag-kernel-policy-primitives Specification

## Purpose
TBD - created by archiving change rag-kernel-policy-primitives. Update Purpose after archive.
## Requirements
### Requirement: Kernel evaluates intent allow lists
The RAG kernel SHALL provide a domain-neutral helper for checking whether an intent is allowed by an optional allow list.

#### Scenario: Empty allow list means all intents
- **WHEN** the allow list is empty
- **THEN** any intent is allowed

### Requirement: Kernel computes position decay
The RAG kernel SHALL provide a domain-neutral helper for section-distance position decay.

#### Scenario: Current section receives alpha
- **WHEN** the section index equals the current index
- **THEN** the helper returns alpha
- **AND** farther sections receive smaller positive scores when sigma is positive

### Requirement: Kernel clamps intent budgets
The RAG kernel SHALL provide a domain-neutral helper for intent-specific context budgets.

#### Scenario: Budget is bounded by global limits
- **WHEN** an intent budget exceeds global chunk or token limits
- **THEN** the returned budget is clamped to those limits

### Requirement: Paper policy uses kernel primitives
Research retrieval policy SHALL use kernel policy helpers for generic calculations while keeping Paper-specific policy configuration in Research.

#### Scenario: Paper policy outputs remain compatible
- **WHEN** Research asks for position weights, parent budgets, or reranker intent gates
- **THEN** the generic calculation is delegated to `framework/rag/core`
- **AND** Paper-specific intent names, weights, and named policy construction remain Research-owned

