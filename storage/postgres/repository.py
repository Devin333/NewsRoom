from __future__ import annotations

import json
from typing import Any, Callable

import psycopg

from storage.postgres.migrations import load_migration_sql
from storage.repository import ReportRecord, WorkflowRunRecord


ConnectionFactory = Callable[[], Any]


class PostgresRepository:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self.dsn = dsn
        self._connection_factory = connection_factory or (lambda: psycopg.connect(dsn))

    def migrate(self) -> None:
        sql = load_migration_sql()
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
            connection.commit()

    def save_workflow_run(self, record: WorkflowRunRecord) -> None:
        sql = """
        INSERT INTO workflow_runs (
            run_id, workflow_id, workflow_version, status, profile,
            artifact_dir, manifest_path, events_path, error, metrics
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
        ON CONFLICT (run_id) DO UPDATE SET
            status = EXCLUDED.status,
            artifact_dir = EXCLUDED.artifact_dir,
            manifest_path = EXCLUDED.manifest_path,
            events_path = EXCLUDED.events_path,
            error = EXCLUDED.error,
            metrics = EXCLUDED.metrics,
            updated_at = now()
        """
        params = (
            record.run_id,
            record.workflow_id,
            record.workflow_version,
            record.status,
            record.profile,
            record.artifact_dir,
            record.manifest_path,
            record.events_path,
            _json(record.error),
            _json(record.metrics),
        )
        self._execute(sql, params)

    def save_report(self, record: ReportRecord) -> None:
        sql = """
        INSERT INTO reports (
            report_id, run_id, status, title, report_json,
            report_markdown, quality_score, manifest_path
        )
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        ON CONFLICT (report_id) DO UPDATE SET
            status = EXCLUDED.status,
            title = EXCLUDED.title,
            report_json = EXCLUDED.report_json,
            report_markdown = EXCLUDED.report_markdown,
            quality_score = EXCLUDED.quality_score,
            manifest_path = EXCLUDED.manifest_path,
            updated_at = now()
        """
        params = (
            record.report_id,
            record.run_id,
            record.status,
            record.title,
            _json(record.report_json),
            record.report_markdown,
            record.quality_score,
            record.manifest_path,
        )
        self._execute(sql, params)

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
            connection.commit()


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)
