# Infrastructure Memory Port Migration Note

Current architecture debt: selected infrastructure storage adapters still import `business.memory` models directly.

Allowed debt is tracked by `tests/architecture/test_infrastructure_memory_dependency_debt.py`.

Future migration path:

1. Define storage-facing memory and graph DTOs or ports.
2. Move business model conversion into interface/application service or business adapter code.
3. Remove direct `business.memory` imports from infrastructure modules.
4. Delete the architecture-test allowlist.

This note is intentionally a follow-up plan, not part of the current P0-P2 code migration.
