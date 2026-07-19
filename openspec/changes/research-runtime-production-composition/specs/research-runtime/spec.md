## MODIFIED Requirements

### Requirement: Research Production Data Sources
Production Research code SHALL use real data sources, real domain models, real bounded runtime paths, integrity-protected artifacts, and durable run records. Configured default HTTP and MCP entrypoints MUST compose `ResearchSinglePaperRuntime` with concrete production adapters and MUST NOT select an unconfigured use case, fake LLM/repository/reader/artifact adapter, legacy paper-radar dependency, or in-memory-only run store. Tests MAY replace external transports, use recorded responses, and use fakes in explicit unit-test composition to reduce development cost.

#### Scenario: Test fake does not leak into production service
- **WHEN** production Research service composition is inspected
- **THEN** fake LLM, fake repository, fixture-only readers, fake artifact ports, and in-memory run storage MUST NOT be the default production dependencies

#### Scenario: Configured default entrypoint analyzes a paper
- **WHEN** valid production settings and accepted source/LLM responses are available
- **THEN** the default HTTP and MCP analysis paths execute the real Harness-controlled Research runtime
- **AND** return durable result, quality, trace, and artifact references

#### Scenario: Required production capability is unavailable
- **WHEN** the real runtime cannot be composed because a required setting or adapter capability is absent
- **THEN** execution fails with a stable sanitized typed unavailable error
- **AND** the system does not silently substitute fake data, an in-memory-only implementation, or an unverified compatibility path
