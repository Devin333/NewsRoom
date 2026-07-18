## MODIFIED Requirements

### Requirement: Canonical URL removes default ports
The system SHALL use the business-owned Source URL identity contract to remove
default HTTP and HTTPS ports for every new Source URL identity emitted by
business normalization, Source tools, SourceRef projections, and infrastructure
Source adapters.

#### Scenario: HTTPS default port is removed
- **WHEN** any Source entry point canonicalizes `https://Example.com:443/post`
- **THEN** the canonical URL is `https://example.com/post`

#### Scenario: HTTP default port is removed
- **WHEN** any Source entry point canonicalizes `http://Example.com:80/post`
- **THEN** the canonical URL is `http://example.com/post`

#### Scenario: Non-default port is preserved
- **WHEN** any Source entry point canonicalizes `https://Example.com:8443/post`
- **THEN** the canonical URL is `https://example.com:8443/post`

#### Scenario: IPv6 host keeps valid brackets
- **WHEN** any Source entry point canonicalizes `https://[2001:DB8::1]:443/post`
- **THEN** the canonical URL is `https://[2001:db8::1]/post`
