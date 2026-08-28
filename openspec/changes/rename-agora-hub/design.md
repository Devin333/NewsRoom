## Context

The repository currently exposes `NewsRoom` through documentation, two browser applications, API/OpenAPI metadata, MCP metadata, CLI descriptions, package manifests, and outbound user-agent strings. The same word also appears in durable paths, environment variables, SDK symbols, cookies, schemas, event types, and test fixtures. Those two groups have different migration costs: public branding can change atomically, while compatibility identifiers require a versioned migration and a deprecation period.

The target product identity is `Agora Hub`, representing one site for news, research papers, and projects. GitHub repository names cannot contain spaces, so the canonical repository and package slug is `agora-hub` (GitHub display casing: `Agora-Hub`).

## Goals / Non-Goals

**Goals:**

- Present `Agora Hub` consistently across current user-facing and operator-facing surfaces.
- Align GitHub and distributable package metadata with the new identity.
- Keep existing runtime data, deployments, replay, and SDK clients working.
- Make the rename testable through focused contract and UI assertions.

**Non-Goals:**

- Renaming Python classes, imports, CLI executable names, environment variables, cookies, event/schema identifiers, database names, or `.newsroom` storage paths.
- Rewriting archived OpenSpec changes, historical design records, fixtures, or migration evidence that correctly describe the former name.
- Renaming the local workspace directory while it is mounted by the current development environment.

## Decisions

### Separate public identity from compatibility identifiers

Public prose, UI labels, protocol metadata, package metadata, and outbound user-agent product tokens will use the new brand. Existing machine-readable identifiers remain unchanged in this change. This avoids invalidating persisted data, deployment configuration, imports, and durable replay merely to remove the former word from source text.

The rejected alternative is a repository-wide case-insensitive replacement. It would silently change stable contracts such as `NEWSROOM_*`, `.newsroom`, `newsroom_sdk`, and `io.newsroom.*` without providing dual-read or migration support.

### Use platform-safe slugs where spaces are not allowed

Human-facing text uses `Agora Hub`. GitHub uses `Agora-Hub`; Python and JavaScript distribution metadata use lowercase hyphenated `agora-hub` names. Protocol user-agent tokens use `AgoraHub` because spaces delimit user-agent products.

### Verify behavior at public boundaries

Existing API, MCP, CLI, and frontend tests will assert the new labels. A focused source audit will distinguish current public surfaces from explicit compatibility and historical files. Generated OpenAPI documentation will be refreshed from the runtime schema rather than edited independently when a generator is available.

### Rename GitHub after local verification

The local change is implemented and verified before the external repository rename. GitHub is then renamed, `origin` is updated to the canonical SSH URL, and the commit is pushed to the renamed repository. GitHub's redirect remains a transition aid, not the canonical configured URL.

## Risks / Trade-offs

- [Some external automation still targets the old repository URL] -> GitHub redirect provides continuity; the local remote and repository documentation use the canonical URL after rename.
- [Changing Python distribution metadata affects installation commands] -> Treat the distribution rename as breaking while preserving Python imports and public SDK symbols.
- [The former name remains in compatibility contracts] -> Document that boundary explicitly and defer any namespace migration to a separate versioned change.
- [Historical documents contain the former name] -> Keep historical truth intact and exclude archived material from current-brand conformance claims.

## Migration Plan

1. Update OpenSpec artifacts and validate the change.
2. Update current product surfaces, package metadata, generated API schema, and corresponding tests.
3. Run focused backend/frontend checks and the required full smoke gate.
4. Commit the verified repository change.
5. Rename GitHub to `Devin333/Agora-Hub`, update `origin`, push the commit, and verify the repository metadata and default branch.

Rollback consists of renaming the GitHub repository back, restoring the prior remote URL, and reverting the branding commit. Compatibility identifiers do not require data rollback because they are not changed.

## Open Questions

None.
