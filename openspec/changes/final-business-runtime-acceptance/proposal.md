## Why

The final business run facade exists, but the project needs explicit acceptance contracts to prove the full runtime surface is present and safe to serialize.

## What Changes

- Add final run acceptance tests for board workflows, cross-board outputs, feedback, learning, policy candidates, guards, artifacts, and metadata.
- Add recursive no-raw-payload contract tests.
- Avoid new runtime behavior unless tests expose an existing serialization gap.

## Capabilities

### New Capabilities
- `final-business-runtime-acceptance`: Final business runtime acceptance and raw payload safety contracts.

### Modified Capabilities

## Impact

- Affected code: tests, with minimal service fixes only if required.
