## ADDED Requirements

### Requirement: Default Source runtime composition shares fetch policy state
The default API, MCP, worker, CLI-command, and Source-tool composition roots MUST
construct Source fetch policy components through one explicit Source runtime
composition. Within one process or command lifetime, connectors, Source tools,
Source health probes, and Research arXiv source-package/PDF adapters MUST share
one underlying reservation ledger and MUST NOT obtain state from an implicit
module-level singleton.

#### Scenario: Connector tool and health probe share quota
- **GIVEN** a default Source runtime composition with
  `rate_limit_per_domain_per_minute = 2`
- **WHEN** a connector and a Source tool reserve the two available requests for
  one domain
- **THEN** a health probe for that domain is denied before network access

#### Scenario: Stable transport factories retain limiter state
- **WHEN** two API or MCP calls use the default Source service factory in the
  same process
- **THEN** both calls observe the same Source runtime limiter state

#### Scenario: Explicit standalone connector remains isolated
- **WHEN** a test or adapter explicitly constructs a standalone connector with
  its own injected limiter
- **THEN** that limiter is isolated from the default production composition
- **AND** the connector still uses the canonical infrastructure limiter
  implementation

#### Scenario: Research arXiv package fetch shares Source quota
- **GIVEN** default Research and Source services run in the same process
- **AND** a Source connector consumed the remaining reservation for `arxiv.org`
- **WHEN** Research requests an arXiv source package or PDF
- **THEN** the Research adapter receives a typed rate-limit denial before network
  access
- **AND** the denial carries the canonical domain and retry-after decision

## MODIFIED Requirements

### Requirement: Default source assembly enforces domain rate limits across connectors

Source Pipeline runtime assembly MUST use the same injected infrastructure domain
reservation ledger for all default-owned connectors so Source rate limits apply
across connector classes and no connector silently constructs a production-local
bucket.

#### Scenario: RSS and HTML share a domain

- **GIVEN** a fetch policy with `rate_limit_per_domain_per_minute = 1`
- **AND** an RSS source and an HTML source use the same domain
- **WHEN** `SourceApplicationService` batch collection fetches both through its
  default connector router
- **THEN** the first source can fetch
- **AND** the second source is returned as `rate_limited` before network fetch.

### Requirement: Source Health Probes Respect Rate Limits

Source health probe execution SHALL reserve the same underlying domain ledger
used by default connectors and Source tools before external network access.

#### Scenario: Two health probes target the same limited domain

- **GIVEN** a source health checker with `rate_limit_per_domain_per_minute` set to `1`
- **AND** two enabled sources on the same domain
- **WHEN** a health check run evaluates both sources
- **THEN** the first probe may fetch
- **AND** the second probe SHALL be skipped before network access with a `rate_limited` diagnostic
- **AND** the skipped probe SHALL NOT increment source failure counts.

#### Scenario: Connector reservation is visible to health probe
- **GIVEN** a default Source composition whose connector consumed the remaining
  reservation for a domain
- **WHEN** the health checker probes the same domain
- **THEN** the probe is skipped as `rate_limited` before network access
- **AND** the source health failure count is unchanged
