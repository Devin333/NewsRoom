## Context

NewsRoom has two local artifact layouts. `LocalArtifactStore` stores an object under `objects/` plus JSON metadata under `.metadata/`, while `FilesystemArtifactStore` stores workflow-owned bytes under a run directory and carries the expected checksum in `ArtifactRef`. The filesystem store already verifies a supplied checksum, but its exception type is implementation-owned. The default local store returns content without validating metadata or bytes, and its direct writes can leave a visible half-pair.

Two inspection layers also exist. `framework.artifacts.inspection.ArtifactIntegrityInspector` verifies generic `ArtifactManifest` references through an `ArtifactStore`, while `framework.workflow.inspection.WorkflowRunInspector` reads manifest-listed run files directly. Service-facing artifact detail and replay currently use the second path, so fixing only `LocalArtifactStore.get()` would leave HTTP, CLI, and MCP reads able to return tampered run files.

The implementation depends on the path boundary established by `artifact-runtime-boundary-hardening`. It must preserve existing non-strict diagnostic behavior, remote reference representation, valid JSON/text/binary reads, redaction, and the workflow manifest self-checksum sentinel `"pending"`.

## Goals / Non-Goals

**Goals:**

- Give local stores and inspectors one public exception vocabulary for missing content, checksum mismatch, and corrupt metadata.
- Ensure a successful local-store read means persisted metadata and bytes were actually checked.
- Prevent ordinary write interruption from publishing truncated metadata or a new metadata commit marker for an incomplete object.
- Make `checked_count` describe real verification attempts and prevent non-empty no-store inspection from reporting success.
- Make direct artifact detail and service-facing replay verify checksum metadata before any artifact content is returned.
- Preserve adapter-specific HTTP, CLI, MCP, and MCP-over-HTTP failure contracts.

**Non-Goals:**

- Converging `ArtifactReference`, `ArtifactRef`, and `WorkflowArtifactRef` into one model.
- Converging `LocalArtifactStore` and `FilesystemArtifactStore` into one layout.
- Adding signatures, encryption, ACLs, remote object storage, cross-process locks, or a cross-file transaction.
- Requiring legacy local-store records without checksum to be migrated or rewritten during reads.
- Changing the existing non-strict workflow diagnostics default into a fail-fast product API.

## Decisions

### Shared store exceptions own integrity failure classification

Add `framework/artifacts/stores/errors.py` with `ArtifactNotFoundError`, `ArtifactChecksumMismatchError`, and `ArtifactStoreMetadataError`. Both local stores and workflow strict inspection import these classes, while `framework.artifacts` and `framework.artifacts.stores` preserve public imports. `ArtifactStoreRequiredError` belongs to generic inspection because it represents missing verification configuration rather than corrupt persisted state.

Alternatives rejected: importing exceptions from `filesystem.py` creates an implementation dependency; mapping every failure to `ValueError` makes adapters unable to distinguish input, conflict, and configuration failures.

### Metadata is the local-store commit marker

`LocalArtifactStore.put()` validates the artifact identifier and prepares object and metadata bytes before touching the filesystem. It writes uniquely named temporary files in their destination directories, closes them, replaces the object, and replaces metadata last. A `finally` block removes only temporary files owned by that call.

This is intentionally not a cross-file transaction. If failure occurs after object replacement but before metadata replacement, readers either observe the prior metadata with a checksum mismatch or a metadata-missing orphan; they never treat the new bytes as a verified successful pair. Metadata-last provides a deterministic commit boundary without introducing a lock service.

### Reads classify every pair state before constructing an Artifact

`LocalArtifactStore.get()` resolves both paths, then handles: both absent as `None`; metadata-only as `ArtifactNotFoundError`; object-only as `ArtifactStoreMetadataError`; malformed or structurally invalid metadata as `ArtifactStoreMetadataError`. It reads object bytes once, validates a lowercase 64-character SHA-256 when present, and raises `ArtifactChecksumMismatchError` on a valid-but-wrong digest.

Legacy metadata without checksum remains readable for one compatibility window. The store overwrites any persisted `_artifact_integrity` claim and returns `metadata["_artifact_integrity"] = "checksum_missing"`. New writes always include a checksum. No read path rewrites legacy data.

### Generic integrity inspection is fail-fast only for missing configuration

An empty manifest has nothing to verify and returns `valid=True, checked_count=0`. A non-empty manifest without a constructor or call-time store raises `ArtifactStoreRequiredError`. For each reference with a store, missing, mismatch, corrupt metadata, and legacy checksum-missing are classified as issues and counted as attempted checks; unknown exceptions propagate. `valid=True` requires every reference to have been checked with no issue.

### Workflow strict reads validate before decoding or redaction

Add a shared strict workflow artifact read helper in `framework.workflow.inspection.inspector`. It resolves the manifest path through the shared path boundary, locates expected metadata from `artifact_metadata` with a `step_artifacts` compatibility fallback, validates checksum format, reads bytes once, compares SHA-256, and only then decodes/redacts.

`ArtifactInspectionService.get_artifact()` delegates to this helper. `WorkflowRunInspector.build_replay_content_bundle()` gains `strict_artifact_integrity=False`; when true it preflights every manifest-listed artifact before expanding any content. `RunInspectionService.replay_run()` always passes true. Missing checksum in strict workflow reads is `ArtifactStoreMetadataError`, not the local-store legacy compatibility marker, because workflow publication already records checksum metadata.

The artifact key `manifest` is excluded only from checksum comparison because its in-document checksum is the sentinel `"pending"`. Its path and metadata shape remain validated. All other artifacts must carry a normal SHA-256 digest.

### Adapter mappings are explicit and ordered before broad base classes

Path errors remain HTTP 400. `ArtifactChecksumMismatchError` and `ArtifactStoreMetadataError` map to HTTP 409, while `ArtifactStoreRequiredError` maps to HTTP 500. CLI typed failures write only a safe message to stderr and return `1`. MCP application service retains `success=False` plus `type(exc).__name__`; MCP HTTP converts those failed results to the same outer HTTP failure envelope. Typed exceptions must be caught before their `ValueError`, `FileNotFoundError`, or `RuntimeError` base classes.

## Risks / Trade-offs

- [Object replacement succeeds but metadata replacement fails] -> Metadata remains the commit marker; the next read deterministically reports mismatch or corrupt half-state, and fault-injection tests cover the ordering.
- [Legacy missing checksums hide historical tampering] -> Reads are temporarily permitted only with an unverified marker; integrity inspection and all strict workflow interface reads fail closed.
- [Strict replay adds hashing work] -> Replay already reads artifact bytes; preflight adds SHA-256 computation and prevents partial content disclosure. Streaming optimization is deferred until measurement justifies it.
- [Workflow manifests from older runs lack artifact metadata] -> Service-facing strict read reports `ArtifactStoreMetadataError`; non-strict diagnostics remain available for forensic inspection.
- [Manifest checksum cannot be self-verifying] -> Exclude exactly artifact key `manifest` and preserve `"pending"`; external signatures/digests remain a future capability.
- [New typed errors change adapter behavior] -> Stable mappings and regression tests cover service, API, CLI, MCP application, stdio, and MCP HTTP surfaces.

## Migration Plan

1. Introduce and export shared exceptions without changing behavior.
2. Harden `LocalArtifactStore` pair writes/reads and generic integrity inspection with focused fault-injection and tamper tests.
3. Add strict workflow read/preflight helpers and integrate artifact detail and replay services.
4. Add API, CLI, MCP, and MCP HTTP error-contract regressions.
5. Run targeted tests, compile, smoke, strict OpenSpec validation, and deployment-root legacy checksum census.
6. Roll back the integrity change as one unit if valid newly written artifacts fail verification; never roll back by swallowing typed failures or disabling strict service reads.

## Open Questions

None. Ending the legacy missing-checksum compatibility window and adding external manifest signatures require separate changes with deployment data migration evidence.
