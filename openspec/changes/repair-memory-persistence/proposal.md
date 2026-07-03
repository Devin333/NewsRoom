# Repair Memory Persistence

## Why

The RAG enterprise review calls out that reader repair memory is still in-memory even though repair cases and procedural strategies are supposed to survive process restarts and feed governed skill evolution later. The current `ReaderRepairService` also reaches into `memory.cases`, which couples the service to the in-memory implementation and blocks a real repository.

## What Changes

- Add a PostgreSQL-backed `ReaderRepairMemoryPort` implementation for repair cases and strategies.
- Persist active repair memory objects and append-only version history, with rollback APIs that restore a prior version as a new active version.
- Extend the business memory port and in-memory implementation with `list_cases`, version listing, and rollback methods.
- Update `ReaderRepairService` to consolidate through the memory service/port instead of reading in-memory dictionaries.
- Add an interface factory that builds a Postgres-backed reader repair service from `NEWS_DATABASE_DSN`.

## Impact

- Production reader repair memory can be configured to use PostgreSQL.
- Existing tests and offline workflows keep using in-memory memory by default.
- Migrations add two tables: `reader_repair_memory_objects` and `reader_repair_memory_versions`.

## Change Id

- `repair-memory-persistence`: Reader repair memory has a persistent Postgres implementation with version and rollback support.
