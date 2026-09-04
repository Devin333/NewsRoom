## ADDED Requirements

### Requirement: AgentLoop can submit a bounded multi-child delegation candidate

The parent `AgentLoop` SHALL parse a versioned `delegate_batch` action whose child proposals contain logical objectives, capability hints, input refs, output roles, dependency refs, and an action correlation id. The action MUST declare no more than the policy's `max_tasks_per_group`; a parallelism hint is advisory and MUST NOT widen policy. AgentLoop MUST pass the candidate to a production Harness-owned orchestration port and MUST NOT create threads, choose concrete worker implementations, grant tools, mutate workflow state, or decide result quality itself.

#### Scenario: Parent submits independent delegations

- **WHEN** the model returns a valid `delegate_batch` action with two policy-compatible independent child proposals
- **THEN** AgentLoop MUST submit one candidate with a correlation id to Harness
- **AND** it MUST wait for the Harness join outcome rather than invoking either child directly

#### Scenario: Parent submits an invalid delegation

- **WHEN** the model returns a child proposal with a callable, concrete worker reference, unauthorized tool, hidden context, or control field
- **THEN** AgentLoop MUST record a typed candidate rejection or retry diagnostic
- **AND** it MUST not start any child or alter the parent workflow

#### Scenario: Parent requests excessive fan-out

- **WHEN** the model proposes more child tasks or a higher parallelism hint than the AgentSpec/stage policy permits
- **THEN** AgentLoop MUST pass the untrusted candidate to Harness validation or return the typed rejection
- **AND** it MUST not silently bypass the policy or create an unbounded loop

### Requirement: Generic AgentLoop orchestration is production-composed

The production AgentLoop composition SHALL resolve a real `AgentOrchestrationPort`, parent observation policy, feature flag, and availability diagnostics for `delegate_batch`. Missing orchestration binding MUST produce a stable unavailable/deferred result and MUST NOT install an ad hoc child executor. The feature flag MUST be independently observable and MUST preserve the legacy single-child path when disabled.

#### Scenario: Generic multi-child delegation is enabled

- **WHEN** a production AgentLoop has the orchestration feature enabled and all required bindings are available
- **THEN** a valid `delegate_batch` MUST be submitted to Harness and its group outcome MUST be returned as one parent observation
- **AND** no interface entrypoint may bypass the orchestration port

#### Scenario: Generic multi-child delegation is unavailable

- **WHEN** the feature is requested but the orchestration port, policy, or required runtime binding is unavailable
- **THEN** AgentLoop MUST return the stable unavailable/deferred diagnostic
- **AND** it MUST not silently execute children serially unless the pinned policy explicitly selects `serial_fallback`

### Requirement: AgentLoop receives one security-projected joined observation

After Harness completes or fails a delegation group, AgentLoop SHALL receive one observation containing the group status, wave summaries, stable child task summaries, result refs/checksums, aggregate refs when valid, gate diagnostics, and retry/recovery information. The observation MUST obey `ParentObservationLimits` from the parent AgentSpec/stage policy: maximum task summaries, summary bytes, diagnostics, refs, and total observation bytes. Over-limit content MUST be represented only by checksum-bound artifact refs. The observation MUST exclude hidden prompts, sibling private transcripts, secrets, and unapproved raw tool payloads.

#### Scenario: Joined child results are successful

- **WHEN** all required child results pass their deterministic gates and Harness aggregation succeeds
- **THEN** AgentLoop MUST append one joined observation to the parent conversation/event stream
- **AND** the next parent model turn MUST be able to reference the aggregate and child identities without receiving private child context

#### Scenario: Multi-child delegation has a controlled failure

- **WHEN** Harness returns partial failure, cancellation, indeterminate outcome, or bounded replan state
- **THEN** AgentLoop MUST expose the typed group outcome as one observation
- **AND** it MUST not convert the outcome into a successful final answer or infer a quality/publication decision

#### Scenario: AgentLoop retry budget is exhausted

- **WHEN** parent loop retry/turn budget is exhausted after a group outcome
- **THEN** AgentLoop MUST return its existing bounded terminal result
- **AND** it MUST not resubmit the same group or ask a child to bypass Harness gates

### Requirement: Legacy single-child delegation remains compatible

The existing single-child `delegate` action SHALL be converted by a compatibility adapter into a one-task group/wave with the same parent identity, policy, tool allowlist, memory boundary, budget, transcript, and result gates. A legacy concrete child reference MUST resolve through `legacy reference -> policy-pinned capability -> unique binding`; missing, ambiguous, or policy-less mappings MUST return stable typed diagnostics. Existing AgentRunner callers MUST continue to receive the current single-agent result shape unless they opt into the group result projection.

#### Scenario: Existing delegate action succeeds

- **WHEN** a legacy `delegate` action names one policy-compatible logical capability and the child returns a verified result
- **THEN** the adapter MUST execute it through the same Harness orchestration and receipt path
- **AND** AgentLoop MUST return a backward-compatible feedback/result projection

#### Scenario: Existing delegate action has no child executor

- **WHEN** a legacy caller has no configured Harness orchestration port
- **THEN** AgentLoop MUST preserve its typed deferred/unavailable diagnostic
- **AND** it MUST not instantiate an unbounded ad hoc child runtime

### Requirement: Planner tool observations are Harness-authorized

AgentLoop MAY request a planning observation through a Harness-controlled `ToolExecutor` only when the pinned AgentSpec/stage policy explicitly allows the read-only tool. The planning call MUST have its own receipt, planning budget, correlation id, and result checksum, and MUST be completed before the candidate is validated. The causal sequence MUST be `PlanningObservationRequest -> PlanningObservationReceipt -> PlanCandidate(source_observation_refs) -> candidate validation`; the receipt MUST first bind `run_id`, `stage_id`, `planner_turn_id`, and `policy_checksum`, and MUST NOT require a not-yet-created candidate checksum. Each planner turn MUST obey `max_planning_tool_calls` and `planning_timeout`. Planning tools MUST NOT grant authorization, mutate workflow routing, publish artifacts, or promote memory.

#### Scenario: Planner uses an allowed read-only tool

- **WHEN** the model requests a policy-allowlisted read-only retrieval tool during planning
- **THEN** Harness MUST execute and persist the tool receipt before candidate validation
- **AND** the receipt MAY be included as an input reference without becoming a quality verdict

#### Scenario: Planner requests a side-effect tool

- **WHEN** the model requests a tool that writes external state, publishes artifacts, changes policy, or promotes memory
- **THEN** Harness MUST deny the call before execution
- **AND** AgentLoop MUST receive a typed tool authorization diagnostic

#### Scenario: Planner tool receipt is not verifiable

- **WHEN** a planning observation has a missing, corrupt, stale, or cross-run receipt
- **THEN** candidate validation MUST fail closed
- **AND** AgentLoop MUST not dispatch child tasks based on that observation
