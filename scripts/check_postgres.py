from __future__ import annotations

import json
import os
import sys
from typing import Any

from interfaces.env import load_root_env


REQUIRED_TABLES = [
    "workflow_runs",
    "workflow_events",
    "artifact_index",
    "lineage_refs",
    "reports",
    "report_sections",
    "source_items",
    "evidence_items",
    "claims",
    "claim_supports",
    "quality_results",
    "memory_documents",
    "agent_conversations",
    "agent_conversation_messages",
    "agent_conversation_state",
    "tool_executions",
    "schema_versions",
    "source_health",
]

REQUIRED_INDEXES = [
    "idx_workflow_events_run_offset",
    "idx_artifact_index_run_created",
    "idx_lineage_refs_target",
    "idx_agent_conversations_run",
    "idx_agent_conversation_messages_conversation_offset",
    "idx_agent_conversation_state_updated",
    "idx_memory_documents_collection",
]


def main() -> int:
    load_root_env()

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
                cursor.execute(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public'
                      AND indexname = ANY(%s)
                    ORDER BY indexname
                    """,
                    (REQUIRED_INDEXES,),
                )
                existing_indexes = {str(row[0]) for row in cursor.fetchall()}
    except Exception as exc:
        _emit(
            status="unready",
            service="postgres",
            reason=f"{exc.__class__.__name__}: {exc}",
        )
        return 0

    missing_tables = sorted(set(REQUIRED_TABLES) - existing_tables)
    missing_indexes = sorted(set(REQUIRED_INDEXES) - existing_indexes)
    if missing_tables or missing_indexes:
        _emit(
            status="unready",
            service="postgres",
            reason="required storage schema objects are missing; run the storage migration",
            missing_tables=missing_tables,
            missing_indexes=missing_indexes,
            existing_tables=sorted(existing_tables),
            existing_indexes=sorted(existing_indexes),
        )
        return 0

    _emit(
        status="ready",
        service="postgres",
        checked_tables=sorted(existing_tables),
        checked_indexes=sorted(existing_indexes),
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
