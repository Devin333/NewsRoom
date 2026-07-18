## Design

`SourceArtifactWriter` already writes request and result artifacts before source
error artifacts. This change records the generated request/result `ArtifactRef`
objects in local lookups keyed by both `request_id` and `source_id`.

For each source error, the writer resolves refs in this order:

1. an explicit `request_ref` or `response_ref` already present on the error,
2. `metadata.request_id` when present,
3. the single matching request/result for the same `source_id`.

The resolved refs are written into the serialized error payload and copied to
the source artifact index entry as `request_ref` and `response_ref`.

The daily runner annotates connector errors with the fetch `request_id` before
recording `source_errors` and `failed_sources`. This keeps top-level
`source_errors.json` joinable even though the full artifact refs are created
later by the artifact writer.

## Compatibility

The new fields are additive. Existing callers that read source errors or source
artifact index entries without request/result refs continue to work. Errors
without a matching request/result, such as aggregate `all_sources_failed`,
remain valid and omit the unresolved refs.
