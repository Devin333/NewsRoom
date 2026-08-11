## Context

`LLMRequest.output_schema` currently accepts a dict and `OpenAICompatibleClient` parses response text with permissive `json.loads()` before calling a hand-written recursive validator. The validator covers a useful subset but does not resolve Pydantic `$defs` / `$ref`, silently ignores unsupported JSON Schema assertions, and applies Python rather than JSON Schema equality semantics in several cases. `infrastructure/research/candidate_worker.py` compensates for non-finite numbers locally, leaving the generic boundary inconsistent.

The repository already ships `jsonschema>=4.0` and `pydantic>=2.6`. The existing response contract is object-only: `LLMResponse.structured_output` is `dict[str, Any] | None`. This change makes that boundary deterministic without expanding it to generic JSON roots or taking ownership of Provider capability routing, cache, or Harness policy.

## Goals / Non-Goals

**Goals:**

- Compile dict or Pydantic model schemas into immutable, digest-addressed local contracts before Provider I/O.
- Run `Draft202012Validator.check_schema()` and deterministic instance validation with local-only references.
- Decode JSON objects strictly, including rejection of `NaN`, `Infinity`, duplicate keys, oversized/overdeep instances, and non-object roots.
- Preserve Pydantic validation after JSON Schema validation and normalize all deterministic failures into bounded diagnostics.
- Keep `validate_structured_output()` as a compatibility API while moving its implementation to the canonical contract path.
- Apply the same decoder and local validator to the OpenAI-compatible non-stream response path.

**Non-Goals:**

- Provider keyword capability negotiation, schema projection, constrained decoding, deployment fallback, or stream terminal parity.
- Cache identity/read-write convergence and Harness repair/replan/event integration.
- External `$ref`, filesystem/network resolution, arbitrary custom keywords, generic JSON array/scalar response roots, or generated JSON extraction from prose.
- Reimplementing JSON Schema, Pydantic, or a regex/grammar engine in NewsRoom.

## Decisions

### 1. `jsonschema.Draft202012Validator` is the only JSON Schema evaluator

`StructuredOutputContract` stores a canonical JSON schema, SHA-256 digest, local dialect revision, safe limits, and an optional typed adapter. Preflight calls `Draft202012Validator.check_schema()` and validation calls `iter_errors()` before deterministic sorting/capping.

The previous recursive evaluator will be replaced by a compatibility facade around the compiled contract. Keeping two evaluators would recreate split semantics and permit a caller to choose the weaker path.

Alternative considered: extend the hand-written subset. Rejected because Draft semantics, reference resolution, equality, and combinations are security/correctness surfaces already covered by the installed dependency.

### 2. The local dialect is safe Draft 2020-12, not unrestricted schema execution

`draft2020-12-local-v1` accepts standard Draft 2020-12 validation/applicator/annotation keywords used by the repository and Pydantic exports. It permits only same-document JSON Pointer `$ref` values beginning with `#`; remote, file, package, relative, dynamic, and unregistered extension references fail before validation. Preflight bounds schema byte size, node count, depth, `$ref` chain depth, enum size, and pattern length.

JSON Schema `format` remains annotation-only in this change. A future explicit `FormatChecker` allowlist can make selected formats assertions without silently changing existing behavior. Patterns are limited to a portable subset and preflight rejects Python-only / high-risk constructs rather than relying on Python `re` as an undocumented dialect.

Alternative considered: allow all schemas accepted by `jsonschema`. Rejected because validators can otherwise attempt remote retrieval and extension behavior would become deployment-dependent.

### 3. Strict decoding precedes validation

`StrictStructuredOutputDecoder` checks response byte length, uses `parse_constant` to reject non-finite numeric tokens, uses `object_pairs_hook` to reject duplicate keys, and bounds the parsed tree before returning a dict. It does not strip Markdown fences or repair malformed content.

Alternative considered: validate after normal `json.loads()` and use `json.dumps(..., allow_nan=False)` later. Rejected because invalid values already crossed the generic client boundary and duplicate keys have already been collapsed.

### 4. Pydantic source models retain typed validation

When a Pydantic model class is supplied, preflight stores an adapter together with `model_json_schema()`. The output passes Draft validation first, then `model_validate()`. The adapter serializes the validated model in JSON mode and verifies the result is a finite object. This captures cross-field/model validators that JSON Schema cannot express.

Alternative considered: consume only `model_json_schema()`. Rejected because that loses model validator semantics and causes nested model `$ref` output to appear valid when typed contract rules reject it.

### 5. Deterministic diagnostics are a data contract

`StructuredOutputDiagnostic` has a stable code, instance path, schema path, validator name, safe message, contract digest, and no raw instance payload. Errors are sorted and capped. `LLMStructuredOutputValidationError` carries diagnostics while retaining `ValueError` compatibility for existing callers.

Alternative considered: expose raw `jsonschema.ValidationError`. Rejected because exception internals, schema/instance values, and order are not a stable or safe cross-layer API.

### 6. Request compatibility is explicit

`LLMRequest.output_schema` widens from dict-only to `Any | None` so callers can pass a Pydantic model class. `LLMResponse.structured_output` remains object-only. The compiler accepts an already-compiled contract so router/client composition can avoid repeated schema work in later changes.

## Risks / Trade-offs

- [Existing caller uses a custom or Provider-specific schema extension] -> Preflight fails closed with a diagnostic; add an approved extension/dialect revision through OpenSpec rather than silently ignoring it.
- [Strict parsing rejects legacy prose-wrapped JSON] -> Migrate the caller to a separate explicit extractor or change its response contract; generic structured output stays strict.
- [Pydantic coercion changes values] -> Require JSON-mode dump and finite-object recheck; tests pin model configuration behavior.
- [Complex schemas use CPU or memory] -> Enforce schema/instance limits and cap diagnostics before instance validation results cross layers.
- [The initial client integration does not cover streaming] -> Mark `output_schema + stream` as deferred/ineligible until Change 2 adds terminal parity; never claim stream is locally verified in Change 1.

## Migration Plan

1. Add contract, preflight, decoder, validator facade, Pydantic adapter, and focused tests behind existing public imports.
2. Route OpenAI-compatible complete structured parsing through the decoder/contract while keeping deterministic errors non-retryable.
3. Remove Research's local non-finite-number workaround once an integration test proves the generic boundary rejects it.
4. Add capability-routing and stream terminal semantics in Change 2, then cache/Harness convergence in Change 3.
5. Roll back by reverting the composition binding only for workflows not yet migrated; do not restore permissive parsing for an enabled structured-output workflow.

## Open Questions

- No blocking questions. The maximum schema/instance limits begin as conservative configuration defaults and will be measured in Change 4's Provider/schema corpus before widening.
- Streamed structured output remains explicitly out of scope for this change; Change 2 owns its terminal validation contract.
