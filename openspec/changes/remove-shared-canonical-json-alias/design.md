## Context

Shared currently exposes both `stable_json_dumps(value)` and `canonical_json(value)`, but the latter is a one-line wrapper with no production caller. The duplicate name is especially misleading because Harness TaskPlan owns a separate, stricter `canonical_json` implementation backed by `freeze_json()` and `canonical_json_bytes()`. Shared hashing is already layered correctly: structured values flow through `stable_json_dumps`, text through `hash_text`, and bytes through `hash_bytes`.

The repository also contains Workflow-specific stable serialization and checksum implementations. Those formats can be durable and are intentionally outside this cleanup because replacing them may invalidate existing manifest, DataBuffer, or checkpoint hashes.

## Goals / Non-Goals

**Goals:**

- Expose one unambiguous stable JSON serializer from Shared.
- Preserve the current `stable_json_dumps` output contract.
- Preserve distinct conversion and hashing layers.
- Make tests and learning artifacts describe the actual dependency graph.

**Non-Goals:**

- Replacing Harness TaskPlan canonicalization.
- Converging Workflow manifest, DataBuffer, or checkpoint checksum formats.
- Changing JSON bytes, SHA-256 algorithms, persisted hashes, or replay behavior.
- Adding a compatibility alias for the removed API.

## Decisions

1. Remove `canonical_json` rather than rename `stable_json_dumps`.
   - `stable_json_dumps` has broad production usage while the Shared `canonical_json` wrapper has none.
   - Alternative considered: keep both as semantic aliases. Rejected because two public names imply contracts that do not exist and conflict conceptually with the stricter TaskPlan canonicalizer.

2. Keep explicit conversion and hashing functions.
   - `to_jsonable` returns inspectable JSON-compatible values.
   - `stable_hash` returns a structured-value digest and composes `stable_json_dumps -> hash_text -> hash_bytes`.
   - `hash_text` and `hash_bytes` keep the UTF-8 encoding boundary explicit.

3. Do not consolidate durable Workflow serializers in this change.
   - Their `default=str`, indentation, set ordering, and normalization behavior differ from Shared.
   - Any convergence requires versioned persisted-format analysis and migration evidence.

4. Update the external learning card and diagram as part of the same change.
   - The diagram will show a dependency tree rather than slash-separated names that can be read as synonyms.

## Risks / Trade-offs

- [Risk] External consumers may import `framework.shared.canonical_json`. -> The removal is explicitly breaking; repository callers are verified absent, and no compatibility layer will be retained.
- [Risk] A future Shared canonical contract might be needed. -> Introduce it later only with distinct semantics and contract tests rather than a naming-only wrapper.
- [Risk] Learners may confuse Shared serialization with TaskPlan canonicalization. -> Notes will explicitly identify the stricter TaskPlan-owned contract as separate.
- [Trade-off] Parallel Workflow serializers remain. -> This avoids an unsafe durable-format migration in a narrowly scoped API cleanup.

## Migration Plan

1. Remove the Shared wrapper and public re-export.
2. Update Shared tests to assert `stable_json_dumps` directly and verify the removed export is absent.
3. Re-run repository searches to confirm no Shared `canonical_json` references remain.
4. Update and validate the external Shared learning card and Excalidraw diagram.
5. Run targeted Shared tests, compile, smoke, and strict OpenSpec validation.

Rollback restores the wrapper, public export, and its test without changing persisted data because serialization bytes are unchanged by this change.

## Open Questions

None for this scope. Durable Workflow serializer convergence requires a separate proposal.
