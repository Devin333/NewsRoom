# Repair Memory Persistence Design

## Boundary

`business/research` owns the reader repair memory contract and service orchestration. `infrastructure/storage/postgres` owns SQL, migrations, and serialization to PostgreSQL. `interfaces/services` is the composition root that may import both layers.

## Repository Shape

The Postgres repository stores two object types:

- `case`: serialized `ReaderRepairCase`
- `strategy`: serialized `ReaderRepairStrategy`

The active object table supports recall queries and current-state reads. The version table records every write or rollback as append-only history. Rollback restores a previous payload by writing it back to the active table and appending a new `rollback` version, preserving auditability instead of mutating history.

## Business Contract

`ReaderRepairMemoryPort` gains:

- `list_cases(namespace=...)`
- `list_case_versions(...)`
- `rollback_case(...)`
- `list_strategy_versions(...)`
- `rollback_strategy(...)`
- `propose_write(...)`

The existing `ReaderRepairMemoryService.commit_case()` path stays the controlled write path for cases. Strategy writes remain explicit and still do not publish active skills.

## Service Decoupling

`ReaderRepairService` currently consolidates with `self.memory_service.memory.cases.values()`. That is replaced with `self.memory_service.list_cases()`, so service logic works with either in-memory or Postgres memory.

## Composition

`interfaces/services/reader_repair_factory.py` exposes:

- `build_reader_repair_memory_from_env(env=None)`
- `build_reader_repair_service_from_env(env=None)`

When `NEWS_DATABASE_DSN` is set, the factory returns a Postgres-backed memory/service. Without the DSN, it returns `None`, leaving callers free to use explicit in-memory test wiring.

## Tests

- Business tests prove service consolidation no longer depends on `.cases`.
- Postgres repository tests prove SQL write/recall/version/rollback behavior.
- Migration tests prove the new tables are part of the repository migration contract.
- Interface factory tests prove env-based production wiring.
