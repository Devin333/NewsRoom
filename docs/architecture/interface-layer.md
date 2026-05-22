# Interface Layer

`interfaces/` contains surfaces for humans, APIs, SDK users, MCP clients, and application-level use cases.

## Surfaces

- `interfaces/cli`: command registration, argument parsing, handler dispatch, and presentation.
- `interfaces/api`: HTTP API routes and transport models.
- `interfaces/mcp`: inbound MCP tools, resources, prompts, and stdio/server adapters.
- `interfaces/sdk`: client-facing SDK surfaces.
- `interfaces/services`: application services that coordinate business use cases.

## CLI Rule

CLI command modules call `interfaces.services` application services. They do not directly instantiate workflow executors, stores, or business runners. This keeps command-line UX separate from runtime construction details.

## Service Rule

Services are application services. They may coordinate business workflows and infrastructure adapters, but complex business runtime assembly should live with the business workflow package, not in CLI handlers.
