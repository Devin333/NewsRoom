## Purpose
Define the Harness-governed skill evolution lifecycle, including candidate validation, held-out evaluation, promotion, release, rollback, and repair-memory seeding rules.

## Requirements

### Requirement: Harness-Controlled Skill Evolution
Skill evolution SHALL be controlled by Harness. LLM optimizers MAY propose skill candidates or patches, but MUST NOT modify active skill packages, decide promotion, skip held-out evals, disable quality gates, or publish production versions.

#### Scenario: Candidate patch cannot publish itself
- **WHEN** an LLM optimizer returns a skill patch candidate
- **THEN** Harness MUST store it as a candidate
- **AND** the active skill package MUST remain unchanged until validation, eval, approval, promotion, and versioned release pass

### Requirement: Skill Candidate Validation
Harness skill evolution SHALL validate candidate packages with static checks, manifest/schema validation, quality gates, dependency policy, and rollback metadata before any eval or promotion.

#### Scenario: Invalid candidate is rejected before eval
- **WHEN** a candidate skill package has an invalid manifest or missing schema
- **THEN** Harness MUST reject the candidate before held-out eval runs
- **AND** Harness MUST record the validation failure in the candidate trace

### Requirement: Held-Out Evaluation And Promotion
Harness SHALL run held-out evaluations before promoting a skill candidate. Promotion MUST require deterministic acceptance criteria, versioned release metadata, and a rollback plan.

#### Scenario: Eval failure blocks promotion
- **WHEN** a candidate fails a held-out eval threshold
- **THEN** Harness MUST block promotion
- **AND** the candidate MUST remain inactive with a recorded eval result

### Requirement: Skill Runtime Assets Are Reused Through Ports
Harness skill evolution SHALL reuse existing skill package loading, runtime execution, schema validation, quality gates, and evaluation assets through explicit ports when those assets satisfy the candidate lifecycle contracts. Reused assets MUST NOT decide production promotion by themselves.

#### Scenario: Existing skill package validator supports evolution
- **WHEN** Harness evaluates a skill candidate package
- **THEN** it MAY call the existing package validator through a port
- **AND** the validator MUST NOT decide production promotion by itself

### Requirement: Business Repair Memory Before Skill Evolution
Research reader repair, paper parsing fixes, and business repair experiences SHALL first be stored as memory and consolidated into procedural strategies before they can seed skill evolution.

#### Scenario: Consolidated strategy seeds candidate
- **WHEN** multiple reader repair memories are consolidated into a stable procedural strategy
- **THEN** Harness MAY generate a skill candidate from that strategy
- **AND** the candidate MUST still pass validation, held-out eval, promotion, and rollback gates

### Requirement: Active Skill Rollback
Harness skill evolution SHALL preserve rollback capability for every promoted production skill version.

#### Scenario: Promoted skill is rolled back
- **WHEN** a promoted skill version later fails a production quality gate or rollback trigger
- **THEN** Harness MUST deactivate that version according to the rollback plan
- **AND** Harness MUST restore the previous approved version or halt skill use if no safe version exists
