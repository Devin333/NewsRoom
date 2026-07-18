# source-canonical-url-default-port Specification

## Purpose
TBD - created by archiving change source-canonical-url-default-port. Update Purpose after archive.
## Requirements
### Requirement: Canonical URL removes default ports
The system SHALL remove default HTTP and HTTPS ports during source URL
canonicalization.

#### Scenario: HTTPS default port is removed
- **WHEN** canonicalizing `https://Example.com:443/post`
- **THEN** the canonical URL is `https://example.com/post`

#### Scenario: HTTP default port is removed
- **WHEN** canonicalizing `http://Example.com:80/post`
- **THEN** the canonical URL is `http://example.com/post`

#### Scenario: Non-default port is preserved
- **WHEN** canonicalizing `https://Example.com:8443/post`
- **THEN** the canonical URL is `https://example.com:8443/post`
