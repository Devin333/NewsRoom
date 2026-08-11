## ADDED Requirements

### Requirement: Summary generation returns a structured candidate
An optional summary worker SHALL return a `ContextSummaryCandidate` containing a summary artifact ref, covered group ids, source refs, claim-to-support mappings, omitted topics, unresolved questions, tool outcomes, loss-risk level, worker/model identity, and candidate schema revision. Raw summary text SHALL be stored through the artifact port rather than embedded in durable events.

#### Scenario: Candidate covers multiple groups
- **WHEN** a worker summarizes old conversation and evidence groups
- **THEN** every summary claim identifies supporting source/group refs and the candidate declares all omitted topics and unresolved questions

#### Scenario: Worker returns free text only
- **WHEN** the summary worker omits the structured coverage, support, omission, or loss fields
- **THEN** candidate parsing fails and no context group is replaced

### Requirement: Summary candidates cannot self-promote
The summary worker and its model output MUST NOT decide that a candidate is verified, modify the active context snapshot, append `context_compaction_verified`, authorize provider dispatch, select workflow routing, or expand retry/replan budgets. Harness SHALL treat every worker result as an untrusted candidate until deterministic gates pass.

#### Scenario: Candidate claims verification
- **WHEN** worker output contains `verified=true`, a next-state instruction, or publication/tool/memory authorization
- **THEN** those fields have no authority and unsupported fields are rejected or excluded from the candidate contract

### Requirement: Source and claim support are verified deterministically
Harness SHALL verify that candidate group ids, source refs, evidence ids, span refs, artifact refs, and tool outcomes exist in the source snapshot and are authorized for the current task. Every factual summary claim MUST have at least one supporting source or group ref. Unknown or malformed refs MUST fail verification.

#### Scenario: Candidate invents an artifact outcome
- **WHEN** the candidate reports an artifact or tool outcome absent from the source snapshot
- **THEN** source verification fails and the source groups remain active

#### Scenario: Claim has no support
- **WHEN** a summary claim has no supporting ref
- **THEN** claim-support verification fails even if the summary is shorter and fluent

### Requirement: Evidence coverage and loss are explicit gates
Harness SHALL verify required evidence/source/span coverage, protected facts, unresolved conflicts, omission declarations, recent complete turns, and declared loss risk before a candidate may replace groups. A high or unknown loss risk MUST fail unless a trusted policy explicitly permits that level for the targeted non-protected groups.

#### Scenario: Required citation is omitted
- **WHEN** a summary candidate does not cover a required evidence span or its source ref
- **THEN** evidence-loss verification fails and the candidate is rejected

#### Scenario: Non-required detail is omitted transparently
- **WHEN** policy permits omission of a non-required topic and the candidate declares it in the loss report
- **THEN** the loss gate may pass while preserving the omission in durable evidence

### Requirement: Post-compaction VERIFY is aggregate and deployment aware
After any action changes group structure or content, Harness SHALL run structure, protection, tool-transaction, provenance, evidence/loss, action-budget, snapshot-integrity, and deployment-aware physical-admission gates over the result. The physical gate SHALL use an injected `ContextPhysicalAdmissionVerifier` backed by the resolved Change 1 preparation contract; legacy Harness token estimates MUST NOT authorize dispatch.

#### Scenario: Estimated count fits but prepared count does not
- **WHEN** the transformed envelope's legacy estimate is within budget but the resolved deployment preparer rejects the materialized request
- **THEN** aggregate VERIFY fails and no provider call or verified result event is authorized

#### Scenario: Every gate passes
- **WHEN** all versioned deterministic gates pass against the same immutable result snapshot and physical profile
- **THEN** Harness may atomically promote the result snapshot and record the aggregate verdict before provider dispatch

### Requirement: Summary calls are bounded and non-recursive
Summary generation SHALL consume the policy's summary-call, LLM-call, token, cost, and turn budgets. A rejected summary MAY trigger only the bounded Harness replan behavior. A summary worker MUST NOT recursively request another summary or invoke provider fallback outside Harness control.

#### Scenario: Summary budget is zero
- **WHEN** non-generative actions cannot fit context and `max_summary_calls` is zero
- **THEN** execution returns `NO_ALLOWED_COMPACTION` or another configured non-verified outcome without calling the summary worker

#### Scenario: First summary is rejected
- **WHEN** the first candidate fails a deterministic gate and the summary-call budget is exhausted
- **THEN** no second summary call occurs and Harness applies its bounded fallback/replan/halt policy
