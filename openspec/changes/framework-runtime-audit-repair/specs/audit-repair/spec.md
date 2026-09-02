## ADDED Requirements

### Requirement: Started activities have durable terminal outcomes
The Harness SHALL persist a typed terminal outcome for every physical Graph activity that has started, including failure, timeout, cancellation, and termination uncertainty, and SHALL not redispatch an activity while termination is unconfirmed.

#### Scenario: Timeout produces an indeterminate outcome
- **WHEN** a started worker does not return within its timeout and cancellation grace period
- **THEN** the Harness records `TIMED_OUT` or `INDETERMINATE` evidence with the exact activity and attempt identity, and does not raise a missing-worker-evidence error instead of committing the result

#### Scenario: Unconfirmed termination is not redispatched
- **WHEN** recovery sees a prior activity outcome with `termination_confirmed=false`
- **THEN** recovery leaves the activity non-runnable until termination is verified or an explicit repair action is recorded

### Requirement: TaskPlan replacement and retry rules are authoritative
The Harness SHALL apply replacement relationships, retryable reason codes, and gate registration checks consistently in live execution, durable projection, recovery, and replay.

#### Scenario: Replacement supersedes a failed task
- **WHEN** a valid `ADD_REPLACEMENT_TASK` patch targets an exhausted failed task and supplies the required output role
- **THEN** the new plan records the target as replaced, downstream dependencies are rewired or the patch is rejected, and a successful replacement can reach aggregation and verification without `task_plan_task_blocked`

#### Scenario: Non-retryable gate failure is not retried
- **WHEN** a task returns `error_code=task_gate_failed` and that code is absent from `retryable_reason_codes`
- **THEN** the Harness does not emit `TASK_RETRY_SCHEDULED` and records a bounded failure with a stable reason code

#### Scenario: Missing gate fails before worker execution
- **WHEN** a task requires a gate reference that is allowed by policy but absent from the actual gate registry
- **THEN** PLAN validation returns a typed gate-unavailable error before any worker activity is dispatched

### Requirement: Authorization comes from deterministic Harness inputs
The Harness SHALL treat policy, approval records, and operator-owned capability classification as authoritative; worker candidates and remote tool metadata SHALL never grant approval, promotion, publication, or memory-write authority.

#### Scenario: Per-tool approval policy is enforced
- **WHEN** `ToolPolicy.require_approval_for` contains a tool whose definition declares `read_only`
- **THEN** the executor returns `APPROVAL_REQUIRED` and does not invoke the tool

#### Scenario: Candidate approval metadata is rejected
- **WHEN** a high-risk skill candidate supplies an `approval_ref` only in its own metadata
- **THEN** the promotion gate ignores or rejects that value and requires a resolver-backed approval record bound to the candidate and scope

#### Scenario: Memory promotion cannot bypass policy
- **WHEN** a caller attempts to promote a record to a scope or kind disallowed by `MemoryPolicy`
- **THEN** the mutation is rejected before the store is changed, regardless of the record's prior scope

### Requirement: Redaction preserves non-secret data integrity
Shared redaction SHALL identify real secret values without modifying ordinary domain text or replacing typed numeric configuration fields with string placeholders.

#### Scenario: Domain identifiers remain unchanged
- **WHEN** a tool, memory record, or transcript contains text such as `task-plan-abc` or `risk-assessment`
- **THEN** redaction returns the text unchanged and does not reject the surrounding record as secret content

#### Scenario: Typed token limits remain numeric
- **WHEN** an `LLMRequest` contains `max_tokens=256` and sensitive metadata such as an API key
- **THEN** the API key is redacted while `max_tokens` remains the integer `256` in the redacted request and persisted manifest
