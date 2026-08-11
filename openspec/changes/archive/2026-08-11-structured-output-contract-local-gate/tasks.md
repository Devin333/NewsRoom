## 1. Contract and preflight

- [x] 1.1 Add immutable structured-output contract, limits, validation result, and bounded diagnostic models.
- [x] 1.2 Implement canonical schema serialization/digest and `draft2020-12-local-v1` preflight with local-only references, approved keywords, portable patterns, and resource limits.
- [x] 1.3 Add Pydantic schema-source and post-schema typed-validation adapter while preserving object-root compatibility.

## 2. Strict local gate integration

- [x] 2.1 Implement the strict JSON-object decoder with non-finite, duplicate-key, root, depth, node, and byte-limit checks.
- [x] 2.2 Replace the hand-written validator implementation with the compiled Draft 2020-12 contract compatibility facade and export the new APIs.
- [x] 2.3 Route OpenAI-compatible complete structured parsing through the strict decoder and local contract, with stable non-retryable diagnostic errors.
- [x] 2.4 Widen request schema source typing and remove the Research-local non-finite JSON workaround after generic-boundary coverage exists.

## 3. Regression coverage

- [x] 3.1 Add contract/preflight tests for local refs, combinations, JSON numeric/boolean semantics, Pydantic nesting, forbidden refs/extensions, and limits.
- [x] 3.2 Add strict decoder/client tests for non-finite numbers, duplicate keys, non-object roots, diagnostics, and valid structured response compatibility.
- [x] 3.3 Add caller integration tests proving invalid structured output cannot reach the Research candidate path.

## 4. Validation and delivery

- [x] 4.1 Run focused structured-output, agent-loop, and Research tests; fix all in-scope failures.
- [x] 4.2 Run compile, smoke, strict OpenSpec validation, diff/secret checks, and commit the scoped change with its OpenSpec artifacts.
