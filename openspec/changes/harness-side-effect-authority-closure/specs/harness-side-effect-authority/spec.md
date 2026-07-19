## ADDED Requirements

### Requirement: Worker side-effect output is candidate-only
Harness-managed workers SHALL return only candidate data, at most one typed side-effect intent per step result, candidate refs, diagnostics, metrics, and explicit observations. A versioned canonical reserved-path matrix MUST define the exact untyped output, diagnostics, metrics, and nested aliases that represent routing, verdict, tool authorization, approval, memory commit, artifact publication, active release, or skill promotion decisions; matches MUST be rejected at every supported structured result ingress and MUST NOT reach a commit handler. Candidate artifact refs MUST be type/reference validated but are not interpreted as structured authorization payloads. Typed intent envelope fields MUST be validated exactly, while their schema-validated domain payload is opaque candidate data and cannot grant authorization. One intent MAY contain multiple members of one atomic group; different handlers or effect kinds require separate workflow steps.

#### Scenario: Forged decision aliases are rejected
- **WHEN** a worker-compatible result places an authorization, memory-write, publication, active-release, or promotion decision alias in output, diagnostics, metrics, or a nested untyped mapping
- **THEN** Harness MUST reject the result with a stable reason code and sorted field paths
- **AND** tool, memory, published artifact, latest index, release, and active-skill write counts MUST remain zero

#### Scenario: Explicit observation remains non-executable
- **WHEN** a worker returns an explicitly named authorization, quality, publication, or promotion observation
- **THEN** Harness MAY retain it as candidate evidence
- **AND** the observation MUST NOT create an authority decision, approval, memory commit, published artifact, latest-index entry, release, or active skill

#### Scenario: Typed payload contains a domain field resembling a decision
- **WHEN** a registered intent schema permits a domain field whose name also appears in the untyped reserved-path matrix
- **THEN** Harness MUST treat that field as opaque candidate payload rather than an authority input
- **AND** only the typed intent identity, workflow policy, deterministic gates, budget, and resolved approval evidence may authorize the handler

#### Scenario: Worker-originated typed intent carries candidate data only
- **WHEN** a workflow declares an exact side-effect handler and its worker returns a valid typed intent
- **THEN** Harness MUST integrity-bind the intent to the run, step, attempt, worker result, effect kind, identity scope, subject scope, and idempotency identity
- **AND** the worker MUST NOT receive or invoke the bound commit handler or its concrete store

#### Scenario: Worker returns multiple side-effect intents
- **WHEN** one worker result contains multiple intents, handlers, or effect kinds for the same step/attempt
- **THEN** Harness MUST reject the ambiguous result before authorization
- **AND** one valid intent MAY contain multiple members only when they share one declared handler, effect kind, and atomic-group identity

#### Scenario: Worker returns multiple side-effect intents
- **WHEN** one worker result contains more than one intent, more than one handler identity, or conflicting effect kinds
- **THEN** Harness MUST reject the result before authorization or handler invocation
- **AND** the producer MUST use one atomic-group intent or separate workflow steps with independent attempt identities

### Requirement: Side-effect authorization is durable and post-VERIFY
Harness SHALL authorize a worker-originated declared side effect only after the candidate worker activity is durably recorded, every required deterministic VERIFY gate passes, the current attempt remains within budget, and any required approval is resolved from canonical evidence bound to the same run, step, attempt, effect id, candidate checksum, identity scope, subject scope, and decision version. Harness SHALL authorize a controller-terminal side effect only after every step outcome is durable and its versioned terminal policy, current state checksum, completion input, inherited aggregate gate evidence, current budget snapshot and effect-attempt allowance, identity scope, subject scope, handler identity, and approval evidence match. A no-approval terminal policy MUST provide a pinned `not_required` policy-evidence reference rather than an omitted approval field. The authority decision MUST be durably recorded before the commit handler is called.

#### Scenario: Gate failure cannot commit
- **WHEN** an effect intent is present and any required VERIFY gate fails
- **THEN** Harness MUST choose an allowed controlled failure outcome without calling the commit handler
- **AND** Tool effects, canonical memory, published artifact, latest index, release, and active-skill mutations MUST remain zero

#### Scenario: Approval is pending or cancelled
- **WHEN** an effect requires approval and no matching durable approval exists, or the approval is cancelled
- **THEN** Harness MUST NOT call the commit handler
- **AND** the candidate MAY be retained only in the isolated candidate or quarantine disposition

#### Scenario: Approval belongs to another effect identity
- **WHEN** approval evidence has a different run, step, attempt, effect id, candidate checksum, identity scope, subject scope, or decision version
- **THEN** Harness MUST reject it as stale or mismatched and MUST NOT call the commit handler
- **AND** the mismatched approval MUST NOT be copied into a new attempt or authority decision

#### Scenario: Handler scope differs from the authorized effect
- **WHEN** the resolved handler or outcome store is bound to a different tenant identity, actor, resource, or memory namespace scope
- **THEN** Harness MUST fail closed before committing or exposing the effect
- **AND** the mismatched scope MUST NOT be normalized into the current authorization

#### Scenario: Budget is exhausted before authorization
- **WHEN** the current turn, retry, replan, or worker-call budget is exhausted before an authority decision is committed
- **THEN** Harness MUST halt or fail according to the existing bounded policy
- **AND** no side effect or published/latest mutation may occur

#### Scenario: Authorized effect commits after its decision
- **WHEN** the declared handler, deterministic gates, current budget, and required approval all validate the same typed intent
- **THEN** Harness MUST commit an authorization containing their exact integrity references before invoking the handler
- **AND** the handler MUST receive only that recorded authorization and the matching candidate intent

#### Scenario: Controller-terminal effect is authorized
- **WHEN** every step outcome is durable and the current completion input matches an explicitly bound controller-terminal policy and handler
- **THEN** Harness MUST create the intent and authorization with `origin=controller_terminal`, inherited aggregate gate and budget refs, bounded effect-attempt state, matching approval or pinned `not_required` evidence, and no worker-result reference
- **AND** a worker MUST NOT be able to create, replace, or authorize that terminal intent

### Requirement: Candidate, prepared, quarantine, accepted, and latest visibility are isolated
Harness side-effect stores and conforming business adapters SHALL use the canonical `candidate`, `prepared`, `quarantine`, and `accepted` dispositions. `prepared` SHALL mean a post-VERIFY, checksum-verified hidden outcome that remains non-public. Only `accepted` data may appear in canonical/published readers or latest indexes. Failed, halted, blocked, cancelled, approval-waiting, superseded, or retry-exhausted data MUST remain candidate/prepared or transition to quarantine, while scoped diagnostic readers MUST be able to inspect the isolated record.

#### Scenario: Failed run follows an accepted run
- **WHEN** an accepted run for one identity is followed by a halted or quality-failed run for the same identity
- **THEN** the failed run MUST remain queryable by its scoped run or quarantine identity
- **AND** the published/latest reader MUST continue to return the accepted run

#### Scenario: No accepted run exists
- **WHEN** only failed, halted, blocked, cancelled, or approval-waiting records exist for an identity
- **THEN** the published/latest reader MUST return no accepted result
- **AND** the explicit quarantine reader MAY return the terminal diagnostics in scope

#### Scenario: Artifact candidate is rejected
- **WHEN** an artifact bundle intent is rejected by gate, approval, budget, or publication policy
- **THEN** its bytes and refs MUST remain absent from the canonical manifest and published artifact index
- **AND** any retained candidate or diagnostic MUST use an isolated reference that a normal artifact reader cannot resolve as published

#### Scenario: Prepared artifact group awaits terminal publication
- **WHEN** a post-VERIFY artifact handler durably prepares a complete hidden candidate group before terminal completion
- **THEN** its prepared outcome MAY be referenced by step state but MUST NOT create canonical manifest/index visibility
- **AND** only the matching controller-terminal handler MAY publish the whole group together with terminal diagnostics

#### Scenario: Prepared group is cancelled or expires
- **WHEN** a prepared group is cancelled, superseded by retry/replan, terminally rejected, or reaches its bounded retention expiry
- **THEN** its durable disposition MUST transition to quarantine before owned cleanup removes eligible hidden bytes
- **AND** cleanup MUST retain stable history/disposition refs and MUST NOT create canonical visibility

#### Scenario: Historical record has no disposition field
- **WHEN** a retained legacy record predates explicit disposition metadata
- **THEN** the reader MUST classify it fail-closed from its stored terminal status, quality result, and complete identity/checksum-consistent artifact evidence without rewriting the record or trusting legacy manifest status as acceptance
- **AND** missing, malformed, inconsistent, or non-passing acceptance evidence MUST NOT enter the accepted latest index

#### Scenario: Historical failed run already has a canonical manifest
- **WHEN** migration finds a legacy failed or non-passing run whose old publisher wrote canonical manifest entries
- **THEN** normal Research artifact resolution MUST classify and reject those refs as `legacy_quarantined` without deleting the stored bytes
- **AND** only an explicit scoped diagnostic reader MAY inspect them

### Requirement: Side-effect commit is idempotent and atomically visible
Each authorized side effect SHALL have a stable idempotency identity and a typed outcome that the handler/store durably persists and exposes through a scoped read-back before returning committed success. Harness MUST verify the matching outcome before `STEP_SUCCESS`, downstream routing, or terminal run success becomes durable, and the success transition MUST reference that outcome. Recovery MAY finish an authorized effect whose outcome is absent, but MUST NOT repeat an effect with a committed matching outcome. A grouped publication MUST become visible through one atomic canonical manifest/index commit or remain entirely unpublished.

#### Scenario: Outcome precedes successful visibility
- **WHEN** an authorized handler returns a successful effect outcome
- **THEN** Harness MUST read back and verify the durably stored outcome before committing step success, downstream routing, or run success
- **AND** failure to commit the outcome MUST prevent the successful state transition

#### Scenario: Terminal outcome precedes run success
- **WHEN** a controller-terminal trace/transcript handler returns a successful outcome
- **THEN** Harness MUST read back and verify the outcome and the single finalized manifest/index commit for all prepared and terminal artifact refs before committing `COMPLETE_RUN`
- **AND** an outcome-store or publication failure MUST leave the run non-succeeded with only durable history or scoped quarantine diagnostics available

#### Scenario: Crash after decision and before effect
- **WHEN** the authority decision is durable but no external effect or outcome was committed before a crash
- **THEN** recovery MAY invoke the handler with the recorded idempotency identity only while the persisted effect-attempt budget remains
- **AND** the resulting outcome MUST be bound to the original decision

#### Scenario: Crash after effect and before durable outcome reference
- **WHEN** a handler completed externally but its durable outcome was not read back and referenced by the success transition before a crash
- **THEN** recovery MUST reuse the same effect identity and the handler/store MUST return the existing result without duplicating the effect
- **AND** Harness MUST reference exactly one matching durable outcome in the resumed success transition

#### Scenario: Effect recovery budget is exhausted
- **WHEN** a worker-originated or controller-terminal effect has consumed its persisted retry allowance without a matching durable outcome
- **THEN** recovery MUST record `effect_retry_exhausted` and enter one stable non-success terminal state
- **AND** restart MUST NOT reset the counter, allocate a replacement effect id, or invoke the handler again

#### Scenario: Committed effect is replayed offline
- **WHEN** replay encounters a committed side-effect decision and outcome
- **THEN** replay MUST expose their intent, handler, gate, approval, decision, idempotency, disposition, and outcome references
- **AND** replay MUST NOT call a worker, handler, store, publisher, Tool adapter, memory port, or release registry

#### Scenario: Grouped artifact publication fails partway
- **WHEN** preparing, writing, or validating any main or terminal member of an authorized artifact group fails before the terminal visibility commit
- **THEN** the canonical manifest and published/latest index MUST have zero new entries from that group
- **AND** hidden candidates MAY be quarantined or removed by owned cleanup without becoming normal artifact refs
