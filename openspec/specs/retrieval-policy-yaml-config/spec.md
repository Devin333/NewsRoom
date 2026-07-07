# retrieval-policy-yaml-config Specification

## Purpose
TBD - created by archiving change retrieval-policy-yaml-config. Update Purpose after archive.
## Requirements
### Requirement: Retrieval policy can be loaded from YAML or JSON config
The Research RAG retrieval layer SHALL support constructing an effective `RetrievalPolicy` from a local YAML or JSON config file.

#### Scenario: YAML config overrides a named base policy
- **WHEN** a policy config file declares `base_policy: paper_hybrid_rrf_rag_v1` and override values
- **THEN** the constructed policy SHALL inherit the named base policy values
- **AND** the configured override values SHALL be applied to the effective `RetrievalPolicy`

#### Scenario: JSON config is accepted
- **WHEN** a policy config file with suffix `.json` is loaded
- **THEN** the constructed policy SHALL apply the same schema as YAML config files

### Requirement: Retrieval policy config is validated before use
Retrieval policy config loading SHALL reject malformed config before constructing a policy.

#### Scenario: Unknown override is rejected
- **WHEN** a policy config override contains a key that is not a `RetrievalPolicy` field
- **THEN** policy loading SHALL raise a validation error that names the unknown field

#### Scenario: Invalid root shape is rejected
- **WHEN** a policy config file root is not an object
- **THEN** policy loading SHALL raise a validation error before returning a policy

### Requirement: Production policy env can point to a config file
The production paper RAG composition path SHALL read a retrieval policy config path from the environment.

#### Scenario: Env config path is set
- **WHEN** `build_retrieval_policy_from_env()` receives `NEWS_PAPER_RAG_POLICY_CONFIG`
- **THEN** it SHALL load the effective policy from that file
- **AND** `NEWS_PAPER_RAG_POLICY` SHALL remain available as the fallback base policy when the file omits `base_policy`

#### Scenario: Env config path is absent
- **WHEN** `NEWS_PAPER_RAG_POLICY_CONFIG` is absent
- **THEN** `build_retrieval_policy_from_env()` SHALL preserve the existing named-policy behavior

### Requirement: Configured policies remain hashable
Configured retrieval policies SHALL participate in existing retrieval policy hash metadata.

#### Scenario: Config override changes hash
- **WHEN** a configured policy changes a tunable field
- **THEN** `policy_config_hash()` SHALL differ from the base named policy hash
