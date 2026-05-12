from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

import psycopg

from domain.sources import SourceHealth
from storage.local_json import ReportNotFoundError
from storage.postgres.migrations import load_migration_sql
from storage.repository import ReportRecord, WorkflowRunRecord


ConnectionFactory = Callable[[], Any]


@dataclass(frozen=True)
class PostgresReportDetailRecord:
    report_id: str
    run_id: str
    status: str
    finished_at: str
    title: str | None
    report_json: dict[str, Any] | None
    report_markdown: str | None
    quality_score: float | None
    citation_coverage_score: float | None
    manifest_path: str | None
    report_json_path: str | None = None
    report_markdown_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "finished_at": self.finished_at,
            "title": self.title,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "manifest_path": self.manifest_path,
            "report_json_path": self.report_json_path,
            "report_markdown_path": self.report_markdown_path,
            "report_json": self.report_json,
            "report_markdown": self.report_markdown,
        }


@dataclass(frozen=True)
class PostgresReportSearchRecord:
    report_id: str
    run_id: str
    status: str
    finished_at: str
    title: str | None
    quality_score: float | None
    citation_coverage_score: float | None
    manifest_path: str | None
    report_json_path: str | None = None
    report_markdown_path: str | None = None
    workflow_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "run_id": self.run_id,
            "status": self.status,
            "finished_at": self.finished_at,
            "title": self.title,
            "quality_score": self.quality_score,
            "citation_coverage_score": self.citation_coverage_score,
            "manifest_path": self.manifest_path,
            "report_json_path": self.report_json_path,
            "report_markdown_path": self.report_markdown_path,
            "workflow_id": self.workflow_id,
        }


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
            report_markdown, quality_score, citation_coverage_score, manifest_path
        )
        VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)
        ON CONFLICT (report_id) DO UPDATE SET
            status = EXCLUDED.status,
            title = EXCLUDED.title,
            report_json = EXCLUDED.report_json,
            report_markdown = EXCLUDED.report_markdown,
            quality_score = EXCLUDED.quality_score,
            citation_coverage_score = EXCLUDED.citation_coverage_score,
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
            record.citation_coverage_score,
            record.manifest_path,
        )
        self._execute(sql, params)

    def update_source_health(self, health: SourceHealth) -> None:
        sql = """
        INSERT INTO source_health (
            source_id, status, consecutive_failures, last_success_at,
            last_failure_at, cooldown_until, last_error, success_count_24h,
            failure_count_24h, avg_latency_ms_24h
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
        ON CONFLICT (source_id) DO UPDATE SET
            status = EXCLUDED.status,
            consecutive_failures = EXCLUDED.consecutive_failures,
            last_success_at = EXCLUDED.last_success_at,
            last_failure_at = EXCLUDED.last_failure_at,
            cooldown_until = EXCLUDED.cooldown_until,
            last_error = EXCLUDED.last_error,
            success_count_24h = EXCLUDED.success_count_24h,
            failure_count_24h = EXCLUDED.failure_count_24h,
            avg_latency_ms_24h = EXCLUDED.avg_latency_ms_24h,
            updated_at = now()
        """
        params = (
            health.source_id,
            health.status.value,
            health.consecutive_failures,
            health.last_success_at,
            health.last_failure_at,
            health.cooldown_until,
            _json_or_none(health.last_error.to_dict() if health.last_error else None),
            health.success_count_24h,
            health.failure_count_24h,
            health.avg_latency_ms_24h,
        )
        self._execute(sql, params)

    def latest_report(self) -> PostgresReportDetailRecord:
        sql = """
        SELECT
            r.report_id, r.run_id, r.status, r.title, r.report_json,
            r.report_markdown, r.quality_score, r.citation_coverage_score,
            r.manifest_path, r.updated_at
        FROM reports r
        ORDER BY r.updated_at DESC
        LIMIT 1
        """
        row = self._fetch_one(sql, ())
        if row is None:
            raise ReportNotFoundError("no PostgreSQL report found")
        return _detail_from_row(row)

    def get_report(self, report_id: str) -> PostgresReportDetailRecord:
        sql = """
        SELECT
            r.report_id, r.run_id, r.status, r.title, r.report_json,
            r.report_markdown, r.quality_score, r.citation_coverage_score,
            r.manifest_path, r.updated_at
        FROM reports r
        WHERE r.report_id = %s
        """
        row = self._fetch_one(sql, (report_id,))
        if row is None:
            raise ReportNotFoundError(f"report not found: {report_id}")
        return _detail_from_row(row)

    def list_reports(
        self,
        *,
        limit: int = 20,
        workflow_id: str | None = None,
    ) -> list[PostgresReportSearchRecord]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        where = ""
        params: tuple[Any, ...]
        if workflow_id:
            where = "WHERE wr.workflow_id = %s"
            params = (workflow_id, limit)
        else:
            params = (limit,)
        sql = f"""
        SELECT
            r.report_id, r.run_id, r.status, r.title, r.quality_score,
            r.citation_coverage_score, r.manifest_path, r.updated_at,
            wr.workflow_id
        FROM reports r
        LEFT JOIN workflow_runs wr ON wr.run_id = r.run_id
        {where}
        ORDER BY r.updated_at DESC
        LIMIT %s
        """
        rows = self._fetch_all(sql, params)
        return [_list_record_from_row(row) for row in rows]

    def search_reports(self, query: str, *, limit: int = 20) -> list[PostgresReportSearchRecord]:
        sql = """
        SELECT
            r.report_id, r.run_id, r.status, r.title, r.quality_score,
            r.citation_coverage_score, r.manifest_path, r.updated_at
        FROM reports r
        WHERE
            COALESCE(r.title, '') ILIKE %s
            OR COALESCE(r.report_markdown, '') ILIKE %s
            OR r.report_json::text ILIKE %s
        ORDER BY r.updated_at DESC
        LIMIT %s
        """
        pattern = f"%{query}%"
        rows = self._fetch_all(sql, (pattern, pattern, pattern, limit))
        return [_search_record_from_row(row) for row in rows]

    def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
            connection.commit()

    def _fetch_one(self, sql: str, params: tuple[Any, ...]) -> tuple[Any, ...] | None:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()

    def _fetch_all(self, sql: str, params: tuple[Any, ...]) -> list[tuple[Any, ...]]:
        with self._connection_factory() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _detail_from_row(row: tuple[Any, ...]) -> PostgresReportDetailRecord:
    return PostgresReportDetailRecord(
        report_id=str(row[0]),
        run_id=str(row[1]),
        status=str(row[2]),
        title=row[3],
        report_json=_dict_or_none(row[4]),
        report_markdown=row[5],
        quality_score=row[6],
        citation_coverage_score=row[7],
        manifest_path=row[8],
        finished_at=_timestamp(row[9]),
    )


def _search_record_from_row(row: tuple[Any, ...]) -> PostgresReportSearchRecord:
    return PostgresReportSearchRecord(
        report_id=str(row[0]),
        run_id=str(row[1]),
        status=str(row[2]),
        title=row[3],
        quality_score=row[4],
        citation_coverage_score=row[5],
        manifest_path=row[6],
        finished_at=_timestamp(row[7]),
    )


def _list_record_from_row(row: tuple[Any, ...]) -> PostgresReportSearchRecord:
    return PostgresReportSearchRecord(
        report_id=str(row[0]),
        run_id=str(row[1]),
        status=str(row[2]),
        title=row[3],
        quality_score=row[4],
        citation_coverage_score=row[5],
        manifest_path=row[6],
        finished_at=_timestamp(row[7]),
        workflow_id=row[8],
    )


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        payload = json.loads(value)
        return payload if isinstance(payload, dict) else None
    return dict(value)


def _timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value or "")
