## ADDED Requirements

### Requirement: HTML connector normalizes canonical URLs
The system SHALL normalize extracted HTML canonical URLs before emitting raw
source items.

#### Scenario: Relative canonical URL is resolved and normalized
- **WHEN** an HTML page has `<link rel="canonical" href="/blog/post?utm_source=x">`
  and source URL `https://Example.com/blog/index.html`
- **THEN** the raw source item URL is `https://example.com/blog/post`
