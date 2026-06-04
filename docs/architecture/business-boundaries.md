# Business Boundaries

This document describes the current `business/` boundary after the Harness + Research cleanup.

## Current Ownership

- `business/research/` owns Research domain models, ports, use cases, paper analysis workflow specs, reader payload construction, reader repair memory, taxonomy, benchmark, code repository, method graph, agent intelligence, and RAG policy rules.
- `business/layers/` owns reusable domain processing primitives for signal, extraction, relation, analysis, output, and memory. These modules may depend on foundation primitives, but must not depend on old board packages.
- `business/foundation/` owns shared enums, registries, evidence primitives, source definitions, policy models, subscription primitives, and skill package metadata. It must remain free of layer or interface dependencies.
- `business/workers/` owns domain-neutral worker task handlers that call application-safe services or reusable business layers.
- `business/tools.py` and `business/layers/signal/connector_tools.py` expose real connector-backed tools that can be registered through Harness or MCP-facing tool catalogs.

## Removed Legacy Surface

The old board runtime packages were deleted from the production business surface:

```text
business/boards
business/scoring
business/evaluation
```

Production code must not keep compatibility adapters for old board workflows, old `paper_radar` payloads, old daily or weekly report runners, or old paper reader APIs. Useful business rules must be migrated into `business/research`, `business/layers`, or framework-level Harness primitives before the old module is removed.

## Research Boundary Rules

- `business/research` must not import `business.boards`, `interfaces`, or concrete `infrastructure` adapters.
- Research use cases define domain inputs and outputs; interface services translate HTTP, SDK, CLI, or MCP requests into those use cases.
- Harness controls workflow routing, quality decisions, retries, replans, memory writes, artifact publication, trace, checkpoint, and replay.
- LLMs and subagents may generate candidate content, but they must not decide routing, quality pass/fail, tool authorization, memory writes, or publication.

## Interface Boundary Rules

- Interface layers call application services under `interfaces/services`.
- Interface services coordinate DTO translation and dependency injection; they do not reach into old business runners, executors, or stores directly.
- Old `/api/v1/papers*`, `/api/v1/boards*`, `/api/v1/runs/daily`, and `/api/v1/runs/weekly` routes are intentionally absent.
- MCP server inbound interfaces and outbound ToolRuntime MCP adapters remain separate concerns.

## Testing Boundary Rules

Architecture tests must enforce:

- No production import of `business.boards`.
- No production import of removed paper services or old paper routers.
- No `business/research` import of `interfaces` or concrete `infrastructure`.
- No framework import of business, interfaces, or concrete infrastructure.

Focused tests should cover migrated Research rules instead of preserving old board-specific behavior.
