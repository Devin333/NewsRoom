# Harness Graph Caller Migration Inventory

- Captured: 2026-07-29
- OpenSpec task: `1.2`
- Machine-readable authority: `caller-migration-inventory.json`

The inventory searches production and test Python sources for the public
Workflow/Scheduler/status/routing/checkpoint/replay/inspection contracts named
in task `1.2`. Every match is assigned to exactly one migration phase or to an
explicit non-Harness exclusion. A repository architecture test recomputes the
search and fails when a caller is added, removed, duplicated, or left
unclassified.

## Migration Phases

| Phase | Ownership and required migration |
|---|---|
| A | Graph contracts, compiler, reader, ports, public exports, and contract tests. These establish v2 types without taking write authority. |
| B | Current Scheduler, routing, run/step state, Control Plane handlers, and lifecycle tests. These move to one graph-aware Scheduler and per-node Step state. |
| C | Canonical event schemas, transition projector, durable recovery, replay kernel, Harness checkpoint/readers, and durability tests. These require v2 reducers/checkpoints plus bounded explicit v1 readers. |
| D | The production Research workflow/runtime and its composition regression. These first prove legacy-compiled equivalence, then adopt explicit Graph/Parallel-All. |
| E | Application Service, API, CLI, and MCP run inspection. These expose graph-safe lifecycle/outcome projections without accessing stores or Control Plane internals. |

The similarly named `current_step_id`, checkpoint, recovery, and run-status
symbols under `framework/workflow` belong to the separate generic Workflow
runtime. They are explicitly listed as exclusions so task `14.5` does not
delete or migrate the wrong engine.

The inventory is considered current only while
`tests/architecture/test_harness_graph_caller_inventory.py` passes.
