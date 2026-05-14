from __future__ import annotations

import json
import os
import sys
from typing import Any


REQUIRED_TABLES = [
    "workflow_runs",
    "reports",
    "source_items",
    "evidence_items",
    "claims",
    "quality_results",
]


def main() -> int:
    dsn = os.environ.get("NEWS_DATABASE_DSN")
    if not dsn:
        _emit(
            status="skipped",
            service="postgres",
            reason="NEWS_DATABASE_DSN is not set",
        )
        return 0

    try:
        import psycopg
    except ModuleNotFoundError as exc:
        _emit(
            status="unready",
            service="postgres",
            reason=f"missing dependency: {exc.name}",
        )
        return 0

    try:
        with psycopg.connect(dsn, connect_timeout=_connect_timeout_seconds()) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                cursor.execute(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name = ANY(%s)
                    ORDER BY table_name
                    """,
                    (REQUIRED_TABLES,),
                )
                existing_tables = {str(row[0]) for row in cursor.fetchall()}
    except Exception as exc:
        _emit(
            status="unready",
            service="postgres",
            reason=f"{exc.__class__.__name__}: {exc}",
        )
        return 0

    missing_tables = sorted(set(REQUIRED_TABLES) - existing_tables)
    if missing_tables:
        _emit(
            status="unready",
            service="postgres",
            reason="required tables are missing; run the storage migration",
            missing_tables=missing_tables,
            existing_tables=sorted(existing_tables),
        )
        return 0

    _emit(
        status="ready",
        service="postgres",
        checked_tables=sorted(existing_tables),
    )
    return 0


def _connect_timeout_seconds() -> int:
    value = os.environ.get("NEWS_POSTGRES_CHECK_TIMEOUT_SECONDS", "3")
    try:
        timeout = int(value)
    except ValueError:
        return 3
    return max(1, timeout)


def _emit(**payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
