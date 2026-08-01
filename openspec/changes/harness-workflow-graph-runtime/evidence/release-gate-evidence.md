# Harness Graph Runtime v2 Release-Gate Evidence

- Captured: `2026-08-01`
- Change: `harness-workflow-graph-runtime`
- Implementation disposition: verified in the workspace candidate
- Production cutover disposition: blocked by upstream release qualification

## Verification Results

| Scope | Result |
| --- | --- |
| Graph compiler/validator/state/scheduler/Control Plane/parallel/loop/Wait/compensation/event/replay | `667 passed` |
| Durable event integration, Harness storage, side effects, skills | `97 passed` |
| Research workflow/application/non-live integration | `194 passed`, `9 deselected` |
| Research composition, Graph/Wait services, APIs, architecture boundaries | `220 passed`, warnings only |
| Mandatory smoke | `1910 passed`, `23 deselected`, `22 warnings` |

The warnings are the existing FastAPI `on_event` deprecation. They do not
weaken an assertion or change the Harness result.

## Fault Injection and Rollback

The selected deterministic fixtures passed at each required boundary:

| Crash point | Evidence |
| --- | --- |
| Decision/projection/activity dispatch and result | `20 passed` in `test_graph_control_plane.py` |
| After fork, during join, and before Parallel-Any winner | `4 passed` in `test_parallel_graph_control_plane.py` |
| Loop boundary and Wait registration/resume | `4 passed` across the loop and Wait recovery selections |
| During compensation dispatch/outcome and replay | `9 passed` in compensation/replay selections |

The five focused selections total `37` passed tests. The broader combined
selection was also run during the gate and had no failures.

Rollback remains graph-aware: a v2 history requires a graph-capable reader;
an unsupported v2 run stays suspended and is never resumed by a v1 executor.
No synthetic replay events or live Worker fallback are used during recovery.

## Performance

The deterministic preflight fixture validated `1,000` nodes and `5,000` edges
in `0.057068s`, below the `<5s` threshold. The test and direct measurement both
reported a valid graph.

## Schema and Migration

Current projection events write
`newsroom.harness-graph-projection-record/v2`, a bounded compact record. The
full graph state is reconstructed by the pinned reducer/applier and checked
against the projection commit checksum. The v1 full control-commit record is a
read-only compatibility window. v2 replay uses the separate history component
id `newsroom.harness-graph-projection-record` to avoid mixed-version pinning
conflicts.

The active Harness routing executor and old durable writer APIs are removed
from the candidate. The remaining `current_step_id` references are explicit
legacy readers or the separate generic `framework/workflow` runtime, not Graph
execution authority. There are no production callers of the legacy Harness
`.recover(...)` API.

## Dependency Limits

The exact dependency identities and qualification status are recorded in
`dependency-contract-baseline.json`. `durable-event-runtime` remains `52/55`
with external rollback/authority tasks open; `framework-runtime-safety-hardening`
remains `0/38` without a committed release identity; and
`harness-side-effect-authority-closure` is `51/51`, while Graph compensation
semantics remain owned by this change. Therefore task `1.1` and production
cutover authorization remain blocked even though implementation, replay,
compile, smoke, strict validation, and deterministic rollback drills pass.
