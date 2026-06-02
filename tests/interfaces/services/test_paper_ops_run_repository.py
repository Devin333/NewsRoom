from datetime import datetime, timedelta, timezone

from interfaces.services.paper_ops_run_repository import PaperOpsRunRepository, new_ops_run


def test_ops_run_repository_reclaims_stale_active_operation(tmp_path) -> None:
    current_time = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)

    def clock() -> datetime:
        return current_time

    repository = PaperOpsRunRepository(
        tmp_path,
        active_timeout_seconds=60,
        clock=clock,
    )
    queued, first_run = repository.try_enqueue_run(
        new_ops_run(
            run_id="stale-run",
            task_type="papers.visual_compile_backfill",
            status="queued",
            operation_key="papers.visual_compile_backfill:{}",
        )
    )
    assert queued is True
    assert first_run["status"] == "queued"
    assert first_run["leaseExpiresAt"] == "2026-06-01T12:01:00Z"

    current_time += timedelta(seconds=61)
    queued, second_run = repository.try_enqueue_run(
        new_ops_run(
            run_id="replacement-run",
            task_type="papers.visual_compile_backfill",
            status="queued",
            operation_key="papers.visual_compile_backfill:{}",
        )
    )

    runs = repository.list_runs(limit=10)
    assert queued is True
    assert second_run["runId"] == "replacement-run"
    assert runs[0]["runId"] == "replacement-run"
    assert runs[1]["runId"] == "stale-run"
    assert runs[1]["status"] == "stale_failed"
    assert runs[1]["errorCode"] == "local_ops_run_stale"


def test_ops_run_repository_keeps_fresh_active_operation_deduplicated(tmp_path) -> None:
    current_time = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
    repository = PaperOpsRunRepository(
        tmp_path,
        active_timeout_seconds=60,
        clock=lambda: current_time,
    )
    repository.try_enqueue_run(
        new_ops_run(
            run_id="fresh-run",
            task_type="papers.ingest_github_arxiv_daily",
            status="queued",
            operation_key="papers.ingest_github_arxiv_daily:{}",
        )
    )

    queued, existing_run = repository.try_enqueue_run(
        new_ops_run(
            run_id="duplicate-run",
            task_type="papers.ingest_github_arxiv_daily",
            status="queued",
            operation_key="papers.ingest_github_arxiv_daily:{}",
        )
    )

    assert queued is False
    assert existing_run["runId"] == "fresh-run"
