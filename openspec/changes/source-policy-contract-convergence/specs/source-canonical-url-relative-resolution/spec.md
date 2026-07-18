## MODIFIED Requirements

### Requirement: Canonical URL resolves relative URLs with a base URL
The system SHALL resolve relative Source URLs against an explicit base URL before
applying the single business-owned canonical identity contract. The contract
SHALL trim inputs, lowercase scheme and host, remove fragments and tracking
parameters, normalize trailing path slashes, preserve duplicate non-tracking
query pairs, retain unresolved relative input without a base, and reject
malformed absolute URLs.

#### Scenario: Root-relative URL is resolved
- **WHEN** canonicalizing `/post?utm_source=x` with base URL
  `https://Example.com/blog/index.html`
- **THEN** the canonical URL is `https://example.com/post`

#### Scenario: Path-relative URL is resolved
- **WHEN** canonicalizing `post` with base URL `https://example.com/blog/`
- **THEN** the canonical URL is `https://example.com/blog/post`

#### Scenario: No base URL preserves absolute behavior
- **WHEN** canonicalizing `HTTPS://Example.com/News/?b=2&a=1#section` without a
  base URL
- **THEN** the canonical URL is `https://example.com/News?a=1&b=2`

#### Scenario: Tracking keys are removed case-insensitively
- **WHEN** canonicalizing
  `https://example.com/post?UTM_Source=x&FbClId=y&Topic=AI&Topic=ML`
- **THEN** the canonical URL is
  `https://example.com/post?Topic=AI&Topic=ML`

#### Scenario: Blank input stays blank
- **WHEN** canonicalizing an input containing only whitespace
- **THEN** the canonical URL is an empty string

#### Scenario: Relative input without a base is fail-preserving
- **WHEN** canonicalizing a relative value without a usable base URL
- **THEN** the result is the trimmed input rather than an invented absolute URL

#### Scenario: Malformed absolute input is rejected
- **WHEN** canonicalizing an absolute URL with an invalid port or IPv6 syntax
- **THEN** canonicalization raises a deterministic validation error
- **AND** no repaired identity is emitted

#### Scenario: Historical URL identity remains readable
- **GIVEN** a persisted Source, Research paper, repository, or paper-card record
  contains a URL emitted by either historical canonicalizer
- **WHEN** a read-side equality or lookup operation compares it with the new
  canonical form
- **THEN** the reader matches a documented historical alias
- **AND** the persisted URL, id, hash, and artifact refs are not rewritten
