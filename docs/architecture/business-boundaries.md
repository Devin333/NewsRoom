# Business Boundaries

`business/` contains NewsRoom-specific intelligence behavior. It depends on framework contracts and runtime APIs, but it does not redefine framework runtime responsibilities.

## Areas

- `business/foundation`: shared NewsRoom domain models, primitives, policies, registries, feedback concepts, and business skill package content.
- `business/layers`: reusable domain processing layers such as signal, extraction, relation, analysis, memory, and output.
- `business/boards`: board-level intelligence products and workflows such as AI news, paper radar, project radar, community pulse, cross-board daily intelligence, and weekly intelligence.

## Skills Boundary

Business skill packages live under `business/foundation/skills`. Framework Skill Runtime lives under `framework/skills`. Business skill content must not be merged into framework runtime, and framework skill execution must not be folded into agent or workflow code.

## Workflow Boundary

Daily and weekly cross-board workflows own NewsRoom-specific source selection, evidence construction, report writing, quality policy, and artifact publishing. Workflow runners should be thin orchestration surfaces; dependency creation belongs in runtime assembly modules.
