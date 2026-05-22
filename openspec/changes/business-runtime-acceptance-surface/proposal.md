## Why

The final business runtime surfaces are now implemented, but the acceptance contract needs to cover the public artifact, CLI/service, cross-board, weekly, persistence, eval, and raw payload safety surfaces as one offline readiness layer.

## What Changes

- Extend business runtime acceptance with final business run checks.
- Add `news business acceptance --final` while keeping existing acceptance modes compatible.
- Remove raw/secret field exposure from final business run evidence-derived public payloads.
- Add artifact, cross-board, weekly, proposal persistence, and eval suite acceptance tests.
- Add OpenSpec-tracked requirements for the acceptance surface completion.

## Capabilities

### New Capabilities

- `business-runtime-acceptance-surface`: Acceptance service, CLI command, artifact contract, cross-board runtime, weekly runtime, proposal persistence, eval suite, and raw payload safety readiness.

### Modified Capabilities

## Impact

- Affected code: `interfaces/services`, `interfaces/models`, `interfaces/cli`, `business/boards`, and tests.
- No framework runtime, productized board runner, real network, real LLM, or automatic proposal application changes.
