# NewsRoom Project Architecture

NewsRoom is organized as a spec-driven news intelligence runtime with four primary layers:

- `framework/`: domain-neutral runtime capabilities for Graph Harness control, bounded AgentLoop execution, tools, memory, scoring, governance, workers, events, artifacts, LLM integration, and shared primitives.
- `business/`: NewsRoom intelligence concepts, source/evidence/report models, ranking policies, business skill packages, and application-specific Graph definitions.
- `infrastructure/`: concrete adapters for storage, source connectors, external APIs, checkpoints, metrics, and operational persistence.
- `interfaces/`: user and integration surfaces such as CLI, HTTP API, MCP, SDK, webhooks, and application services.

## Dependency Direction

- `framework` must not depend on `business`.
- `framework` must not depend on `interfaces`.
- `framework` must not depend on concrete `infrastructure` implementations.
- `business` may depend on `framework` contracts and runtime APIs.
- `interfaces` are entry layers and should call application services instead of Graph executors, stores, or AgentLoop runners directly.
- `interfaces.services` coordinate use cases across `business`, `framework`, and `infrastructure`.
- `infrastructure` implements external technical details and adapters for protocols defined by `framework`, `business`, or service-layer composition.
- `tests` may depend on every layer they verify.

## Main Runtime Path

The main path is source collection -> evidence -> Graph-controlled AgentLoop analysis -> report -> deterministic quality gate -> artifacts/storage. Deterministic work stays in normal functions or services. AgentLoop is reserved for agent-shaped work, and Skill Runtime remains separate from the Graph control plane and AgentLoop internals.

## Extension Rule

New runtime capabilities should enter through the existing layer where they belong. Do not add framework evolution packages, bypass runners, sidecar harnesses, or business-specific shortcuts inside `framework`.
