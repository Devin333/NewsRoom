from __future__ import annotations

import os
from collections.abc import Mapping

from business.research.reader_repair import ReaderRepairService
from infrastructure.storage.postgres import PostgresReaderRepairMemoryRepository
from infrastructure.storage.postgres.dsn import normalize_dsn
from interfaces.services.reader_repair_memory import PostgresReaderRepairMemoryPort


def build_reader_repair_memory_from_env(
    env: Mapping[str, str] | None = None,
) -> PostgresReaderRepairMemoryPort | None:
    values = os.environ if env is None else env
    dsn = values.get("NEWS_DATABASE_DSN")
    if not dsn:
        return None
    return PostgresReaderRepairMemoryPort(PostgresReaderRepairMemoryRepository(normalize_dsn(dsn)))


def build_reader_repair_service_from_env(
    env: Mapping[str, str] | None = None,
) -> ReaderRepairService:
    memory = build_reader_repair_memory_from_env(env)
    if memory is None:
        return ReaderRepairService()
    return ReaderRepairService(memory=memory)


__all__ = [
    "build_reader_repair_memory_from_env",
    "build_reader_repair_service_from_env",
]
