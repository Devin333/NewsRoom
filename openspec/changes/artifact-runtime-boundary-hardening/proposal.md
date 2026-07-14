## Why

Artifact runtime paths currently trust caller-controlled `run_id`, identifiers, relative paths, and metadata at multiple filesystem boundaries. This allows writes outside the configured artifact root, permits caller metadata to forge infrastructure-owned identity, and lets malformed serialized references survive until unrelated file access.

## What Changes

- Add one shared artifact path boundary for single-segment identifiers, relative artifact paths, and canonical descendant resolution.
- Apply that boundary to artifact managers, publishers, stores, workflow/checkpoint/index paths, builtin artifact tools, and interface services before filesystem side effects.
- Reject caller metadata that conflicts with publisher- or artifact-step-owned identity, location, integrity, lifecycle, or redaction fields.
- Tighten `ArtifactReference` construction/deserialization and `ArtifactRef.from_dict()` so missing, blank, or conflicting aliases cannot become the string `"None"`.
- Preserve remote URI support in the general reference model; local path restrictions apply only at local filesystem boundaries.
- Add adversarial Windows/POSIX traversal, symlink/junction containment, metadata-conflict, reference, workflow, API, CLI, and MCP tests.

## Capabilities

### New Capabilities

- `artifact-runtime-boundary`: Defines the shared path, trusted metadata, and serialized-reference boundary for local artifact runtime access.

### Modified Capabilities

- `artifact-store-index`: Requires filesystem artifact stores and storage references to reject unsafe local identifiers and paths without weakening remote reference semantics.
- `artifact-inspection-interface`: Requires manifest-listed artifact inspection entry points to reject unsafe run identifiers and artifact paths before reading files.
- `workflow-storage-indexing`: Requires workflow artifact indexing and checkpoint recovery to resolve manifest paths through the shared artifact boundary.
- `tool-builtin-artifact-tools`: Requires artifact write/load to use canonical descendant resolution for all local paths.
- `tool-builtin-artifact-search`: Requires artifact search to validate the run identifier and path prefix before scanning.

## Impact

- Core: `framework/artifacts`, workflow runtime/inspection/checkpoint paths, and builtin artifact tools.
- Interfaces: artifact/run services, run operations, storage diagnostics, API/CLI/MCP adapters.
- Compatibility: valid UUID/run identifiers, nested relative paths, non-reserved metadata, and remote `ArtifactReference` URIs remain supported; unsafe or ambiguous inputs intentionally fail earlier.
- Dependencies: no new third-party runtime dependency.
