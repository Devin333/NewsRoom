from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import (
    DailyIntelligenceRuntime,
)
from business.boards.cross_board.workflows.daily_intelligence.runtime_assembly import (
    DailySourceRuntimeAssembly,
    build_daily_intelligence_runtime,
    build_daily_source_runtime_assembly,
)


def test_build_daily_intelligence_runtime_constructs_default_runtime(tmp_path) -> None:
    runtime = build_daily_intelligence_runtime(artifact_root=tmp_path)

    assert isinstance(runtime, DailyIntelligenceRuntime)
    assert runtime.artifact_root == tmp_path
    assert runtime.source_registry is runtime.source_collector.source_registry
    assert runtime.source_dispatcher is runtime.source_collector.source_dispatcher
    assert runtime.report_writer is not None


def test_legacy_source_runtime_assembly_still_available() -> None:
    assembly = build_daily_source_runtime_assembly()

    assert isinstance(assembly, DailySourceRuntimeAssembly)
    assert assembly.connector_bundle.feed_connector is assembly.feed_connector
