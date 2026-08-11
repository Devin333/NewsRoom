## 1. Cache contract convergence

- [x] 1.1 Add immutable structured-output cache identity derived from compiled contract and selected projection.
- [x] 1.2 Bind key and entry identity to schema/capability/projection revisions and reject unmanaged structured cache requests.
- [x] 1.3 Revalidate terminal output before write and after read; convert mismatches/corruption to observable misses.
- [x] 1.4 Preserve terminal structured output and validation identity across stream cache capture/replay.

## 2. Harness repair and diagnostics

- [x] 2.1 Extend JudgeVerdict with bounded stable structured-output diagnostics and deterministic response fingerprint.
- [x] 2.2 Integrate schema/typed failures with existing AgentLoop judge retry/iteration budgets and unchanged-candidate halt detection.
- [x] 2.3 Emit repair-requested, accepted, and exhausted attempt events without raw output or schema bodies.
- [x] 2.4 Keep domain/evidence validators after schema acceptance and prove they still block publication.

## 3. Events, metrics, and replay

- [x] 3.1 Add the safe structured-output event envelope, allowlisted event types, sink protocol, and redacted serialization.
- [x] 3.2 Add low-cardinality counters/histograms for preflight, projection, validation, repair, cache validation, and duration.
- [x] 3.3 Project safe attempt events into AgentLoop replay and the existing durable workflow recorder boundary.

## 4. Research and architecture closure

- [x] 4.1 Make Research consume only managed verified terminal output and remove local schema interpretation.
- [x] 4.2 Inventory production structured-output callsites and add an AST architecture test rejecting direct response parsing/validation bypasses.
- [x] 4.3 Migrate remaining production callsites and update explicit test fakes.

## 5. Validation and delivery

- [x] 5.1 Add cache, complete/stream, AgentLoop bounded repair, durable replay, Research, and architecture tests.
- [x] 5.2 Run focused suites, compile, smoke, strict OpenSpec validation, diff/secret checks, archive, and commit.
