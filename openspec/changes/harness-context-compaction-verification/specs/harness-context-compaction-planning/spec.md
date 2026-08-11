## ADDED Requirements

### Requirement: Compaction policy and bounds are immutable
Harness SHALL resolve an immutable, versioned `ContextCompactionPolicy` from trusted workflow and global policy. It MUST define enabled actions, action order, maximum actions, maximum summary calls, maximum replans, protected kinds/reasons, recent-tail rules, evidence selection rules, target input budget, and failure policy. A child, retry, worker, or summary candidate MUST NOT expand these bounds.

#### Scenario: Unknown action is configured
- **WHEN** policy names an action with no registered typed implementation
- **THEN** composition validation fails before the Harness run starts

#### Scenario: Child policy requests more actions
- **WHEN** a child or retry requests bounds larger than its parent-approved policy
- **THEN** the effective policy retains the narrower parent limits

### Requirement: Plans are deterministic typed proposals
For a fixed source snapshot, task/query binding, physical-admission evidence, and policy revision, the planner SHALL produce an immutable `ContextCompactionPlan` with a stable digest id, ordered typed actions, protected group ids, target input tokens, and remaining action/summary/replan budgets. The plan MUST NOT contain raw prompt or evidence bodies.

#### Scenario: Same inputs are replanned
- **WHEN** the same immutable inputs are given to the planner twice
- **THEN** the ordered non-generative actions and plan id are identical

#### Scenario: Source snapshot changes
- **WHEN** any group identity, protection state, task/query binding, or physical profile revision changes
- **THEN** the plan identity changes and an older plan cannot be applied to the new snapshot

### Requirement: Only allowlisted group-safe actions execute
Production plans SHALL use registered typed actions with explicit preconditions and postconditions. Supported initial actions SHALL include `DROP_RECONSTRUCTABLE_GROUP`, `REPLACE_WITH_REFERENCE`, `REDUCE_AUTHORIZED_TOOL_SET`, `SELECT_EVIDENCE_SPANS`, `COMPACT_OLD_CONVERSATION`, and `SUMMARIZE_GROUPS`. Arbitrary character truncation, FIFO message popping, untyped callbacks, and fabricated artifact refs MUST NOT execute as production actions.

#### Scenario: Reversible action is available
- **WHEN** a reconstructable or duplicate group can satisfy the target without information loss
- **THEN** the planner selects that action before a lossy summary action

#### Scenario: Action targets part of a transaction
- **WHEN** an action references only one member of a tool transaction or protected group
- **THEN** action validation rejects the plan before execution

### Requirement: Evidence selection is extractive and query bound
`SELECT_EVIDENCE_SPANS` SHALL operate on explicit evidence/span refs and the current task/query binding. It MUST retain required citations, lineage, conflict markers, and a loss report of omitted non-required spans. It MUST NOT invent a source ref or use semantic similarity alone as proof of coverage.

#### Scenario: Irrelevant spans are removable
- **WHEN** non-required spans are outside the task/query binding and policy permits extractive selection
- **THEN** the result retains selected span refs and records omitted span ids in the loss report

#### Scenario: Selection would remove required citation
- **WHEN** the proposed selection excludes a required evidence span or source ref
- **THEN** the evidence action is rejected and cannot contribute to a verified result

### Requirement: Tool-set reduction follows existing authorization
`REDUCE_AUTHORIZED_TOOL_SET` MAY remove provider tool schemas only from the currently authorized set and only when deterministic workflow policy proves those tools are unavailable for the current step. Context compaction MUST NOT grant a tool, revoke an authorization needed by a pending transaction, or alter tool arguments/results.

#### Scenario: Unreachable authorized tool is removed
- **WHEN** workflow routing proves a tool cannot be called in the current step and no pending transaction references it
- **THEN** the tool schema may be omitted with the authorization and policy refs recorded

#### Scenario: Planner attempts to add a tool
- **WHEN** a plan contains a tool not present in the trusted authorized tool set
- **THEN** plan validation fails and no result snapshot is created

### Requirement: Execution is bounded and produces typed outcomes
Plan execution SHALL enforce action, summary-call, replan, token, cost, and turn bounds at every transition. It SHALL terminate with one of `VERIFIED`, `NO_COMPACTION_REQUIRED`, `PROTECTED_CONTEXT_EXCEEDS_WINDOW`, `NO_ALLOWED_COMPACTION`, `ACTION_BUDGET_EXHAUSTED`, `SUMMARY_REJECTED`, or `POST_COMPACTION_VERIFY_FAILED`. It MUST NOT loop until context happens to fit.

#### Scenario: Action budget is exhausted
- **WHEN** the next plan action would exceed `max_actions`
- **THEN** execution halts with `ACTION_BUDGET_EXHAUSTED` and no provider dispatch authorization

#### Scenario: Compaction still does not fit
- **WHEN** all allowed actions complete but the physical admission verifier still rejects the result
- **THEN** execution returns a typed non-verified outcome under existing Harness fallback/replan/halt policy
