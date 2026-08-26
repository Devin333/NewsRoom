## ADDED Requirements

### Requirement: Process-local execution composition has a stable identity

Each supported production process SHALL resolve a process-local `RuntimeExecutionComposition` from the same execution configuration, policy, profile catalog, and provider identity inputs. The composition SHALL expose an immutable versioned identity and deterministic composition, policy, and provider fingerprints, an `ExecutionEnvironmentRegistry`, an explicit profile registry, and a `ToolExecutor` factory. Separate processes MAY own separate Python objects.

The composition SHALL NOT require a distributed manifest service or bundle child lifecycle, durable event/outbox, projection, operator, approval, or business side-effect ports into execution wiring. Those contracts remain owned by their existing or follow-up changes.

#### Scenario: API and worker resolve execution wiring

- **WHEN** an API process and worker process are created from the same execution configuration
- **THEN** their compositions SHALL report the same composition, policy, and provider fingerprints
- **AND** each process SHALL use its own registry/provider instances only through the composition boundary.

#### Scenario: Expected execution identity drifts

- **WHEN** a process is configured with an expected composition fingerprint that differs from its resolved identity
- **THEN** startup, health, or execution admission SHALL reject the process with a typed composition-drift result
- **AND** it SHALL NOT create a substitute local provider or disable execution policy checks.

### Requirement: Required providers are role-scoped and fail closed

The composition SHALL distinguish catalogued providers from role-required providers. A process role that requires an external provider SHALL declare the provider id explicitly; unavailable required providers SHALL produce a stable typed blocked result at readiness or admission. A process role that only validates wiring MAY expose catalogued providers without treating them as startup dependencies.

#### Scenario: Research parser role lacks Docker

- **WHEN** the selected Research parser composition requires `docker` and no usable Docker provider is available
- **THEN** readiness/admission SHALL return a typed execution-environment denial with provider and denial-code details
- **AND** the parser SHALL NOT run through host `subprocess.run`.

#### Scenario: API validates optional external catalog

- **WHEN** an API process loads the shared execution catalog but has no selected external activity
- **THEN** the process MAY become ready after composition integrity validation
- **AND** any later external activity SHALL still be admitted against its provider and capability requirements.

### Requirement: External activity uses explicit admission

Every selected `sandboxed` or `external_process` activity SHALL enter `ExecutionEnvironment` admission with an exact Graph identity, registered activity profile, capability set, argv, working roots, allowlisted environment, timeout, and cancellation contract. Missing provider, profile, Graph identity, capability, or valid execution specification SHALL fail closed with a stable typed denial.

#### Scenario: Unsupported capability is requested

- **WHEN** an activity requests a provider capability such as a network allowlist, executable allowlist, secret handle, or resource limit that the provider does not declare
- **THEN** admission SHALL return a stable capability-denial code and structured missing-capability details
- **AND** it SHALL NOT reduce the request to host execution.

#### Scenario: Graph identity is missing

- **WHEN** an external activity has no exact Graph identity
- **THEN** admission SHALL reject it before provider dispatch
- **AND** no execution receipt SHALL report a successful activity.

### Requirement: Supported ToolExecutor paths receive composition injection

`AgentRunner`, Harness tool activity, batch executor, external subagent tool execution, API, worker, CLI, and Research composition SHALL receive execution registry/profile resolution from the process composition boundary. Production call sites SHALL NOT construct an unregistered external `ToolExecutor` or provider.

Only the selected Research parser external-process profile is production-enabled by this change. Other supported entrypoints SHALL validate wiring and fail-closed compatibility without claiming that their unselected external profiles are deployment-qualified.

#### Scenario: Harness tool activity resolves a profile

- **WHEN** Harness creates a selected external tool activity
- **THEN** its `ToolExecutor` SHALL use the registry and profile resolver supplied by the process composition
- **AND** missing or invalid profile data SHALL result in a typed denial before execution.

#### Scenario: API, worker, and CLI share identity

- **WHEN** API, worker, and CLI construct their default process composition
- **THEN** they SHALL expose the same execution composition fingerprint for the same configuration
- **AND** no entrypoint SHALL require event, child, approval, or operator ports from this change.

### Requirement: Selected Research parser uses the controlled adapter

The selected Research Marker/MinerU parser SHALL use `ResearchParserExecutionAdapter` to map parser intent to an `ExecutionRequest`. The adapter SHALL bind canonical cwd, read/write roots, mount mapping, allowlisted environment, network policy, timeout, cancellation semantics, Graph identity, and `ExecutionReceipt` mapping. Business parser services SHALL NOT own an unbounded host process handle.

#### Scenario: Parser request is mapped

- **WHEN** the selected parser is invoked for a Research document
- **THEN** the adapter SHALL issue one request with the declared profile, exact roots, environment, timeout, and Graph identity
- **AND** the parser result SHALL derive status and observation from the resulting receipt.

#### Scenario: Termination cannot be confirmed

- **WHEN** the provider cannot confirm parser termination after timeout or cancellation
- **THEN** the result SHALL remain typed indeterminate or blocked
- **AND** the adapter SHALL NOT report an ordinary parser success.

### Requirement: Harness-managed direct-process inventory is enforced

The change SHALL maintain a versioned caller inventory and source-validation check for Harness-managed production external activity. Each production process-creation or raw external-execution site SHALL be classified as migrated, trusted exemption, or blocked. Every exemption SHALL include owner, reason, non-Harness-managed proof, review date, and automated validation reference.

Docker provider internals, tests, and build/development tooling SHALL be outside this scan. The PDF compiler and outbound MCP/sidecar paths that are not selected for this vertical slice SHALL remain explicit blocked/handoff entries; they SHALL NOT be silently treated as migrated.

#### Scenario: Unapproved production caller appears

- **WHEN** source validation detects a new Harness-managed direct process caller without a valid inventory classification
- **THEN** the validation gate SHALL fail
- **AND** the caller SHALL be migrated or documented before the change can claim completion.

### Requirement: Trusted in-process work is explicit and authority remains unchanged

Only deterministic, side-effect-free functions explicitly registered as `trusted_in_process` MAY execute without an external provider. Caller flags, worker/LLM output, or provider absence SHALL NOT downgrade a sandboxed/external activity to trusted. Execution receipt/observation SHALL NOT grant routing, quality-gate, approval, memory-write, artifact-publication, or business side-effect authority.

#### Scenario: Unsafe downgrade is requested

- **WHEN** a caller requests in-process execution for an activity declared sandboxed or external
- **THEN** execution admission SHALL reject the downgrade
- **AND** Harness SHALL retain all control-plane decisions.
