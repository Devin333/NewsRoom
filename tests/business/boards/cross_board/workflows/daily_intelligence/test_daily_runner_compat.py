from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import DailyIntelligenceRuntime
from business.boards.cross_board.workflows.daily_intelligence.profiles import PROFILE_LIVE_OFFLINE
from business.boards.cross_board.workflows.daily_intelligence.runner import DailyIntelligenceRunner
from business.boards.cross_board.workflows.daily_intelligence.runtime_assembly import (
    build_daily_intelligence_runtime,
)
from framework.specs import WorkflowStatus


def test_daily_runner_old_connector_argument_remains_compatible(tmp_path) -> None:
    feed_connector = object()

    runner = DailyIntelligenceRunner(artifact_root=tmp_path, feed_connector=feed_connector)

    assert runner.feed_connector is feed_connector
    assert runner.source_runtime_assembly.feed_connector is feed_connector


def test_daily_runner_accepts_prebuilt_runtime(tmp_path) -> None:
    runtime = build_daily_intelligence_runtime(artifact_root=tmp_path)

    runner = DailyIntelligenceRunner(runtime=runtime)

    assert runner.runtime is runtime
    assert runner.artifact_root == tmp_path
    assert runner.source_registry is runner.source_runtime_assembly.source_registry
    assert runner.source_dispatcher is runner.source_runtime_assembly.source_dispatcher
    assert runner.source_health_manager is runner.source_runtime_assembly.source_health_manager


def test_daily_runner_run_behavior_stays_offline(tmp_path) -> None:
    runtime = build_daily_intelligence_runtime(artifact_root=tmp_path)
    assert isinstance(runtime, DailyIntelligenceRuntime)

    result = DailyIntelligenceRunner(runtime=runtime).run(
        profile=PROFILE_LIVE_OFFLINE,
        topic="AI policy",
        source_limit=1,
        run_id="daily-runner-compat",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    assert result.run_id == "daily-runner-compat"
    assert result.output["final_report"].title == "Daily Intelligence: AI policy"
