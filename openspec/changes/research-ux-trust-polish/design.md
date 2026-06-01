## Decisions

- Product status copy should describe the available data, not the failed dependency. A cache or artifact fallback is presented as verified fallback data with source and update time.
- Task and method canonicalization is applied at ref normalization time so list pages, detail routes, and paper filters share the same visible taxonomy.
- Signal filters are URL-backed and use the already loaded dashboard paper window for consistent counts and pagination.
- PDF thumbnails are treated as progressive enhancement. The first few visible rows can render real PDF previews; later rows use a stable placeholder until deeper lazy loading is introduced.
- Anonymous users should not see broken personal-state controls. Reading-list style actions remain a future authenticated workflow rather than a local fake state.

## Non-Goals

- No synthetic taxonomy, paper, benchmark, or user-state data.
- No backend route renames.
- No new authenticated personal workflow in this change.
