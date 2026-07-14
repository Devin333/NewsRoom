## Context

Stage 18 established shared path, metadata, and checksum contracts and marked service-facing replay as strict. The live implementation verifies each manifest-listed file in `WorkflowRunInspector.build_replay_content_bundle()`, discards the verified bytes, and then reopens the same paths through non-strict event, artifact, index, and step-result readers. A temporary-directory adversarial reproduction replaced `output.json` after preflight and strict replay returned the replacement bytes successfully.

The completion audit also showed that strict replay ignores `validate_run_dir().valid`, expands checksum-bearing source artifact index entries through a non-strict reader, and accepts test manifests that do not satisfy `validate_run_manifest()`. Separately, `LocalArtifactStore.get()` treats a directory at an object or metadata file path as an untyped OS error, `LocalArtifactStore.list()` coerces persisted null required fields to the literal string `"None"`, `LocalArtifactPublisher._artifact_path()` coerces a non-string legacy metadata run id before validation, and artifact detail retains one direct `artifact_root / run_id` fallback even though its normal caller validates the run id.

The implementation must preserve non-strict workflow diagnostics, the exact `manifest` checksum sentinel `"pending"`, valid JSON/text/binary/redaction behavior, existing HTTP/CLI/MCP error envelopes, and the no-lock/no-signature scope of stage 18.

## Goals / Non-Goals

**Goals:**

- Make every byte returned by strict replay come from the same immutable byte snapshot that passed checksum verification.
- Complete all manifest and selected artifact-index entry checks before decoding, redacting, or constructing any replay content.
- Reject invalid canonical run manifests in direct artifact detail and replay, and reject invalid index integrity metadata with stable shared typed errors.
- Classify stable non-regular local-store object/metadata paths as corrupt persisted state.
- Reject invalid persisted required reference fields and non-string legacy run identifiers before string coercion.
- Remove the last direct run-directory join in artifact detail inspection.
- Fulfil the stage 18 structured observability contract without adding a metrics dependency.
- Preserve non-strict diagnostic behavior and adapter error contracts.

**Non-Goals:**

- Adding cross-process locks, filesystem transactions, signatures, encryption, ACLs, or external manifest digests.
- Verifying arbitrary run files that are neither manifest-listed nor referenced by the selected artifact index.
- Converging the repository's artifact reference/store models.
- Ending the legacy `LocalArtifactStore` missing-checksum compatibility window.
- Changing normal non-strict diagnostics into fail-fast product APIs.

## Decisions

### Strict replay owns an immutable verified snapshot

Introduce one internal frozen snapshot model carrying artifact key, canonical relative and absolute paths, content type, validated metadata, and raw bytes. The strict reader returns this snapshot after path, metadata, file-kind, size, and checksum checks. Direct artifact detail converts one snapshot to a content record.

Strict replay first captures and validates the canonical manifest, then captures every manifest-listed artifact. It retains the raw bytes instead of discarding them. Only after all required snapshots exist does replay decode JSON/JSONL/text/binary content, redact values, build event records, derive step results, or construct response models.

The manifest artifact continues to require the exact `"pending"` checksum sentinel and valid path/metadata shape, but its snapshot is the same byte sequence used to parse the replay manifest. This provides internal replay consistency without claiming cryptographic authenticity.

Alternatives rejected: performing a second strict read after preflight prevents returning unchecked bytes but doubles I/O and still produces a replay assembled from different filesystem moments; adding locks exceeds the stage 18 scope.

### Strict projections consume bytes, never paths

Add byte-based helpers for event JSONL parsing, JSON decoding, content preview/redaction, and artifact-index parsing. In strict mode, events, step results, manifest-listed artifact records, and index selection consume the verified snapshot map. No strict post-preflight code calls `Path.read_*`, `_read_json_file()`, `read_events()`, `read_json_artifact()`, or `read_workflow_artifact_content()`.

Non-strict mode keeps the existing path-based functions and tolerant `read_error` behavior unchanged.

### Verified indexes form a transitive checksum boundary

A manifest-listed artifact index is trusted only after its own manifest checksum verifies. Strict replay then parses that snapshot and requires every expanded entry to provide a valid checksum, using the top-level `checksum` field with the embedded `artifact_ref.checksum` as compatibility fallback. If both declarations exist, they must agree. Integrity identity, path, serialized content type, and size use the nested `artifact_ref` as the canonical declaration when present; duplicated top-level integrity fields must agree, except explicitly documented business projections that reuse a top-level name. In particular, `source_response_headers` currently uses top-level `content_type` for the source HTTP response while `artifact_ref.content_type` describes the persisted JSON file, so replay must not treat that business field as the file MIME type. Path, optional serialized content type, optional size, and duplicated projected keys are validated before any entry content is decoded.

All referenced entry files are captured and verified as a second preflight set. Any missing file, invalid metadata, or checksum mismatch fails replay as a whole. Expanded records are created from those entry snapshots. Non-strict index expansion remains tolerant for forensic diagnostics.

### Canonical manifest validation precedes content verification

Direct strict artifact detail and strict replay call `validate_run_manifest(..., require_terminal_artifact=True)` before snapshot expansion. `RunManifestError` is wrapped as `ArtifactStoreMetadataError` because the failure describes corrupt persisted run metadata, not invalid HTTP input. Missing files still surface as `ArtifactNotFoundError`, and checksum mismatches retain `ArtifactChecksumMismatchError`.

This intentionally rejects invalid historical manifests in service-facing replay. Non-strict inspection remains the migration and forensic path.

`RunInspectionService.replay_run()` must not load and normalize the manifest before invoking strict replay, because that creates a second manifest read and a split validation owner. After validating the run directory and missing-run condition, it delegates manifest byte capture, parsing, canonical validation, artifact path validation, and integrity preflight to `WorkflowRunInspector.build_replay_content_bundle(strict_artifact_integrity=True)`.

The concrete run-replay and artifact-detail services do not accept or construct an artifact store, so their real filesystem paths cannot produce `ArtifactStoreRequiredError`. End-to-end HTTP regressions therefore prove the upstream 400, 404, and 409 outcomes those services can actually originate. The existing 500 `artifact_store_unavailable` contract remains covered at the router mapping boundary with an injected failing service; that test is adapter-isolation evidence only and is never counted as proof that these filesystem services produced the failure.

### Local-store pair classification includes file kind

After resolving both canonical paths, `LocalArtifactStore.get()` distinguishes absence from non-regular persisted nodes. A stable directory or other non-file node at either object or metadata location raises `ArtifactStoreMetadataError` before JSON or byte reads. Ordinary ACL/permission failures for regular files remain underlying operational errors rather than being mislabeled as corrupt data.

`LocalArtifactStore.list()` loads each metadata record through the same required-string, file-kind, checksum-declaration, and metadata-shape rules used by `get()` or a shared equivalent. Missing, null, blank, whitespace-padded, or non-string `artifact_id` and `uri` values, malformed JSON, and non-regular metadata/object nodes raise `ArtifactStoreMetadataError`; the listing path never calls `str()` to manufacture persisted identity and never returns a partial listing after corruption is found. Listing does not read every object merely to recompute content checksums; callers that require byte verification use `get()` or an integrity inspector.

### Legacy workflow-reference run ids preserve type safety

`LocalArtifactPublisher._artifact_path()` validates the raw optional `metadata["run_id"]` value before any conversion. A present value must already be a `str` and satisfy the shared segment boundary. Numeric, boolean, collection, and object values raise `ArtifactPathError`; valid historical string run ids remain supported.

### Artifact detail fallback uses the shared boundary

Replace the direct `artifact_root / run_id` expression with the same validated segment plus canonical descendant helper used by artifact listing. The normal `RunInspectionService.get_run()` result remains preferred, while a missing `artifact_dir` cannot create a new path algorithm.

### Structured events are the observability implementation

Add a small dependency-free artifact observability helper over Python logging. It emits a stable event name and a flat, allow-listed dimension mapping; it never serializes artifact content, raw metadata values, filesystem bytes, tokens, or exception tracebacks.

Instrument the deterministic ownership boundaries once per outcome:

- path helper rejection -> `artifact_path_rejected_total` with `field` and `operation`;
- publisher/artifact-step reserved-key rejection -> `artifact_reserved_metadata_rejected_total` with `key` and `publisher`;
- shared checksum mismatch -> `artifact_checksum_mismatch_total` with `store` and `operation`;
- caught typed store/workflow metadata corruption -> `artifact_metadata_corrupt_total` with `store`;
- legacy or strict missing checksum detection -> `artifact_checksum_missing_total` with `store`;
- generic integrity inspection completion/configuration failure -> `artifact_integrity_inspection_total` with `result`.

Failure events use warning level; successful inspection outcomes use info. Tests assert event name/dimensions and prove sensitive content is absent. A future metrics sink can translate these stable events without changing artifact logic.

## Risks / Trade-offs

- [Strict replay retains raw bytes until response construction] -> Replay already materializes the same content; snapshots remove duplicate reads and are bounded by existing replay memory behavior. Large-artifact streaming remains a later measured optimization.
- [Invalid legacy manifests and checksum-less index entries stop replaying] -> This is the intended fail-closed service contract; retain non-strict diagnostics and require explicit offline migration or regeneration.
- [The manifest has no external digest] -> Preserve the explicit `"pending"` exception and avoid claiming authenticity; external signatures remain out of scope.
- [Files can change after snapshot capture] -> Returned content remains the verified snapshot, so later disk changes cannot alter this response. A future replay observes and verifies the newer state.
- [Index entries may contain inconsistent top-level and nested refs] -> Reject conflicts as metadata corruption rather than choosing silently.
- [Logging security failures can leak attacker-controlled values] -> Emit only fixed event names and normalized dimension labels; never log paths, metadata values, content, or raw exception text.

## Migration Plan

1. Add failing adversarial tests for TOCTOU replacement, invalid manifest schema, index-entry mismatch/missing checksum, non-file local-store states, null list metadata, non-string legacy run ids, and the residual path fallback.
2. Introduce the internal snapshot and byte-decoding helpers without changing non-strict callers.
3. Route strict replay and service-facing replay projections through the complete snapshot preflight.
4. Tighten local-store file-kind classification and artifact detail fallback resolution.
5. Add structured artifact observability events and no-secret regressions.
6. Update API/CLI/MCP regressions and stage 18 documentation.
7. Run targeted tests, compile, smoke, strict OpenSpec validation, and `git diff --check`; commit and archive the completion change.
8. Roll back the change as one unit if valid canonical runs fail; never roll back by re-enabling unchecked post-preflight reads.

## Open Questions

None. External manifest authenticity and streaming verified replay require separate proposals with deployment and performance evidence.
