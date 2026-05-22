# NewsRoom Project Architecture

NewsRoom is organized as a spec-driven news intelligence runtime with four primary layers:

- `framework/`: domain-neutral runtime capabilities for agents, workflow, tools, memory, scoring, governance, workers, events, artifacts, specs, LLM integration, and shared primitives.
- `business/`: NewsRoom intelligence concepts, board workflows, source/evidence/report models, ranking policies, business skill packages, and application-specific workflow definitions.
- `infrastructure/`: concrete adapters for storage, source connectors, external APIs, checkpoints, metrics, and operational persistence.
- `interfaces/`: user and integration surfaces such as CLI, HTTP API, MCP, SDK, webhooks, and application services.

## Dependency Direction

- `framework` must not depend on `business`.
- `framework` must not depend on `interfaces`.
- `framework` must not depend on concrete `infrastructure` implementations.
- `business` may depend on `framework` contracts and runtime APIs.
- `interfaces` are entry layers and should call application services instead of executors, stores, or runners directly.
- `interfaces.services` coordinate use cases across `business`, `framework`, and `infrastructure`.
- `infrastructure` implements external technical details and adapters for protocols defined by `framework`, `business`, or service-layer composition.
- `tests` may depend on every layer they verify.

## Main Runtime Path

The main path is source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage. Deterministic work stays in normal functions or services. Agent execution is reserved for agent-shaped work, and Skill Runtime remains separate from agent and workflow internals.

## Extension Rule

New runtime capabilities should enter through the existing layer where they belong. Do not add framework evolution packages, bypass runners, sidecar harnesses, or business-specific shortcuts inside `framework`.
