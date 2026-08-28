## ADDED Requirements

### Requirement: Canonical public product name
The product SHALL present `Agora Hub` as its canonical human-facing name across current documentation, browser metadata and navigation, API/OpenAPI metadata, MCP metadata, CLI descriptions, and generated report attribution. Machine-token contexts that cannot contain spaces SHALL use the `AgoraHub` product token.

#### Scenario: User opens a primary product surface
- **WHEN** a user opens either current web application or reads a current entry document
- **THEN** the visible product identity is `Agora Hub` and does not identify the current product as `NewsRoom`

#### Scenario: Client inspects an operator protocol
- **WHEN** a client inspects API/OpenAPI, MCP, or CLI metadata
- **THEN** the protocol presents the product as `Agora Hub`

### Requirement: Canonical repository and package identity
The GitHub repository SHALL be named `Devin333/Agora-Hub`. Distributable metadata SHALL use an `agora-hub`-based slug while human-readable descriptions SHALL identify the `Agora Hub` product.

#### Scenario: Developer inspects repository metadata
- **WHEN** a developer views the GitHub repository or the configured `origin` remote
- **THEN** the canonical repository identity is `Devin333/Agora-Hub`

#### Scenario: Developer inspects package metadata
- **WHEN** a developer builds or inspects Python and JavaScript package metadata
- **THEN** package names use `agora-hub`-based slugs and descriptions use the `Agora Hub` brand

### Requirement: Runtime compatibility identifiers remain stable
The rename SHALL preserve existing machine-readable compatibility identifiers, including `.newsroom` storage paths, `NEWSROOM_*` environment variables, `newsroom_sdk` imports, `NewsRoomClient` SDK symbols, cookie names, CLI executable names, and `newsroom.*` or `io.newsroom.*` durable schema and event identifiers.

#### Scenario: Existing deployment starts after the rename
- **WHEN** an existing deployment uses its current environment variables, persisted paths, CLI commands, or Python SDK imports
- **THEN** it continues to resolve the same runtime contracts without a branding-related data or configuration migration

#### Scenario: Existing run is replayed after the rename
- **WHEN** a durable run contains the existing schema or event identifiers
- **THEN** replay continues to recognize those identifiers unchanged
