from __future__ import annotations

from framework import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.weekly_run_service import WeeklyRunApplicationService


def test_weekly_run_service_persists_with_weekly_profile(tmp_path) -> None:
    persistence = _Persistence()
    service = WeeklyRunApplicationService(
        artifact_root=tmp_path,
        persistence_service=persistence,
        report_service_factory=lambda artifact_root: _ReportService(),
        weekly_runner_cls=_WeeklyRunner,
        profile="weekly",
    )

    result = service.run_weekly(topic="AI", run_id="weekly-1")

    assert result.run_id == "weekly-1"
    assert persistence.profile == "weekly"


class _Persistence:
    profile = None

    def prepare_repository(self):
        return object()

    def persist_prepared_result(self, repository, result, *, profile):
        self.profile = profile


class _ReportService:
    repository = object()


class _WeeklyRunner:
    def __init__(self, *, artifact_root, report_repository):
        self.artifact_root = artifact_root
        self.report_repository = report_repository

    def run(self, **kwargs):
        return RunResult(
            run_id=kwargs["run_id"],
            workflow_id="weekly",
            workflow_version="1",
            status=WorkflowStatus.SUCCEEDED,
            output={},
        )
