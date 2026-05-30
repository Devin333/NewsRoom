## Why

Phase 3 introduced graph, historian, evaluation, consolidation, feedback, and policy-learning modules, but those capabilities are still mostly internal building blocks. This change finalizes Phase 3 by exposing stable application/worker/workflow entrypoints and lightweight observability without replacing the existing structured memory architecture.

## What Changes

- Add worker parsing/build helpers for dry-run memory consolidation tasks.
- Add historian context adaptation and wire historian metadata into report writing and daily quality gate metadata.
- Add application services for graph memory, memory evaluation, feedback submission, and policy proposal generation.
- Add graph projection summaries for observable graph node/edge/type counts.
- Add a minimal Phase 3 loop integration test that connects graph, historian, evaluation, policy proposals, and feedback ingestion.

## Capabilities

### New Capabilities

### Modified Capabilities
- `memory-evolution`: Phase 3 memory evolution capabilities become callable through worker, workflow, and application-service boundaries with observable outputs.

## Impact

- Affects business memory modules, daily intelligence writer/quality gate integration, business worker handler surface, interface service modules, and targeted tests.
- No Neo4j/Kuzu dependency, no framework runtime rewrite, no Phase 2 ingestion/recall replacement, and no automatic application of high-risk policy changes.
