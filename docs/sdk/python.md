# NewsRoom Python SDK

The Python SDK is an interface-layer client for the HTTP API. It calls API
contracts and application services through the public boundary; it must not
reach into workflow executors, concrete stores, Harness internals, or business
runtime modules.

## Install

For local development, install the repository package and use the checked-in
client implementation:

```bash
python -m pip install -e ".[dev]"
```

The lightweight client lives at `interfaces.sdk.python_client.NewsClient`.
Example scripts live under `examples/sdk/`.

## Basic Usage

```python
from interfaces.sdk.python_client import NewsApiError, NewsClient

client = NewsClient(
    "http://localhost:8000",
    api_key="local-token",
)

try:
    analysis = client.research.analyze_paper(
        paper_id="arxiv:2501.00001",
        source_url="https://arxiv.org/abs/2501.00001",
    )
except NewsApiError as exc:
    print(exc.code, exc.message, exc.request_id)
else:
    print(analysis)
```

## Client Groups

`NewsClient` exposes grouped helpers for the stable interface surface:

- `client.runs`: inspect run manifests, events, replay bundles, health, lineage,
  artifacts, and operations.
- `client.reports`: list and read persisted reports.
- `client.memory`: search and reindex memory.
- `client.sources`: list, probe, validate, and fetch configured real sources.
- `client.mcp`: inspect MCP catalog and manifest payloads.
- `client.workers`: inspect workers and queues.
- `client.schedules`: manage scheduled maintenance tasks.
- `client.approvals`: submit approval decisions.
- `client.research`: analyze papers and read Research paper payloads.

## Response Contract

The SDK unwraps successful API envelopes and returns the `data` object. Error
envelopes raise `NewsApiError` with the server error code, message, retryable
flag, user-action flag, details, status code, and request id.

Transport callers should preserve `request_id` values in logs and user-facing
diagnostics so API, MCP, and Harness events can be correlated during incident
review.

## Examples

Run the checked-in examples against a local backend:

```bash
set NEWSROOM_API_BASE_URL=http://localhost:8000
set NEWSROOM_API_TOKEN=local-token
python examples/sdk/analyze_research_paper.py
python examples/sdk/latest_report.py
```

Tests may use fake openers or fake API payloads, but production SDK code should
always go through the HTTP interface contract.
