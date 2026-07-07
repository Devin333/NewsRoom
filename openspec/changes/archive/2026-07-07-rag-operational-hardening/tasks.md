## 1. Interface Documentation

- [x] 1.1 Add `docs/sdk/python.md` with supported Python SDK usage and interface boundary notes.
- [x] 1.2 Add `docs/web-console.md` with web console operational scope and safety expectations.
- [x] 1.3 Add `docs/mcp.md` with MCP tool/resource/prompt behavior and dangerous-tool confirmation metadata.

## 2. Transcript Persistence Hardening

- [x] 2.1 Add a Paper RAG service test proving transcript store failures do not fail a completed gated ask.
- [x] 2.2 Catch transcript persistence errors in gated Paper RAG asks and return an error-shaped `transcript_artifact`.

## 3. Verification

- [x] 3.1 Run interface documentation and Paper RAG service tests.
- [x] 3.2 Run compile and `openspec validate rag-operational-hardening --strict`.
- [x] 3.3 Commit the completed change.
