## Why

`framework.shared.json.canonical_json()` currently delegates directly to `stable_json_dumps()` and has no production caller in the repository. Keeping both names in the public Shared API suggests two canonicalization contracts where only one implementation exists, which obscures the actual `to_jsonable -> stable_json_dumps -> stable_hash` dependency chain.

## What Changes

- **BREAKING** Remove `canonical_json` from `framework.shared.json` and the `framework.shared` public export surface.
- Keep `stable_json_dumps` as the single Shared stable JSON serialization entry point without changing its output bytes.
- Keep `to_jsonable`, `stable_hash`, `hash_text`, and `hash_bytes` as distinct layered primitives.
- Preserve the separate Harness TaskPlan `canonical_json` contract and all existing Workflow manifest, buffer, and checkpoint checksum formats.
- Update tests and the external interview-learning notes/Excalidraw diagram to show the real dependency chain and boundaries.

## Capabilities

### New Capabilities

- `shared-json-primitives`: Defines the unique Shared JSON conversion, stable serialization, and hashing API contract.

### Modified Capabilities

None.

## Impact

- Affected code: `framework/shared/json.py`, `framework/shared/__init__.py`, and `tests/framework/shared`.
- Affected public API: imports of `framework.shared.canonical_json` or `framework.shared.json.canonical_json` will fail after this change.
- Unaffected durable contracts: Harness TaskPlan canonical JSON, Workflow manifest hashes, DataBuffer hashes, and checkpoint checksums retain their current implementations and byte representations.
- Affected learning artifacts: the Shared framework card and its JSON/hashing Excalidraw diagram in the external `F:` Obsidian vault.
