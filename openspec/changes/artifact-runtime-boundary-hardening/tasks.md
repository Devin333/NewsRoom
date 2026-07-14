## 1. Shared Boundary

- [x] 1.1 Add `ArtifactPathError` and the fixed segment, relative-path, and canonical descendant helpers in `framework/artifacts/paths.py`.
- [x] 1.2 Export the public path API and add parameterized POSIX/Windows/ADS/device/symlink path tests.

## 2. Core Runtime And Metadata

- [x] 2.1 Migrate `ArtifactManager`, `LocalArtifactPublisher`, `LocalArtifactStore`, and `FilesystemArtifactStore` to the shared boundary before filesystem access.
- [x] 2.2 Add fixed publisher and artifact-step reserved metadata sets; fail conflicts without file, ref, manifest, index, or buffer side effects.
- [x] 2.3 Preserve valid nested paths, `_records`, custom metadata, redaction, and publisher recover/status behavior.

## 3. Reference Contracts

- [x] 3.1 Make `ArtifactReference` constructor/from_dict share required string, alias, and optional run-id validation without rejecting remote URIs.
- [x] 3.2 Tighten only `ArtifactRef.from_dict()` required fields and path/uri aliases while preserving valid roundtrip and constructor compatibility.
- [x] 3.3 Update `ArtifactValidator` to reuse segment validation without applying local-path rules to general URIs.

## 4. Workflow, Tool, And Interface Bypasses

- [x] 4.1 Migrate workflow manifest, execution, artifact publishing/indexing, checkpoint recovery, operations, and inspection path resolution to the shared boundary.
- [x] 4.2 Migrate builtin artifact load/search/write and storage/run/artifact service filesystem paths to the shared boundary.
- [x] 4.3 Preserve API 400 vs 404 semantics, CLI nonzero failures, and MCP failure envelopes for unsafe input.

## 5. Regression And Gates

- [x] 5.1 Add core artifact, workflow artifact-step, builtin tool, checkpoint/index, service, API, CLI, and MCP adversarial regressions with no-side-effect assertions.
- [x] 5.2 Run `openspec validate artifact-runtime-boundary-hardening --strict` and all Change 1 targeted tests.
- [ ] 5.3 Run `python -m scripts.dev compile`, `python -m scripts.dev smoke`, `openspec validate --all --strict`, and `git diff --check`.
