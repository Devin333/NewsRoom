## 1. Business Port And Service

- [x] 1.1 Extend `ReaderRepairMemoryPort` with list/version/rollback methods.
- [x] 1.2 Update `InMemoryReaderRepairMemory` to satisfy the extended port.
- [x] 1.3 Remove `ReaderRepairService` reliance on in-memory `.cases`.

## 2. PostgreSQL Persistence

- [x] 2.1 Add reader repair memory migration tables and indexes.
- [x] 2.2 Implement `PostgresReaderRepairMemoryRepository`.
- [x] 2.3 Add env factory for Postgres-backed reader repair service.

## 3. Tests And Validation

- [x] 3.1 Add business, infrastructure, migration, and factory tests.
- [x] 3.2 Run targeted tests, compile, smoke/full checks, and strict OpenSpec validation.
