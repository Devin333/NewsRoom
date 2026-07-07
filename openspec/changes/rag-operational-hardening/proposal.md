## Why

The latest RAG readiness review found that the implementation path is nearly production-shaped, but two operational gaps still block a clean merge posture: interface documentation tests remain red and transcript audit persistence can fail the main `rag_ask` request after a valid answer is produced.

## What Changes

- Restore the required interface documentation files for Python SDK usage, web console operations, and MCP surface behavior.
- Document MCP dangerous-tool confirmation metadata, including `news.run.cancel`, `requires_confirmation`, `side_effect_level`, and `external_write`.
- Make gated Paper RAG transcript persistence best-effort: persistence failures are reported in `transcript_artifact` without failing the answer response.
- Add focused tests for the restored docs and transcript persistence failure behavior.

## Capabilities

### New Capabilities
- `rag-operational-hardening`: Operational hardening for Paper RAG and interface docs, covering required documentation presence and best-effort transcript audit persistence.

### Modified Capabilities

## Impact

- Affected docs: `docs/sdk/python.md`, `docs/web-console.md`, `docs/mcp.md`.
- Affected code: `interfaces/services/paper_rag_service.py`.
- Affected tests: interface documentation contract tests and Paper RAG service tests.
- No breaking API change; `transcript_artifact` remains additive and may carry an error payload when persistence fails.
