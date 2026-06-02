from __future__ import annotations

from business.boards.cross_board.workflows.daily_intelligence.dependency_bundle import (
    DailyIntelligenceRuntime,
)
from business.boards.cross_board.workflows.daily_intelligence.runtime_assembly import (
    DailySourceRuntimeAssembly,
    build_daily_intelligence_runtime,
    build_daily_source_runtime_assembly,
    source_runtime_assembly_from_runtime,
)


def test_build_daily_intelligence_runtime_constructs_default_runtime(tmp_path) -> None:
    runtime = build_daily_intelligence_runtime(artifact_root=tmp_path)

    assert isinstance(runtime, DailyIntelligenceRuntime)
    assert runtime.artifact_root == tmp_path
    assert runtime.source_registry is runtime.source_collector.source_registry
    assert runtime.source_dispatcher is runtime.source_collector.source_dispatcher
    assert runtime.report_writer is not None


def test_source_runtime_assembly_from_runtime_projects_connectors(tmp_path) -> None:
    feed_connector = object()
    runtime = build_daily_intelligence_runtime(
        artifact_root=tmp_path,
        feed_connector=feed_connector,
    )

    assembly = source_runtime_assembly_from_runtime(runtime)

    assert assembly.source_registry is runtime.source_registry
    assert assembly.source_collector is runtime.source_collector
    assert assembly.feed_connector is feed_connector
    assert assembly.source_dispatcher is runtime.source_dispatcher


def test_legacy_source_runtime_assembly_still_available() -> None:
    assembly = build_daily_source_runtime_assembly()

    assert isinstance(assembly, DailySourceRuntimeAssembly)
    assert assembly.connector_bundle.feed_connector is assembly.feed_connector


def test_source_runtime_assembly_threads_connector_explicitly() -> None:
    feed_connector = object()

    assembly = build_daily_source_runtime_assembly(feed_connector=feed_connector)

    assert assembly.feed_connector is feed_connector
    assert assembly.source_dispatcher.feed_connector is feed_connector
    assert assembly.connector_bundle.feed_connector is feed_connector
