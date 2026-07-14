## ADDED Requirements

### Requirement: Replay modes have explicit side-effect contracts
The system SHALL provide distinct `REBUILD_STATE`, `VERIFY_HISTORY`, and authorized `REDELIVER` modes and SHALL NOT route state reconstruction or history verification through live side-effect subscribers.

#### Scenario: State is rebuilt from history
- **WHEN** an operator or recovery path runs `REBUILD_STATE`
- **THEN** events are applied only to registered pure reducers in stream-sequence order
- **AND** the source stream is not modified

#### Scenario: Historical decisions are verified
- **WHEN** a workflow or Harness history runs in `VERIFY_HISTORY`
- **THEN** deterministic commands are compared with the recorded history
- **AND** any mismatch produces a typed nondeterminism report

#### Scenario: Operator requests redelivery
- **WHEN** an authorized operator runs `REDELIVER`
- **THEN** selected event-consumer pairs are scheduled through the normal delivery ledger
- **AND** the action is not represented as state reconstruction

### Requirement: Replay never re-executes unrecorded nondeterministic work
The system SHALL model LLM, Tool, MCP, HTTP, retrieval, memory write, publication, email, real clock, and random operations as activities whose accepted inputs and outcomes are recorded and reused during replay.

#### Scenario: Workflow history contains an LLM activity
- **WHEN** replay reaches a completed LLM activity
- **THEN** it reads the recorded input/output references and status
- **AND** does not call the live LLM provider

#### Scenario: Required activity result is missing
- **WHEN** replay reaches a nondeterministic activity with no complete recorded result
- **THEN** replay halts with a typed incomplete-history diagnostic
- **AND** does not attempt the live operation as a fallback

### Requirement: Replay validates order, schema, and integrity
The system SHALL read a stream by authoritative sequence and SHALL validate event checksum, envelope schema, data schema, and upcast compatibility before applying each event.

#### Scenario: Replay input iterable is unsorted
- **WHEN** replay receives records outside stream-sequence order
- **THEN** the replay reader either orders them from the durable store or rejects the input
- **AND** never uses occurrence time as authoritative order

#### Scenario: Stored event checksum is invalid
- **WHEN** replay detects an event whose canonical checksum does not match
- **THEN** replay stops before applying that event
- **AND** records a corruption diagnostic without altering history

#### Scenario: Event requires an upcaster
- **WHEN** replay reads a supported historical data schema
- **THEN** it applies the registered pure upcast chain before the reducer
- **AND** records the applied schema versions in the replay report

### Requirement: Replay resumes from a verified checkpoint
The system SHALL support a checksum-verified checkpoint that identifies the stream, last applied stream sequence, runtime/workflow version, and reducer state required to resume deterministically.

#### Scenario: Valid checkpoint is restored
- **WHEN** a replay starts from a valid checkpoint at sequence N
- **THEN** it restores the checkpoint state and reads events after sequence N
- **AND** produces the same final state as replay from sequence 1

#### Scenario: Checkpoint and stream do not match
- **WHEN** the checkpoint stream, sequence, version, or checksum is incompatible with the requested replay
- **THEN** replay rejects the checkpoint before applying later events

### Requirement: Replay pins deterministic handler versions
The system SHALL record and resolve workflow, reducer, policy, schema, and activity contract versions needed to interpret history and SHALL fail closed when no compatible version or migration exists.

#### Scenario: Historical workflow version remains available
- **WHEN** replay selects a stored workflow version with compatible handlers
- **THEN** generated commands are compared against history using that version

#### Scenario: Code change reorders deterministic commands
- **WHEN** current workflow code emits a different command at a recorded sequence
- **THEN** `VERIFY_HISTORY` reports nondeterminism
- **AND** does not overwrite the historical command or continue as success

### Requirement: Replay reports are durable and source history is immutable
The system SHALL transactionally capture a finite source high watermark when replay starts and SHALL write replay status, that input watermark, checkpoint, versions, upcasts, mismatches, quarantine references, and result checksum to a separate replay report or audit stream without appending synthetic events to the source history. This change SHALL NOT provide an unbounded follow mode.

#### Scenario: Live append continues during replay
- **WHEN** new events commit after a replay captures its source high watermark
- **THEN** that replay processes only events at or below the captured watermark
- **AND** it completes with the same result it would have produced from an equivalent static stream prefix

#### Scenario: Replay completes successfully
- **WHEN** replay reaches the source high watermark without mismatch
- **THEN** the report records success, applied sequence range, versions, and final state checksum

#### Scenario: Replay halts on mismatch
- **WHEN** replay finds corruption, incompatible schema, missing activity output, or command nondeterminism
- **THEN** the report records the exact sequence and typed reason
- **AND** the original event stream remains byte-for-byte unchanged

### Requirement: Redelivery is authorized and idempotency-aware
The system SHALL require event range, target consumer, authorization, tenant scope, operator reason, and idempotency readiness before redelivery.

#### Scenario: Redelivery request lacks a target consumer
- **WHEN** an operator requests generic replay-to-bus behavior without a consumer selection
- **THEN** the runtime rejects the request

#### Scenario: Authorized redelivery succeeds
- **WHEN** a scoped request passes authorization and the consumer idempotency contract is ready
- **THEN** the runtime creates audited delivery work using the original event identity
- **AND** preserves prior delivery and dead-letter history

### Requirement: Harness transitions use the durable replay source
The system SHALL persist every recoverable Harness state transition through the durable event runtime before advancing the recoverable state projection. This includes phase entry and exit for `PLAN`, `EXECUTE`, and `VERIFY`; controlled `replan`, `retry`, `route_to_repair`, `wait_for_approval`, approval resume or cancel, budget exhaustion, halt, failure, and successful terminal outcomes.

#### Scenario: Process crashes after transition commit
- **WHEN** a Harness transition event commits but the process dies before updating its in-memory projection
- **THEN** recovery reapplies the committed transition from the durable stream
- **AND** does not ask an LLM or worker to decide that transition again

#### Scenario: Harness event store is unavailable
- **WHEN** a required phase transition cannot be durably appended
- **THEN** Harness fails closed before the state transition or external activity
- **AND** does not downgrade to the in-memory event port

#### Scenario: VERIFY chooses a controlled recovery outcome
- **WHEN** a deterministic gate selects retry, replan, route-to-repair, or wait-for-approval
- **THEN** the selected outcome and its budget and gate evidence commit before the next state is entered
- **AND** recovery does not ask a worker or LLM to choose that transition again

### Requirement: Workflow checkpoints use stream sequence semantics
The system SHALL store the last durable event stream sequence in new workflow checkpoints and SHALL keep legacy JSONL line offsets as explicitly named import metadata only.

#### Scenario: New workflow checkpoint is created
- **WHEN** workflow execution writes a checkpoint
- **THEN** the checkpoint records the last committed stream sequence and event id
- **AND** resume consumes events after that sequence

#### Scenario: Legacy checkpoint is imported
- **WHEN** a checkpoint contains a 0-based legacy event offset
- **THEN** the migration adapter maps it through the recorded legacy import mapping
- **AND** a fixture verifies the boundary event is neither skipped nor replayed twice
