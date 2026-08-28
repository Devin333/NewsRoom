## Why

`NewsRoom` no longer describes the product: the site brings together news, research papers, and projects. A single public identity is needed across the repository, published packages, operator interfaces, and GitHub so users encounter the same product name everywhere.

## What Changes

- Rename the public product brand from `NewsRoom` to `Agora Hub`.
- Rename the GitHub repository from `Devin333/NewsRoom` to `Devin333/Agora-Hub` and update the local `origin` remote.
- Update public documentation, browser titles, UI copy, API/OpenAPI metadata, MCP/CLI labels, and user-agent branding to `Agora Hub`.
- **BREAKING**: rename distributable package metadata from `newsroom` to `agora-hub`, while retaining the current Python import and SDK compatibility namespace.
- Retain `.newsroom`, `NEWSROOM_*`, `newsroom_sdk`, `NewsRoomClient`, event/schema identifiers, cookies, and persisted data locations as compatibility identifiers; this change does not perform a runtime namespace migration.

## Capabilities

### New Capabilities

- `product-brand-identity`: Defines the canonical Agora Hub public brand and the compatibility boundary for legacy runtime identifiers.

### Modified Capabilities

- None.

## Impact

- Root metadata and entry documentation: `pyproject.toml`, `README.md`, and active operator/API/SDK documentation.
- Product surfaces: both Next.js applications, public API/OpenAPI metadata, MCP metadata, and CLI help text.
- Package metadata: Python distribution metadata and both JavaScript workspace package names/lockfiles.
- Delivery metadata: GitHub repository name, description, and local `origin` remote URL.
- Tests: API/OpenAPI/MCP/CLI assertions and browser-facing brand assertions.
