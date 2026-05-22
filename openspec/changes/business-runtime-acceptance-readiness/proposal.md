## Why

Business full productization is implemented, but the project still needs a focused runtime acceptance layer that proves the productized boards run offline, publish stable artifacts, expose subscription-ready outputs, persist approved improvement proposals across runs, and can be consumed from service and CLI entrypoints.

## What Changes

- Add runtime acceptance documentation and an OpenSpec-tracked acceptance plan.
- Add an offline `BusinessAcceptanceService` with unified acceptance result models.
- Add a `news business acceptance` CLI command that calls the acceptance service only.
- Add richer fixture signal datasets for productized board acceptance.
- Add schema/readiness tests for artifacts, cross-board aggregation, weekly enhanced outputs, proposal persistence, eval suite, subscription delivery plan consumption, and CLI smoke.
- Tighten small readiness gaps: proposal LocalJson path handling, `BoardEvalReport.pass_rate`, and subscription delivery plan helpers.

## Capabilities

### New Capabilities
- `business-runtime-acceptance-readiness`: Offline acceptance service, CLI smoke command, fixture dataset, artifact schema acceptance, cross-board/weekly acceptance, eval suite readiness, productized subscription consumption, and durable proposal persistence verification.

## Impact

- Affected code: `interfaces/models`, `interfaces/services`, `interfaces/cli`, `business/foundation/feedback`, `business/evaluation`, `docs/business`, tests, and fixture helpers.
- No framework runtime, board runner base, board service base, Skill Runtime structure, real network, real LLM, or automatic proposal application changes.
