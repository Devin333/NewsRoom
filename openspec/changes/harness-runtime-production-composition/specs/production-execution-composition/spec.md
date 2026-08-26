## ADDED Requirements

### Requirement: Production runtime composition is singular

Each production process SHALL construct one `RuntimeExecutionComposition` from the same versioned manifest and SHALL verify the same `composition_id`, policy fingerprint, provider/config identity, event schema, and durable-store contract. The composition SHALL inject its execution registry, tool executor factory, durable execution/side-effect receipt ports, child lease/receipt ports, child supervisor, canonical event/outbox publisher, projection checkpoint reader, operator authorizer, and operator service into every supported API, worker, CLI, Harness, and Research entrypoint. Processes SHALL NOT be required to share in-memory provider objects.

#### Scenario: API and worker share execution policy

- **WHEN** an API run and a worker continuation execute activities for the same Graph run
- **THEN** both entrypoints SHALL resolve the same manifest version, policy fingerprint, and provider/config identity
- **AND** neither entrypoint SHALL create an unregistered local execution provider or event authority

#### Scenario: Composition dependency is unavailable

- **WHEN** a required production provider, durable event store, or operator read port cannot be resolved
- **THEN** startup or capability admission SHALL return a typed blocked result
- **AND** the entrypoint SHALL NOT silently construct an in-memory or host-process fallback

#### Scenario: Composition manifest drifts

- **WHEN** an API and worker resolve different manifest checksums, policy fingerprints, provider identities, or event schema versions for one deployment
- **THEN** health/admission SHALL reject the mismatched process
- **AND** it SHALL not execute a cross-process run until the composition identity is reconciled

### Requirement: External activities require execution admission

Every `sandboxed` or `external_process` tool, parser, compiler, MCP sidecar, and child process SHALL enter Harness-controlled execution admission with an exact Graph identity, activity profile, capability set, argv, working root, environment policy, timeout, and cancellation contract.

#### Scenario: Sandboxed activity is admitted

- **WHEN** a Graph-bound activity requests capabilities supported by the registered provider
- **THEN** Harness SHALL create an `ExecutionRequest` and execute it through the registered environment
- **AND** the resulting `ExecutionReceipt` SHALL include provider, profile, capability, termination, and checksum evidence

#### Scenario: Provider capability is missing

- **WHEN** an activity requests a network allowlist, child executable allowlist, secret handle, or other capability not supported by the provider
- **THEN** admission SHALL fail closed with a stable capability denial
- **AND** the activity SHALL NOT run in the host process with reduced restrictions

#### Scenario: Child launch is admitted

- **WHEN** a supervisor requests a production child process
- **THEN** the child launch adapter SHALL consume an admitted `ExecutionRequest` from the registered environment
- **AND** the resulting `ExecutionReceipt` SHALL bind to the child lease and attempt before the worker can be accepted

### Requirement: Direct subprocess callers are bounded

Production code SHALL NOT invoke `subprocess.run`, `Popen`, or equivalent process creation for a Harness-managed external activity outside an approved execution adapter. The adapter SHALL map command lifetime, cwd, mounts, environment, timeout, cancellation, and output receipts to the execution environment contract. An approved caller inventory SHALL cover production runtime packages only; every exemption SHALL name an owner, reason, non-Harness-managed proof, expiry/review date, and test or static check.

#### Scenario: Research parser runs through the adapter

- **WHEN** a Research parser or PDF compiler requests an external executable
- **THEN** the request SHALL be represented as an admitted execution activity
- **AND** the business service SHALL receive a typed observation/receipt rather than owning an unbounded process handle

#### Scenario: Unapproved subprocess caller is detected

- **WHEN** caller inventory finds a production process creation site without an approved adapter annotation and test
- **THEN** the production qualification gate SHALL fail
- **AND** the caller SHALL be migrated or explicitly excluded with a documented security rationale

### Requirement: Trusted in-process work is explicit

Only deterministic, side-effect-free functions explicitly registered as `trusted_in_process` MAY execute without an external provider. A caller flag, LLM output, or missing provider SHALL NOT change an activity from `sandboxed`/`external_process` to trusted.

#### Scenario: Pure function is trusted

- **WHEN** a registered pure function executes with no external file, network, environment, or child-process access
- **THEN** the composition MAY execute it in process
- **AND** the profile and registration identity SHALL be recorded in runtime evidence

#### Scenario: Caller requests unsafe downgrade

- **WHEN** a caller requests in-process execution for an activity declared sandboxed
- **THEN** Harness SHALL reject the downgrade
- **AND** no worker or tool code SHALL receive authorization to bypass the environment
