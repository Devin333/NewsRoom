# NewsRoom MCP Surface

NewsRoom exposes MCP tools, resources, prompts, and capability metadata through
`MCPApplicationService`. MCP is an inbound interface surface: it calls
application services and returns contract-shaped payloads rather than reaching
into Graph executors, AgentLoop workers, storage clients, or Harness internals directly.

## Catalog And Manifest

The MCP catalog publishes:

- tools for report, run, source, memory, worker, approval, and Research actions
- resources such as latest report, run manifest, run replay, artifacts, memory,
  storage metrics, source health, workers, and queues
- prompts for Research paper briefing, report review, run diagnosis, and source
  triage

Clients can inspect the real service surface through:

```bash
news mcp catalog --json
news mcp manifest --json
```

The manifest mirrors the catalog and adds capability metadata such as
permission, risk level, read-only status, input schema, and side-effect hints.

## Tools

Tool calls are routed through `MCPApplicationService.call_tool()`. Read-only
tools report `read_only: true` and `side_effect_level: none`. Application write
tools report `side_effect_level: application_service_write`.

Dangerous tools that can perform external writes or high-risk run operations
advertise confirmation metadata:

```json
{
  "requires_confirmation": true,
  "side_effect_level": "external_write"
}
```

The current dangerous set includes `news.report.publish`, `news.run.cancel`,
`news.run.rerun_from_step`, `news.approval.approve`, and
`news.approval.reject`.

## Dangerous Tool Confirmation

`news.run.cancel` requests Graph run cancellation through
`RunOperationApplicationService`. The tool schema requires `run_id` and accepts
`reason`, `actor_id`, and `metadata`. Its capability metadata sets
`requires_confirmation` to `true`, `risk_level` to `high`, and
`side_effect_level` to `external_write`.

MCP clients must show a confirmation step before invoking any tool with
`requires_confirmation: true`. The confirmation should display the tool name,
the affected run or resource id, the user-provided reason, and the
`side_effect_level`. Calls without explicit confirmation should be blocked by
the client before they reach the service.

## Resources

Resource reads are routed through `MCPApplicationService.read_resource()`.
Resource payloads are read-only and redacted for interface consumption. Common
URIs include:

- `news://reports/latest`
- `news://reports/{report_id}`
- `news://runs/{run_id}/manifest`
- `news://runs/{run_id}/events`
- `news://runs/{run_id}/replay`
- `news://artifacts/{artifact_id}`
- `news://storage/metrics`
- `news://sources/health`

## Prompts

Prompt payloads are metadata templates only. They prepare operator-facing prompt
arguments for clients, but they do not route Graph nodes, decide quality gates, or
write memory. Harness and application services remain responsible for Graph
runtime decisions; AgentLoop only executes the bounded inner worker loop.
