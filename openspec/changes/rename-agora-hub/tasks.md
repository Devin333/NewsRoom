## 1. Public Brand and Metadata

- [x] 1.1 Update root package metadata and current entry documentation from `NewsRoom` to `Agora Hub`, using `agora-hub` for package slugs.
- [x] 1.2 Update both web applications' browser metadata, visible brand copy, and JavaScript package metadata without changing compatibility identifiers.
- [x] 1.3 Update API/OpenAPI, MCP, CLI, SDK documentation, report attribution, and outbound user-agent branding.

## 2. Contract Coverage

- [x] 2.1 Refresh generated OpenAPI documentation and update API, MCP, CLI, SDK, and frontend expectations for the public brand.
- [x] 2.2 Add or update focused regression coverage proving the new public identity while preserving legacy runtime compatibility identifiers.

## 3. Validation and Delivery

- [x] 3.1 Run strict OpenSpec validation and focused Python/frontend checks.
- [x] 3.2 Run the required `python -m scripts.dev smoke` gate and resolve any root-cause failures.
- [x] 3.3 Commit the repository change, rename GitHub to `Devin333/Agora-Hub`, update `origin`, push, and verify the renamed default branch.
