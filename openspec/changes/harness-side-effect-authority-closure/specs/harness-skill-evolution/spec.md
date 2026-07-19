## MODIFIED Requirements

### Requirement: Harness-Controlled Skill Evolution
Skill evolution SHALL be controlled by Harness. LLM optimizers MAY propose skill candidates or patches, but MUST NOT modify active skill packages, decide promotion, skip held-out evals, disable quality gates, or publish production versions. An active-version or release-store mutation MUST resolve a durable Harness side-effect authority decision bound to the same candidate, package hash, held-out evaluation, deterministic promotion gates, required approval, release version, rollback-plan reference, and idempotency identity; a caller-provided promotion object alone is insufficient.

#### Scenario: Candidate patch cannot publish itself
- **WHEN** an LLM optimizer returns a skill patch candidate
- **THEN** Harness MUST store it as a candidate
- **AND** the active skill package MUST remain unchanged until validation, eval, approval, promotion, and versioned release pass

#### Scenario: Ordinary run cannot activate a skill
- **WHEN** an ordinary Harness or business run returns a promotion, release, production-version, active-package, or auto-promote shaped value
- **THEN** the value MUST be rejected or retained only as non-executable candidate evidence
- **AND** release-store and active-version mutation counts MUST remain zero

#### Scenario: Unbound promotion object cannot publish
- **WHEN** a caller supplies an approved-looking promotion decision that cannot be resolved to the canonical candidate, held-out evaluation, gate evidence, approval, package hash, release version, and side-effect authority decision
- **THEN** the release boundary MUST reject publication
- **AND** the active version and release history MUST remain unchanged

#### Scenario: Provenance-bound release is published
- **WHEN** Harness records a matching evaluated candidate, deterministic promotion result, required approval, versioned rollback-plan reference, and side-effect authority decision
- **THEN** the release handler MAY publish exactly the authorized version with the recorded idempotency identity
- **AND** the active index mutation, rollback plan, and outcome MUST be durably bound to that authority decision
