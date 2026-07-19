## Why

The production HTTP and MCP entrypoints currently construct `ResearchApplicationService` without an `AnalyzePaperUseCase`, so every default paper analysis fails with a hard-coded 503 even when the repository contains the real Harness/Research runtime. The same default also uses a process-local run store and has no concrete production adapters for the runtime's source, compiler, candidate worker, GitHub, RAG, or artifact ports.

## What Changes

- Add one interface-owned Research composition root that builds `ResearchApplicationService -> AnalyzePaperUseCase -> ResearchSinglePaperRuntime` from real configured adapters.
- Make HTTP Research, HTTP MCP, local MCP, stdio MCP, and `NewsMCPServerAdapter` reuse the same production service factory while retaining explicit dependency injection for tests.
- Add concrete Research adapters for arXiv metadata/source records, document compilation, structured LLM candidates, GitHub repository metadata, bounded document RAG, and durable Harness artifact publication.
- Replace the production in-memory Research run store with durable filesystem-backed records that can reconstruct analysis, reader, ask, and trace responses after process restart.
- Validate required source, parser, LLM, storage, and RAG configuration at the composition boundary and return a stable sanitized unavailable error only when the real runtime cannot be composed.
- Extend smoke and adapter-boundary integration coverage so production composition executes a real business/Harness path using recorded transport responses rather than production fakes.

## Capabilities

### New Capabilities

- `research-production-composition`: Defines the production service factory, concrete adapter graph, configuration/lifecycle rules, and HTTP/MCP entrypoint parity.
- `research-run-persistence`: Defines durable Research result/artifact storage and restart-safe query behavior.

### Modified Capabilities

- `research-runtime`: Requires the default production entrypoints to execute the real bounded Research/Harness runtime when configured and forbids unconfigured, fake, or in-memory-only defaults from representing production readiness.

## Impact

- Business: `ResearchSinglePaperRuntime` DTO serialization/reconstruction boundaries and existing Research ports, without importing infrastructure.
- Infrastructure: new `infrastructure/research` adapters over existing arXiv, GitHub, document, LLM, retrieval, and artifact components.
- Interfaces: one Research composition module used by API and all MCP transports; durable `ResearchRunStore` selection and typed availability errors.
- Configuration: Research source/LLM/parser/artifact settings, reusable client lifetime, and explicit startup validation.
- Tests/smoke: production object-graph assertions, offline recorded transport integration through real adapters and gates, filesystem restart reads, interface parity, missing-configuration failure, and optional credential-gated live E2E.
