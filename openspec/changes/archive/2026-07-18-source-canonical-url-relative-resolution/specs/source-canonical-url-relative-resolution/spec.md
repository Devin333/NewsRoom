## ADDED Requirements

### Requirement: Canonical URL resolves relative URLs with a base URL
The system SHALL resolve relative source URLs against an explicit base URL before
applying canonicalization.

#### Scenario: Root-relative URL is resolved
- **WHEN** canonicalizing `/post?utm_source=x` with base URL
  `https://Example.com/blog/index.html`
- **THEN** the canonical URL is `https://example.com/post`

#### Scenario: Path-relative URL is resolved
- **WHEN** canonicalizing `post` with base URL `https://example.com/blog/`
- **THEN** the canonical URL is `https://example.com/blog/post`

#### Scenario: No base URL preserves current behavior
- **WHEN** canonicalizing an absolute URL without a base URL
- **THEN** existing canonicalization behavior is unchanged
