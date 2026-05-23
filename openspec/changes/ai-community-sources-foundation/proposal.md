## Why

NewsRoom already has source registry, source health, source connectors, and preview fetch paths, but AI community sources are still split across legacy categories and narrow source-specific fetch commands. The final AI Community Sources plan needs a stable taxonomy, stronger registry validation, unified connector routing, and generic service/CLI fetch surfaces before specialized platform connectors are added.

## What Changes

- Add the final AI Community Sources PRD under `docs/prd/`.
- Replace the tracked source registry config with the seven final semantic categories.
- Add source catalog constants for category, priority, signal kind, and trust policy values.
- Validate AI community source taxonomy and priority metadata in `SourceRegistry`.
- Add `SourceConnectorRouter` for source type to connector dispatch.
- Extend `SourceApplicationService` and `news sources` CLI with generic source/category/priority/topic fetch methods.

## Out Of Scope

- Hugging Face, ModelScope, Papers with Code, Product Hunt, and X specialized connectors.
- API, MCP, and SDK exposure for source fetch methods.
- Quality filter scoring/ranking changes.
- Agent changes or direct external source calls from agents.
