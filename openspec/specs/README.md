# OpenSpec Specs Index

This folder contains the currently active capability specs for Agora Hub.

- Framework runtime specs cover Graph orchestration, Harness control-plane policy, AgentLoop worker execution, tool/runtime safety, storage, memory, and worker scheduler closure.
- Business specs cover board runtime, cross-board intelligence, foundation quality loop, and business-layer pipelines.
- Interface specs cover API/CLI/MCP contracts and Graph Wait approval-cause/resume flows. `harness-graph`, `graph-storage-indexing`, and `approval-graph-resume-interfaces` are the canonical owners for the Graph-only cutover.

Retired Workflow capability specs remain only as explicit history/provenance tombstones. They are not live contracts and must not be reintroduced as compatibility facades.

Historical implementation changes live under `openspec/changes/archive`. New architecture governance work should use staged changes and avoid large file moves that break compatibility imports.
