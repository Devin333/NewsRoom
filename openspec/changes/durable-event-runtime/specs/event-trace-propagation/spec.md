## ADDED Requirements

### Requirement: New trace identifiers conform to OpenTelemetry and W3C
The system SHALL generate and validate standards-compatible immutable span context containing a 16-byte trace id, 8-byte span id, trace flags, trace state, and remote-context marker.

#### Scenario: Runtime creates a root span
- **WHEN** a new run has no valid incoming trace context
- **THEN** the runtime creates a nonzero 32-hex-character trace id and nonzero 16-hex-character span id

#### Scenario: Incoming trace context is malformed
- **WHEN** an inbound adapter receives an invalid or disallowed W3C trace context
- **THEN** it rejects or restarts the trace according to trust policy
- **AND** does not use the malformed value as authentication, tenant, or event identity

### Requirement: Cross-process boundaries inject and extract trace context
The system SHALL use a shared propagator to extract inbound and inject outbound W3C context at HTTP, MCP, Tool, worker, and message boundaries.

#### Scenario: Worker consumes a propagated message
- **WHEN** a worker receives a message containing valid trace context
- **THEN** the adapter extracts it and creates the consumer span with the appropriate remote relationship

#### Scenario: Tool request leaves the process
- **WHEN** ToolRuntime sends an outbound request
- **THEN** it injects the current trace context into the supported carrier
- **AND** leaves business run and workflow identifiers in their defined business fields

### Requirement: Trace and durable business identity remain independent
The system SHALL correlate durable events with trace context when available but SHALL NOT require sampled telemetry for event persistence, ordering, authorization, idempotency, or replay.

#### Scenario: Trace sampling drops a span
- **WHEN** telemetry policy does not export a span
- **THEN** required workflow and Harness events are still durably stored in full
- **AND** replay remains possible from the event stream

#### Scenario: Run resumes in a new trace
- **WHEN** recovery policy starts a new trace for a resumed run
- **THEN** the durable `run_id` and stream identity remain unchanged
- **AND** trace linkage is recorded without changing event identity

### Requirement: Resource and instrumentation ownership are explicit
The system SHALL identify the emitting service or process through OpenTelemetry Resource attributes and the library or component through InstrumentationScope rather than relying on arbitrary event metadata.

#### Scenario: Workflow runtime emits telemetry
- **WHEN** the workflow event bridge creates spans or span events
- **THEN** Resource identifies the NewsRoom service instance
- **AND** InstrumentationScope identifies the workflow/event library and version

### Requirement: Asynchronous causality supports span links
The system SHALL use span links for asynchronous queues, retries, fan-in, fan-out, batches, or other relationships that cannot be represented accurately by one parent span.

#### Scenario: Batch consumer handles events from multiple traces
- **WHEN** one processing span consumes a batch whose events have different span contexts
- **THEN** the processing span links the valid originating contexts
- **AND** does not invent one arbitrary parent for the batch

#### Scenario: Retry begins after producer span ended
- **WHEN** a later delivery attempt processes a previously published event
- **THEN** telemetry links or relates it to the event's producer context according to messaging conventions
- **AND** delivery attempt state remains outside the immutable event

### Requirement: Telemetry attributes are bounded and safe
The system SHALL emit only schema-defined low-cardinality telemetry attributes and SHALL exclude raw payloads, prompts, answers, evidence text, secrets, tenant or user values, and arbitrary metadata.

#### Scenario: Event contains confidential payload
- **WHEN** the runtime emits a span or span event for the event
- **THEN** telemetry includes only allowed identifiers, type, status, and bounded counts
- **AND** excludes the confidential payload

#### Scenario: External tracestate or baggage is oversized or disallowed
- **WHEN** inbound propagation exceeds configured limits or contains forbidden keys
- **THEN** the adapter drops or rejects the offending values according to policy
- **AND** records a bounded security diagnostic

### Requirement: Trace compatibility facade has a bounded migration
The system SHALL preserve existing `TraceContext.root()`, `child()`, serialization, and `trace_fields()` call sites during one migration release while generating standards-compatible context for new runs and preserving historical identifiers as legacy data.

#### Scenario: Existing component creates a child context
- **WHEN** an existing Agent, Tool, Memory, or Workflow caller uses the compatibility facade
- **THEN** the child preserves the trace and receives a valid new span id
- **AND** all supported business identifiers are propagated without a shared mutable recorder context

#### Scenario: Compatibility fields contain business identifiers and credential-like metadata
- **WHEN** the facade projects Agent, Tool, Memory, or Artifact context containing supported business identifiers and metadata keys that resemble security terms
- **THEN** `agent_id`, `tool_call_id`, `memory_operation_id`, and `artifact_id` are preserved according to the registered field contract
- **AND** schema-aware security policy redacts forbidden values without substring-based false positives or credential-key omissions
- **AND** later mutation of source metadata cannot change the accepted immutable trace or event context

#### Scenario: Historical non-W3C span id is read
- **WHEN** a legacy event contains a historical span id that cannot be emitted as W3C context
- **THEN** the reader preserves it as legacy correlation data
- **AND** does not rewrite history or inject the invalid value into an outbound carrier

### Requirement: OpenTelemetry integration is optional at framework import time
The system SHALL run correctly with a no-op telemetry implementation when the OpenTelemetry API or exporter is unavailable.

#### Scenario: Telemetry dependency is absent
- **WHEN** NewsRoom imports and executes framework events without OpenTelemetry installed or configured
- **THEN** event append, delivery, replay, and workflow behavior remain functional
- **AND** no telemetry import error escapes the optional adapter boundary
