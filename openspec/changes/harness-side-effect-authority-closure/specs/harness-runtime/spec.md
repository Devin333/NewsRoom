## MODIFIED Requirements

### Requirement: Harness Control Plane Authority
The Harness runtime SHALL be the only workflow and side-effect decision maker for Harness-managed runs. LLM workers, AgentLoop workers, tool workers, subagents, skill workers, RAG workers, interface services, and business steps MUST NOT decide workflow routing, quality verdicts, memory writes, tool authorization, approval state, artifact publication, active release, or skill promotion. Worker-provided scores, verdict-shaped values, route suggestions, and side-effect observations are candidate data only and MUST NOT be consumed as Harness decisions. Effectful store and publisher ports MUST be bound to exact Harness side-effect handlers rather than exposed to candidate workers. Controller-originated terminal effects MUST use an explicit terminal policy and identity-bound intent rather than masquerading as worker output or a synthetic workflow step.

#### Scenario: Worker output cannot route a run
- **WHEN** a worker result contains a suggested next route or quality verdict
- **THEN** Harness MUST treat that value as candidate data only
- **AND** Harness MUST choose the next route from workflow spec, current state, policy, budgets, and deterministic gate results

#### Scenario: Worker self-evaluation is observational
- **WHEN** an LLM or subagent returns a self-evaluation observation
- **THEN** Harness MUST NOT convert that observation into `HarnessQualityVerdict`
- **AND** the observation MUST NOT select retry, replan, repair, halt, completion, memory write, approval, publication, active release, or promotion

#### Scenario: Worker forges a side-effect decision
- **WHEN** a worker-compatible result contains a direct, alternate, or nested tool authorization, memory commit, publication, active-release, or promotion decision
- **THEN** Harness MUST reject it before deterministic scheduling can consume it
- **AND** no registered side-effect handler may be called

#### Scenario: Declared side effect uses a separate handler
- **WHEN** a workflow step declares an exact side-effect handler and its candidate passes VERIFY and required approval
- **THEN** Harness MUST create the authority decision from recorded deterministic evidence
- **AND** only the separately registered handler may commit the effect after that decision is durable

#### Scenario: Controller publishes terminal diagnostics
- **WHEN** every workflow step outcome is durable and the run declares a controller-terminal trace/transcript handler
- **THEN** Harness MUST create an origin- and scope-bound terminal intent from the recorded state and completion input
- **AND** the handler outcome MUST be durable before `COMPLETE_RUN` may be committed

#### Scenario: Terminal policy is invalid at preflight
- **WHEN** a run declares an unknown, duplicate, kind-mismatched, or unsupported-version `HarnessTerminalSideEffectPolicy`
- **THEN** Harness MUST fail closed before `RUN_CREATED` or any worker/handler call
- **AND** it MUST NOT infer a handler or approval default from the legacy `publish_requires_verify` boolean

#### Scenario: Legacy run has no terminal side-effect policy
- **WHEN** offline replay reads a historically completed run whose workflow predates `HarnessTerminalSideEffectPolicy`
- **THEN** replay MUST retain the recorded historical meaning and MUST NOT invoke a terminal handler
- **AND** live recovery that would require an unrecorded terminal effect MUST fail closed with `terminal_side_effect_policy_missing`

#### Scenario: Terminal artifact uses a bounded history cutoff
- **WHEN** the controller-terminal handler writes trace/transcript before `COMPLETE_RUN`
- **THEN** the artifact MUST record the last committed history/cutoff reference it contains
- **AND** replay and normal trace reads MUST use the durable event history to expose the later terminal outcome and `COMPLETE_RUN` transition rather than requiring the artifact to contain a self-referential final checksum

### Requirement: Trace Checkpoint Replay
Harness SHALL record phase transitions, worker calls, gate decisions, budgets, handoffs, RAG refs, memory write intents, side-effect intents, authorization decisions, quarantine dispositions, commit outcomes, and artifact publication decisions to a durable transcript or event log that can support checkpointing and replay. Gate and side-effect evidence MUST include origin, identity and subject scope references, exact versioned handler/gate/terminal-policy identities, deterministic input references, result references, each gate pass/fail outcome, stable reason codes, aggregate verdict, matching approval or pinned `not_required` policy evidence, idempotency identity, disposition, persisted effect-attempt counter/limit, durably resolvable outcome reference, and the resulting scheduler decision before the next state or publication is accepted.

#### Scenario: Replay reads deterministic decisions
- **WHEN** a completed Harness run is replayed from its transcript and checkpoints
- **THEN** the replay reader MUST expose the recorded plan, execution, verify, gate, budget, handoff, side-effect, and artifact decision events without calling an LLM

#### Scenario: Recovery resumes after committed VERIFY
- **WHEN** VERIFY evidence and its transition were durably committed before a process crash
- **THEN** recovery MUST use the recorded gate evidence and pinned gate version as scheduler input
- **AND** recovery MUST NOT replace the recorded verdict with current defaults or worker self-evaluation

#### Scenario: Recorded gate evidence is incomplete
- **WHEN** recovery cannot resolve the pinned gate version or verify the recorded gate evidence checksum
- **THEN** recovery MUST fail closed with a typed history diagnostic
- **AND** it MUST NOT guess, reclassify the history as passed, or invoke an LLM

#### Scenario: Recovery observes authorization without an outcome
- **WHEN** recovery finds one matching committed side-effect authority decision and no durably resolvable matching outcome
- **THEN** it MUST verify and reuse the original command ordinal, causation, origin, scope, intent, worker-result or terminal-state input, gate, approval, budget, handler, and decision identities rather than recording a replacement decision
- **AND** recovery MAY call the idempotent handler with the original effect identity and scope only while the persisted effect-attempt budget remains

#### Scenario: Offline replay observes side-effect history
- **WHEN** offline replay observes a side-effect authority decision with or without a matching outcome
- **THEN** it MUST verify and expose the recorded origin, scope, intent, worker-result or terminal-state input, gate, approval, budget, handler, decision, disposition, idempotency, and outcome references
- **AND** it MUST NOT call a worker, handler, store, publisher, Tool adapter, memory port, or release registry
