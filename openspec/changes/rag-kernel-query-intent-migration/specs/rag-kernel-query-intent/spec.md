## ADDED Requirements

### Requirement: Kernel classifies query intent with domain-neutral rules
The RAG kernel SHALL provide a rule-based query intent classifier that matches query text against caller-provided rules.

#### Scenario: First matching rule wins
- **WHEN** multiple rules could match a query
- **THEN** the classifier returns the intent from the first matching rule
- **AND** rule ordering remains controlled by the caller

#### Scenario: No rule matches
- **WHEN** no signals match the query
- **THEN** the classifier returns the caller-provided default intent

### Requirement: Kernel validates query intent rules
The RAG kernel SHALL reject query intent rules without an intent or without signals.

#### Scenario: Rule has no intent
- **WHEN** a rule has an empty intent
- **THEN** rule construction fails

#### Scenario: Rule has no signals
- **WHEN** a rule has no non-empty signals
- **THEN** rule construction fails

### Requirement: Paper routing uses kernel rule matching
Research routing SHALL use the kernel query intent matcher while keeping Paper-specific routing semantics in Research.

#### Scenario: Paper route behavior is preserved
- **WHEN** Research classifies figure, table, formula, result, comparison, contribution, or method questions
- **THEN** generic rule matching is performed by `framework/rag/retrieval`
- **AND** Paper-specific intent names, filters, section role filters, propositions, and route construction remain Research-owned
