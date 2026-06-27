## ADDED Requirements

### Requirement: Kernel scores answer-level grounding
The RAG kernel SHALL provide deterministic answer-level scoring for generic RAG answers.

#### Scenario: Answer score includes grounding and success
- **WHEN** an answer metric case contains expected facts, gold evidence ids, context evidence ids, cited evidence ids, and source locators
- **THEN** the kernel score includes fact coverage, retrieval context coverage, citation grounding, source locator grounding, answer success, and failure reason

### Requirement: Kernel supports structured fact matching
The RAG kernel SHALL support deterministic soft matching for long or structured expected facts.

#### Scenario: Structured figure or equation facts match concise answers
- **WHEN** an expected fact contains structural labels, captions, nearby context, or equation markup
- **THEN** structural noise is ignored before token-overlap matching

### Requirement: Paper answer evaluation uses kernel scoring
Research answer evaluation SHALL use the kernel answer scorer while preserving Paper benchmark output contracts.

#### Scenario: Research answer score shape remains compatible
- **WHEN** Research scores an evidence answer sample
- **THEN** the returned Research score still includes the original sample, fact coverage, citation grounding, source locator grounding, retrieval context coverage, citation gold coverage, matched facts, missing facts, answer success, and failure reason
