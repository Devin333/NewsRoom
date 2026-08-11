## Why

NewsRoom currently parses structured LLM responses with permissive `json.loads()` and validates them with a hand-written JSON Schema subset. That lets non-JSON values such as `NaN` enter the generic LLM path, silently ignores unsupported schema assertions, and does not validate nested Pydantic `$defs` / `$ref` contracts. A schema gate that can accept an invalid candidate is not a reliable deterministic boundary for the Harness.

The repository already declares `jsonschema>=4.0` and `pydantic>=2.6`. This change uses those dependencies to establish the canonical local structured-output contract before later changes add Provider capability routing, cache convergence, and Harness repair orchestration.

## What Changes

- Add an immutable `StructuredOutputContract` with canonical schema digest, explicit `draft2020-12-local-v1` dialect, root-object policy, limits, and normalized diagnostics.
- Add schema preflight that checks Draft 2020-12 validity, allows only same-document `$defs` / `$ref`, rejects unsafe or oversized schemas before any Provider call, and preserves a Pydantic model adapter when supplied.
- **BREAKING** Replace the production hand-written schema evaluator with `jsonschema.Draft202012Validator`; unsupported/unsafe schema input now fails closed rather than being silently ignored.
- Add a single strict JSON-object decoder that rejects malformed JSON, non-finite numbers, duplicate keys, non-object roots, and configured response limits.
- Route `OpenAICompatibleClient` structured-response parsing through the strict decoder and canonical local validator while retaining non-retryable deterministic content failures.
- Add Pydantic post-schema typed validation and bounded, stable, redacted validation diagnostics.
- Restore focused structured-output tests and add adversarial coverage for JSON Schema semantics, nested Pydantic models, strict parsing, and resource/reference policy.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `llm-structured-output`: Structured responses are normalized only after strict JSON-object decoding, with stable structured parse diagnostics.
- `llm-structured-output-validation`: Schema validation uses a canonical local Draft 2020-12 contract with Pydantic typed validation, safe reference policy, and fail-closed preflight semantics.

## Impact

- Affected code: `framework/llm/structured_output/*`, `framework/llm/clients/openai_compatible.py`, `framework/llm/models/request.py`, exports, and focused LLM tests.
- Affected API: `validate_structured_output()` remains the compatibility entry point but gains fail-closed Draft 2020-12 semantics; new typed contract/diagnostic APIs are added for managed callers.
- Dependencies: reuse existing `jsonschema` and `pydantic`; no new network dependency, Provider SDK, cache behavior, or Harness routing policy is introduced in this change.
- Follow-ups: Provider capability projection is Change 2; cache/Harness convergence is Change 3; Provider evaluation/release controls are Change 4.
