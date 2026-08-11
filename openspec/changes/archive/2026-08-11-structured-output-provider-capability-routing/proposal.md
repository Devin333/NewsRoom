# Change: Add provider capability routing for structured output

## Why

The local structured-output contract is now deterministic, but provider payload selection still assumes that every OpenAI-compatible deployment can enforce the same `strict: true` JSON Schema. The router has only a coarse boolean capability, does not re-project schemas per fallback deployment, and streaming terminal output is not validated through the same contract as `complete()`.

This change supersedes the Provider translation portion of the canonical `llm-structured-output` capability. Provider enforcement becomes an explicit, versioned deployment fact; unsupported schemas route, use an explicitly allowed JSON-object-plus-local-gate mode, or fail before transport.

## What Changes

- Add immutable provider structured-output capability, policy, and projection contracts with stable coverage and projection digests.
- Resolve and record a fresh projection for every router deployment attempt before model-aware context preflight.
- Make the OpenAI-compatible adapter consume the selected projection instead of assuming native strict support.
- Gate streaming terminal content through the same compiled contract as complete responses and mark all non-terminal fragments provisional.
- Include the selected provider response format in context/token accounting and add protocol/fallback regression coverage.

## Impact

- Affected spec: `llm-structured-output`
- Affected code: `framework/llm/structured_output`, `framework/llm/models`, `framework/llm/clients`, `framework/llm/routing`, `framework/llm/context`, and focused LLM tests
- Provider capability is configuration-owned and versioned. API failures never teach or mutate capability state.
- Local strict decode and validation remain mandatory in every projection mode.
