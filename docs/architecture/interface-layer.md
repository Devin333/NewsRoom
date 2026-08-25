# Interface Layer

`interfaces/` contains entrypoints for humans, API clients, SDK users, MCP clients, webhooks, and application-level use cases.

## Surfaces

- `interfaces/cli`: command registration, argument parsing, handler dispatch, and presentation.
- `interfaces/api`: HTTP API routes and transport models.
- `interfaces/mcp`: inbound MCP tools, resources, prompts, and stdio/server adapters.
- `interfaces/sdk`: client-facing SDK surfaces.
- Webhook adapters, when present, are also entry-layer code.
- `interfaces/services`: application services that coordinate business use cases.

## CLI Rule

CLI command modules parse arguments, format output, and call `interfaces.services` application services. They do not directly instantiate Graph executors, stores, AgentLoop workers, or business runners.

`interfaces/cli/news.py` is only the command registration entrypoint. It owns `COMMAND_MODULES`, `build_parser()`, `main()`, and shared JSON printing. It does not re-export service classes, framework models, business constants, or infrastructure adapters.

## Service Rule

Services are application services, not bottom-level runtime packages. They may coordinate Research use cases and Graph composition with infrastructure adapters, but complex runtime assembly should live with the owning composition service, not in CLI handlers.

`interfaces/services/run_service.py` is a facade. It keeps the stable `RunApplicationService` public API and delegates run inspection, Graph operation, Wait/approval, live smoke, persistence, and Graph resolution concerns to focused application services. Graph executor selection and approval decision handling belong in those focused services, not in the facade.
