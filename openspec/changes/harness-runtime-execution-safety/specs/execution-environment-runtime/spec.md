## ADDED Requirements

### Requirement: Harness admits physical execution capabilities
The Harness SHALL admit a tool or external worker only when the selected execution provider declares every filesystem, network, environment, process, resource, and cancellation capability required by the normalized execution profile.

#### Scenario: Missing capability fails closed
- **WHEN** a sandboxed tool requests a network or filesystem restriction that the selected provider cannot enforce
- **THEN** the Harness rejects the activity with stable reason code `execution_environment_unavailable` and does not invoke the tool executor

#### Scenario: Trusted pure function is explicitly classified
- **WHEN** a tool is registered as `trusted_in_process` and its profile declares no filesystem, network, subprocess, or external side effect
- **THEN** the Harness may execute it in process after the existing policy, approval, budget, and Graph identity gates pass

### Requirement: ExecutionEnvironment enforces filesystem and environment boundaries
The selected execution provider SHALL canonicalize declared roots, enforce read/write containment, reject traversal and escape through drive-relative, UNC, symlink, or junction paths, and expose only the explicitly allowed environment variables and named secret handles.

#### Scenario: Path escape is rejected
- **WHEN** a tool attempts to read or write outside its declared canonical roots, including through a symlink or junction
- **THEN** the provider rejects the operation and records a redacted policy reason without returning the protected path contents

#### Scenario: Undeclared environment data is unavailable
- **WHEN** a sandboxed process reads an environment variable that is not in its allowlist
- **THEN** the variable is absent and the execution receipt does not contain raw secret values

### Requirement: ExecutionEnvironment enforces network and child-process policy
The execution provider SHALL default to no network access, enforce declared host/port policy when supported, and constrain child-process creation to the admitted process policy.

#### Scenario: Network is denied by default
- **WHEN** a sandboxed tool has no admitted network capability
- **THEN** outbound network access is blocked and the tool receives a typed denial rather than a best-effort warning

#### Scenario: Unauthorized child process is blocked
- **WHEN** a sandboxed process attempts to spawn an executable or shell not covered by its process policy
- **THEN** the provider blocks the child and records a terminal policy violation

### Requirement: Cancellation reports termination certainty
The execution provider SHALL implement bounded cancellation as request, grace period, process-tree termination, and termination verification, and SHALL distinguish confirmed termination from indeterminate outcome.

#### Scenario: Confirmed cancellation
- **WHEN** cancellation is requested and the complete process tree is terminated within the grace period
- **THEN** the receipt is `cancelled` with `termination_confirmed=true`

#### Scenario: Indeterminate side effect cannot retry
- **WHEN** cancellation cannot confirm that a process with an external side effect has stopped
- **THEN** the receipt is `indeterminate` and Harness retry policy forbids automatic re-execution of that side effect

### Requirement: Execution receipt binds to Graph identity
Every admitted execution SHALL emit an immutable receipt bound to the exact Graph, activity, node, stage, and attempt identity used for admission.

#### Scenario: Identity mismatch is rejected
- **WHEN** a provider receipt or tool result carries an activity or attempt identity different from the admitted request
- **THEN** Harness rejects the result and does not advance Graph verification or publication
