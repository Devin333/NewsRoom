from framework.workflow.runtime.run_result import RunResult
from framework.specs import WorkflowStatus
from interfaces.services.report_service import ReportApplicationService
from interfaces.services.run_service import RunApplicationService
from workflows.daily_intelligence.profiles import (
    NEWSROOM_DAILY_AGENTIC_ENABLED,
    PROFILE_AGENTIC_LIVE,
    PROFILE_AGENTIC_OFFLINE,
    PROFILE_LIVE,
    PROFILE_LIVE_OFFLINE,
)


def test_run_service_runs_agentic_daily_offline_and_persists_report(tmp_path) -> None:
    result = RunApplicationService(artifact_root=tmp_path).run_daily_agentic(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-service-offline",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.workflow_id == "daily-intelligence-agentic"
    assert result.output["final_report"].title == "Daily Intelligence: AI policy"
    assert "# Daily Intelligence: AI policy" in result.output["report_markdown"]
    assert result.output["planner_agent_loop_result"]["success"] is True
    assert result.output["analyst_agent_loop_result"]["success"] is True
    assert "writer_agent_loop_result" in result.output
    assert "verifier_agent_loop_result" in result.output
    assert "editor_agent_loop_result" in result.output

    record = ReportApplicationService(artifact_root=tmp_path).get_report(
        "agentic-service-offline:final"
    )

    assert record.run_id == "agentic-service-offline"
    assert record.status == "final"
    assert record.title == "Daily Intelligence: AI policy"
    assert record.report_markdown is not None
    assert "Daily Intelligence: AI policy" in record.report_markdown


def test_run_service_agentic_persists_with_repository(tmp_path, monkeypatch) -> None:
    import interfaces.services.run_service as run_service_module

    fake_repository = _FakePersistenceRepository()
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: fake_repository,
    )

    result = RunApplicationService(artifact_root=tmp_path).run_daily_agentic(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-persisted",
    )

    assert result.run_id == "agentic-persisted"
    assert fake_repository.migrated is True
    assert fake_repository.workflow_runs[0].run_id == "agentic-persisted"
    assert fake_repository.workflow_runs[0].profile == PROFILE_AGENTIC_OFFLINE
    assert fake_repository.reports[0].status == "final"
    assert fake_repository.quality_results[0].decision == "pass"


def test_run_service_agentic_uses_agentic_runner_without_changing_explicit_agentic_entrypoint(
    tmp_path,
    monkeypatch,
) -> None:
    import interfaces.services.run_service as run_service_module

    calls = []
    fake_repository = _FakePersistenceRepository()
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: fake_repository,
    )
    monkeypatch.setattr(
        run_service_module,
        "DailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="legacy-daily"),
    )
    monkeypatch.setattr(
        run_service_module,
        "AgenticDailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="agentic-daily"),
    )

    legacy_result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile="live-offline",
        topic="AI policy",
        source_limit=1,
        run_id="legacy-run",
    )
    agentic_result = RunApplicationService(artifact_root=tmp_path).run_daily_agentic(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-run",
    )

    assert legacy_result.workflow_id == "agentic-daily"
    assert agentic_result.workflow_id == "agentic-daily"
    assert calls == [
        {
            "workflow_id": "agentic-daily",
            "profile": "live-offline",
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "legacy-run",
        },
        {
            "workflow_id": "agentic-daily",
            "profile": PROFILE_AGENTIC_OFFLINE,
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "agentic-run",
        },
    ]


def test_run_daily_routes_agentic_profiles_to_agentic_runner(
    tmp_path,
    monkeypatch,
) -> None:
    import interfaces.services.run_service as run_service_module

    calls = []
    fake_repository = _FakePersistenceRepository()
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: fake_repository,
    )
    monkeypatch.setattr(
        run_service_module,
        "DailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="legacy-daily"),
    )
    monkeypatch.setattr(
        run_service_module,
        "AgenticDailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="agentic-daily"),
    )

    offline_result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile=PROFILE_AGENTIC_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-offline-run",
    )
    live_result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile=PROFILE_AGENTIC_LIVE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-live-run",
    )

    assert offline_result.workflow_id == "agentic-daily"
    assert live_result.workflow_id == "agentic-daily"
    assert calls == [
        {
            "workflow_id": "agentic-daily",
            "profile": PROFILE_AGENTIC_OFFLINE,
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "agentic-offline-run",
        },
        {
            "workflow_id": "agentic-daily",
            "profile": PROFILE_AGENTIC_LIVE,
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "agentic-live-run",
        },
    ]


def test_run_daily_keeps_legacy_profiles_on_legacy_runner_by_default(
    tmp_path,
    monkeypatch,
) -> None:
    import interfaces.services.run_service as run_service_module

    calls = []
    fake_repository = _FakePersistenceRepository()
    monkeypatch.delenv(NEWSROOM_DAILY_AGENTIC_ENABLED, raising=False)
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: fake_repository,
    )
    monkeypatch.setattr(
        run_service_module,
        "DailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="legacy-daily"),
    )
    monkeypatch.setattr(
        run_service_module,
        "AgenticDailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="agentic-daily"),
    )

    offline_result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile=PROFILE_LIVE_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="legacy-offline-run",
    )
    live_result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile=PROFILE_LIVE,
        topic="AI policy",
        source_limit=1,
        run_id="legacy-live-run",
    )

    assert offline_result.workflow_id == "agentic-daily"
    assert live_result.workflow_id == "agentic-daily"
    assert calls == [
        {
            "workflow_id": "agentic-daily",
            "profile": PROFILE_LIVE_OFFLINE,
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "legacy-offline-run",
        },
        {
            "workflow_id": "agentic-daily",
            "profile": PROFILE_LIVE,
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "legacy-live-run",
        },
    ]


def test_run_daily_env_flag_routes_legacy_profiles_to_agentic_runner(
    tmp_path,
    monkeypatch,
) -> None:
    import interfaces.services.run_service as run_service_module

    calls = []
    fake_repository = _FakePersistenceRepository()
    monkeypatch.setenv(NEWSROOM_DAILY_AGENTIC_ENABLED, "true")
    monkeypatch.setattr(
        run_service_module,
        "repository_from_env",
        lambda artifact_root: fake_repository,
    )
    monkeypatch.setattr(
        run_service_module,
        "DailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="legacy-daily"),
    )
    monkeypatch.setattr(
        run_service_module,
        "AgenticDailyIntelligenceRunner",
        lambda artifact_root: _RecordingRunner(calls, workflow_id="agentic-daily"),
    )

    offline_result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile=PROFILE_LIVE_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-flag-offline-run",
    )
    live_result = RunApplicationService(artifact_root=tmp_path).run_daily(
        profile=PROFILE_LIVE,
        topic="AI policy",
        source_limit=1,
        run_id="agentic-flag-live-run",
    )

    assert offline_result.workflow_id == "agentic-daily"
    assert live_result.workflow_id == "agentic-daily"
    assert calls == [
        {
            "workflow_id": "agentic-daily",
            "profile": PROFILE_LIVE_OFFLINE,
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "agentic-flag-offline-run",
        },
        {
            "workflow_id": "agentic-daily",
            "profile": PROFILE_LIVE,
            "topic": "AI policy",
            "source_limit": 1,
            "run_id": "agentic-flag-live-run",
        },
    ]


def test_agentic_daily_offline_smoke_script_succeeds(tmp_path, monkeypatch, capsys) -> None:
    from scripts.smoke import agentic_daily_offline

    monkeypatch.setattr(
        "sys.argv",
        [
            "agentic_daily_offline",
            "--artifact-root",
            str(tmp_path),
            "--run-id",
            "agentic-smoke-script",
            "--topic",
            "AI policy",
            "--source-limit",
            "1",
        ],
    )

    exit_code = agentic_daily_offline.main()
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "status=succeeded" in captured.out
    assert "run_id=agentic-smoke-script" in captured.out
    assert "profile=agentic-offline" in captured.out


class _FakePersistenceRepository:
    def __init__(self) -> None:
        self.migrated = False
        self.workflow_runs = []
        self.reports = []
        self.source_items = []
        self.evidence_items = []
        self.claims = []
        self.quality_results = []

    def migrate(self) -> None:
        self.migrated = True

    def save_workflow_run(self, record) -> None:
        self.workflow_runs.append(record)

    def save_report(self, record) -> None:
        self.reports.append(record)

    def save_source_item(self, record) -> None:
        self.source_items.append(record)

    def save_evidence_item(self, record) -> None:
        self.evidence_items.append(record)

    def save_claim(self, record) -> None:
        self.claims.append(record)

    def save_quality_result(self, record) -> None:
        self.quality_results.append(record)


class _RecordingRunner:
    def __init__(self, calls, *, workflow_id: str) -> None:
        self.calls = calls
        self.workflow_id = workflow_id

    def run(self, *, profile, topic, source_limit, run_id=None):
        self.calls.append(
            {
                "workflow_id": self.workflow_id,
                "profile": profile,
                "topic": topic,
                "source_limit": source_limit,
                "run_id": run_id,
            }
        )
        return RunResult(
            run_id=run_id or "generated",
            workflow_id=self.workflow_id,
            workflow_version="1",
            status=WorkflowStatus.SUCCEEDED,
            output={},
        )
