## MODIFIED Requirements

### Requirement: HTML connector normalizes canonical URLs
The system SHALL delegate extracted HTML canonical URLs to the business-owned
Source URL identity contract before emitting raw source items. The infrastructure
adapter SHALL NOT maintain a second canonicalization algorithm or a behaviorally
different fallback.

#### Scenario: Relative canonical URL is resolved and normalized
- **WHEN** an HTML page has `<link rel="canonical" href="/blog/post?utm_source=x">`
  and source URL `https://Example.com/blog/index.html`
- **THEN** the raw source item URL is `https://example.com/blog/post`

#### Scenario: HTML and business normalization agree
- **WHEN** the same absolute or relative URL and base URL are processed by the
  HTML connector, Source tool, and business normalizer
- **THEN** all three entry points emit the same canonical URL

#### Scenario: Invalid HTML canonical is rejected
- **WHEN** an extracted HTML canonical is a malformed absolute URL or remains
  unresolved after applying the page URL as its base
- **THEN** the connector returns a structured parse SourceError
- **AND** it emits no raw source item with an invented identity
