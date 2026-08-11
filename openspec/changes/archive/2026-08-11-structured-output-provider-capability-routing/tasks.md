## 1. Projection contracts

- [x] 1.1 Add immutable provider capability, request policy, projection result, coverage inventory, and stable digest contracts.
- [x] 1.2 Implement pure fail-closed projection for native strict, constrained, JSON-object local-gate, and rejected modes without mutating canonical schema.
- [x] 1.3 Export safe projection diagnostics and contract/projection metadata helpers.

## 2. Deployment and router integration

- [x] 2.1 Extend deployment configuration with validated versioned structured-output capability profiles and identity checks.
- [x] 2.2 Compile once before routing, independently project every deployment attempt, route on ineligibility, and record bounded selected/rejected metadata.
- [x] 2.3 Run model-aware context preparation after projection so token accounting sees the actual provider response format.

## 3. Client and stream parity

- [x] 3.1 Make the OpenAI-compatible adapter consume explicit projections for native strict and JSON-object modes and fail closed for unsupported adapter mappings.
- [x] 3.2 Preserve compiled contract/projection execution context through request normalization without weakening public serialization or cache identity.
- [x] 3.3 Accumulate structured streams, mark fragments provisional, validate terminal content through the complete-path gate, and expose the validated terminal object and parity metadata.
- [x] 3.4 Preserve stream terminal structured output through router capture and cached-event replay boundaries without authorizing provisional fragments.

## 4. Regression coverage

- [x] 4.1 Add unit tests for dialect, keyword, reference, limit, mode, policy, coverage, immutability, and stable projection digest behavior.
- [x] 4.2 Add configuration/client payload tests for explicit capability revisions, native strict, JSON-object local gate, constrained adapter rejection, and zero-transport rejection.
- [x] 4.3 Add router fallback tests proving every deployment is re-projected before context preflight and unsupported primary schemas do not call transport.
- [x] 4.4 Add complete/stream parity tests for valid, malformed, locally invalid, interrupted, and provisional-fragment cases.

## 5. Validation and delivery

- [x] 5.1 Run focused structured-output, client, routing, stream, context, and architecture tests; fix all in-scope failures.
- [x] 5.2 Run compile, smoke, strict OpenSpec validation, diff/secret checks, archive, and commit the scoped change.
