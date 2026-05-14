import json

import pytest

from core.framework import WorkflowRunner
from core.framework.artifacts import ArtifactManager
from core.framework.specs import EdgeSpec, StepSpec, WorkflowSpec, WorkflowStatus
from core.framework.workflow import (
    WorkflowDataBufferChange,
    FunctionStepRegistry,
    FunctionStepRunner,
    WorkflowExecutor,
    WorkflowRunInspectionError,
    WorkflowRunInspector,
    build_artifact_inventory,
    build_run_catalog_health,
    build_run_health_report,
    build_workflow_timeline,
    build_workflow_replay_content_bundle,
    catalog_runs_by_status,
    catalog_runs_by_workflow,
    compare_workflow_run_inspections,
    compare_workflow_runs,
    event_records_by_step,
    failed_run_items,
    failed_step_summaries,
    filter_artifacts_by_prefix,
    health_report_summary,
    inspect_workflow_run,
    inspect_workflow_run_diagnostics,
    invalid_run_items,
    latest_workflow_run,
    list_workflow_runs,
    paused_run_items,
    read_source_artifact_content_records,
    read_workflow_artifact_content,
    redact_sensitive_values,
    replay_bundle_summary,
    required_artifact_records,
    resolve_run_dir,
    resolve_artifact_path,
    step_artifact_records,
    summarize_data_buffer_diff,
    summarize_workflow_timeline,
    terminal_artifact_record,
    timeline_items_by_event_type,
    timeline_items_by_phase,
    timeline_items_by_step,
    unhealthy_timeline_items,
    unhealthy_run_items,
    workflow_run_catalog_health,
    workflow_run_catalog_health_summary,
    workflow_run_catalog_summary,
    workflow_run_comparison_summary,
    workflow_run_inspection_summary,
)


def test_workflow_run_inspector_builds_summary_and_replay_bundle(tmp_path) -> None:
    executor = _sample_executor(tmp_path)

    result = executor.execute(
        _sample_spec(),
        {"topic": "ai"},
        profile="test",
        run_id="inspect-run",
    )

    assert result.status == WorkflowStatus.SUCCEEDED
    inspector = WorkflowRunInspector()
    inspection = inspector.inspect_run(run_dir=tmp_path / "inspect-run", strict=True)
    replay_bundle = inspector.build_replay_bundle(run_dir=tmp_path / "inspect-run", strict=True)

    assert inspection.integrity.valid is True
    assert inspection.run_id == "inspect-run"
    assert inspection.workflow_id == "inspect-sample"
    assert inspection.status == "succeeded"
    assert inspection.succeeded is True
    assert inspection.failed is False
    assert inspection.paused is False
    assert inspection.event_summary.event_count == 8
    assert inspection.event_summary.terminal_event_type == "workflow_succeeded"
    assert inspection.timeline_summary.event_count == 8
    assert inspection.timeline_summary.routing_event_count == 2
    assert inspection.timeline_summary.traversed_edges[0]["edge_id"] == "plan-to-write"
    assert inspection.artifact_inventory.complete is True
    assert inspection.artifact_inventory.terminal_artifact_exists is True
    assert inspection.data_buffer_diff_summary.added_keys == ["plan", "report"]
    assert inspection.health_report.severity == "ok"
    assert inspection.step_by_id("write").output_keys == ["report"]
    assert terminal_artifact_record(inspection).artifact_key == "output"
    assert {artifact.artifact_key for artifact in required_artifact_records(inspection)}.issuperset(
        {"request", "workflow_spec", "manifest", "events"}
    )
    assert step_artifact_records(inspection) == []
    assert filter_artifacts_by_prefix(inspection.artifacts, "data_buffer")
    assert workflow_run_inspection_summary(inspection)["event_count"] == 8
    assert workflow_run_inspection_summary(inspection)["health_severity"] == "ok"

    assert replay_bundle.request == {"topic": "ai"}
    assert replay_bundle.output["report"] == "Report: ai"
    assert replay_bundle.step_results["write"]["outputs"]["report"] == "Report: ai"
    replay_summary = replay_bundle_summary(replay_bundle)
    assert replay_bundle.integrity["valid"] is True
    assert replay_bundle.to_dict()["integrity"]["valid"] is True
    assert replay_summary["has_output"] is True
    assert replay_summary["step_result_count"] == 2
    assert replay_summary["integrity_valid"] is True


def test_workflow_run_inspector_reports_missing_artifact_file(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="missing-artifact-run")
    (tmp_path / "missing-artifact-run" / "output.json").unlink()

    inspection = inspect_workflow_run(tmp_path / "missing-artifact-run")

    assert inspection.integrity.valid is False
    assert "output" in inspection.integrity.missing_artifact_files
    with pytest.raises(WorkflowRunInspectionError, match="inspection failed"):
        inspect_workflow_run(tmp_path / "missing-artifact-run", strict=True)


def test_workflow_run_inspector_guards_artifact_paths(tmp_path) -> None:
    run_dir = tmp_path / "bad-run"
    run_dir.mkdir()
    manifest = {
        "schema_version": "newsroom.workflow_run_manifest.v1",
        "run_id": "bad-run",
        "workflow_id": "inspect-sample",
        "workflow_version": "1.0",
        "profile": "test",
        "status": "succeeded",
        "started_at": "2026-05-13T01:02:03Z",
        "finished_at": "2026-05-13T01:02:04Z",
        "path": [],
        "steps": {},
        "artifacts": {
            "request": "request.json",
            "workflow_spec": "workflow_spec.json",
            "workflow_version": "workflow_version.json",
            "events": "events.jsonl",
            "manifest": "manifest.json",
            "data_buffer_snapshot": "data_buffer_snapshot.json",
            "data_buffer_initial": "data_buffer.initial.json",
            "data_buffer_final": "data_buffer.final.json",
            "data_buffer_diff": "data_buffer.diff.json",
            "step_results": "step_results.json",
            "metrics": "metrics.json",
            "redaction_report": "redaction_report.json",
            "output": "../outside.json",
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    inspection = inspect_workflow_run(run_dir)

    assert inspection.integrity.valid is False
    assert any("relative to the run directory" in item for item in inspection.integrity.errors)
    with pytest.raises(WorkflowRunInspectionError, match="within the run directory"):
        resolve_artifact_path(run_dir, "../outside.json")


def test_workflow_run_inspector_summarizes_failed_steps(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register(
        "sample.fail",
        lambda buffer: (_ for _ in ()).throw(RuntimeError("step failed")),
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )
    spec = WorkflowSpec(
        workflow_id="failed-inspection",
        name="Failed Inspection",
        version="1.0",
        start_step_id="fail",
        steps=[
            StepSpec(
                step_id="fail",
                implementation="sample.fail",
                write_keys=["report"],
            )
        ],
    )

    result = executor.execute(spec, {}, profile="test", run_id="failed-run")

    assert result.status == WorkflowStatus.FAILED
    inspection = inspect_workflow_run(tmp_path / "failed-run", strict=True)
    failed_steps = failed_step_summaries(inspection)
    events = WorkflowRunInspector().read_events(tmp_path / "failed-run", manifest=inspection.manifest)

    assert inspection.failed is True
    assert inspection.terminal_artifact_key == "error"
    assert failed_steps[0].step_id == "fail"
    assert failed_steps[0].error_type == "RuntimeError"
    assert [event.event_type for event in event_records_by_step(events, "fail")] == [
        "step_started",
        "step_failed",
    ]


def test_workflow_run_inspector_builds_timeline_helpers(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="timeline-run")
    inspector = WorkflowRunInspector()
    manifest = inspector.load_manifest(tmp_path / "timeline-run")
    events = inspector.read_events(tmp_path / "timeline-run", manifest=manifest)

    timeline = build_workflow_timeline(events)
    summary = summarize_workflow_timeline(timeline)

    assert [item.event_type for item in timeline[:3]] == [
        "workflow_started",
        "step_started",
        "step_succeeded",
    ]
    assert summary.event_count == 8
    assert summary.phase_counts["workflow"] == 2
    assert summary.phase_counts["step"] == 4
    assert summary.phase_counts["routing"] == 2
    assert summary.terminal_event_type == "workflow_succeeded"
    assert timeline_items_by_step(timeline, "plan")[0].event_type == "step_started"
    assert timeline_items_by_event_type(timeline, "edge_traversed")[0].edge_id == "plan-to-write"
    assert timeline_items_by_phase(timeline, "routing")[1].event_type == "edge_traversed"
    assert unhealthy_timeline_items(timeline) == []


def test_workflow_run_inspector_builds_artifact_inventory(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="inventory-run")

    inspection = inspect_workflow_run(tmp_path / "inventory-run", strict=True)
    inventory = build_artifact_inventory(
        inspection.artifacts,
        terminal_artifact_key=inspection.terminal_artifact_key,
    )

    assert inventory.complete is True
    assert inventory.artifact_count == len(inspection.artifacts)
    assert inventory.existing_count == inventory.artifact_count
    assert inventory.missing_count == 0
    assert inventory.required_count >= 10
    assert inventory.terminal_artifact_key == "output"
    assert inventory.terminal_artifact_exists is True
    assert inventory.content_type_counts["application/json"] >= 10
    assert inventory.category_counts["required"] >= 10
    assert inventory.total_size_bytes > 0
    assert inventory.largest_artifacts


def test_data_buffer_diff_summary_uses_shapes_not_values() -> None:
    summary = summarize_data_buffer_diff(
        {
            "added": {
                "report": {"title": "AI", "items": [1, 2]},
                "api_token": "secret-value",
            },
            "changed": {
                "ranked_items": {
                    "previous": ["old"],
                    "current": ["new", "newer"],
                },
                "score": {
                    "previous": 1,
                    "current": "1",
                },
            },
            "removed": {
                "temporary": [1, 2, 3],
            },
        }
    )

    assert summary.added_count == 2
    assert summary.changed_count == 2
    assert summary.removed_count == 1
    assert summary.total_change_count == 5
    assert summary.sensitive_keys == ["api_token"]
    assert summary.type_changed_keys == ["score"]
    assert summary.has_sensitive_changes is True
    assert WorkflowDataBufferChange(
        key="sample",
        change_type="changed",
        sensitive_key=False,
        previous_type="str",
        current_type="dict",
    ).type_changed is True
    report_change = next(change for change in summary.changes if change.key == "report")
    assert report_change.current_type == "dict"
    assert report_change.current_size == 2


def test_workflow_run_health_report_flags_missing_artifacts(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="health-missing-run")
    (tmp_path / "health-missing-run" / "output.json").unlink()

    inspection = inspect_workflow_run(tmp_path / "health-missing-run")
    health = build_run_health_report(inspection)

    assert health.severity == "error"
    assert health.healthy is False
    assert "output" in health.missing_artifact_keys
    assert "output" in " ".join(health.issues)
    assert health_report_summary(health)["issue_count"] >= 1


def test_workflow_run_diagnostics_aggregate_matches_inspection(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="diagnostics-run")

    diagnostics = inspect_workflow_run_diagnostics(tmp_path / "diagnostics-run", strict=True)

    assert diagnostics.healthy is True
    assert diagnostics.inspection.run_id == "diagnostics-run"
    assert diagnostics.timeline_summary.event_count == 8
    assert diagnostics.artifact_inventory.complete is True
    assert diagnostics.data_buffer_diff_summary.added_keys == ["plan", "report"]
    assert diagnostics.health_report.summary == "run diagnostics-run completed successfully"
    assert diagnostics.to_dict()["health_report"]["severity"] == "ok"


def test_workflow_replay_content_bundle_reads_and_redacts_artifacts(tmp_path) -> None:
    run_dir = tmp_path / "content-run"
    run_dir.mkdir()
    manifest = {
        "run_id": "content-run",
        "status": "succeeded",
        "artifacts": {
            "events": "events.jsonl",
            "report_json": "report.json",
            "report_markdown": "report.md",
            "missing": "missing.json",
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "events.jsonl").write_text(
        json.dumps({"event_type": "workflow_started", "payload": {"token": "hidden"}}) + "\n",
        encoding="utf-8",
    )
    (run_dir / "report.json").write_text(
        json.dumps({"title": "Report", "api_key": "hidden-key"}),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# Report\n", encoding="utf-8")

    bundle = build_workflow_replay_content_bundle(run_dir)
    artifacts = {artifact.artifact_key: artifact for artifact in bundle.artifacts}

    assert bundle.run_id == "content-run"
    assert bundle.event_count == 1
    assert bundle.events[0]["payload"]["token"] == "[redacted]"
    assert artifacts["report_json"].content["api_key"] == "[redacted]"
    assert artifacts["report_markdown"].content == "# Report\n"
    assert artifacts["missing"].read_error == "artifact file not found: missing.json"
    assert "hidden-key" not in json.dumps(bundle.to_dict())


def test_workflow_artifact_content_supports_limits_and_raw_redaction(tmp_path) -> None:
    run_dir = tmp_path / "artifact-content-run"
    run_dir.mkdir()
    (run_dir / "secret.json").write_text(
        json.dumps({"api_key": "hidden", "items": [1, 2, 3]}),
        encoding="utf-8",
    )
    (run_dir / "long.txt").write_text("abcdef", encoding="utf-8")

    redacted = read_workflow_artifact_content(run_dir, "secret", "secret.json")
    raw = read_workflow_artifact_content(run_dir, "secret", "secret.json", redact=False)
    truncated = read_workflow_artifact_content(run_dir, "long", "long.txt", max_bytes=3)

    assert redacted.content["api_key"] == "[redacted]"
    assert raw.content["api_key"] == "hidden"
    assert truncated.content == "abc"
    assert truncated.truncated is True
    assert redact_sensitive_values({"nested": {"authorization": "bearer"}}) == {
        "nested": {"authorization": "[redacted]"}
    }


def test_workflow_replay_content_expands_source_artifacts(tmp_path) -> None:
    run_dir = tmp_path / "source-content-run"
    item_dir = run_dir / "sources" / "items" / "feed"
    item_dir.mkdir(parents=True)
    (run_dir / "source_artifacts").mkdir()
    source_index = {
        "entries": [
            {
                "artifact_type": "source_item",
                "source_id": "feed/source",
                "object_id": "item-1",
                "path": "sources/items/feed/item-1.json",
            }
        ]
    }
    manifest = {
        "run_id": "source-content-run",
        "status": "succeeded",
        "artifacts": {"source_artifacts": "source_artifacts/index.json"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "source_artifacts" / "index.json").write_text(
        json.dumps(source_index),
        encoding="utf-8",
    )
    (item_dir / "item-1.json").write_text(
        json.dumps({"item": {"title": "Item", "metadata": {"api_key": "hidden-key"}}}),
        encoding="utf-8",
    )

    records = read_source_artifact_content_records(
        run_dir,
        {"source_artifacts": "source_artifacts/index.json"},
    )
    bundle = WorkflowRunInspector().build_replay_content_bundle(run_dir=run_dir)

    assert records[0].artifact_key == "source_artifact.source_item.feed_source.item-1"
    assert records[0].metadata["source_artifact"] is True
    assert records[0].content["item"]["metadata"]["api_key"] == "[redacted]"
    assert bundle.artifact_by_key("source_artifact.source_item.feed_source.item-1") is not None


def test_workflow_run_catalog_lists_filters_and_finds_latest(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="catalog-success")

    functions = FunctionStepRegistry()
    functions.register(
        "sample.fail",
        lambda buffer: (_ for _ in ()).throw(RuntimeError("step failed")),
    )
    failing_executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )
    failing_executor.execute(
        WorkflowSpec(
            workflow_id="catalog-failed",
            name="Catalog Failed",
            version="1.0",
            start_step_id="fail",
            steps=[
                StepSpec(
                    step_id="fail",
                    implementation="sample.fail",
                    write_keys=["report"],
                )
            ],
        ),
        {},
        profile="test",
        run_id="catalog-failed",
    )
    invalid_dir = tmp_path / "invalid-run"
    invalid_dir.mkdir()
    (invalid_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    catalog = list_workflow_runs(tmp_path)
    latest = latest_workflow_run(tmp_path)
    failed_only = WorkflowRunInspector(tmp_path).list_runs(status=WorkflowStatus.FAILED)
    with_invalid = WorkflowRunInspector(tmp_path).list_runs(include_invalid=True, limit=None)

    assert {run.run_id for run in catalog.runs} == {"catalog-success", "catalog-failed"}
    assert catalog.status_counts == {"failed": 1, "succeeded": 1}
    assert catalog.workflow_counts == {"catalog-failed": 1, "inspect-sample": 1}
    assert "invalid-run" in " ".join(catalog.invalid_run_dirs)
    assert latest.run_id in {"catalog-success", "catalog-failed"}
    assert [run.run_id for run in failed_only.runs] == ["catalog-failed"]
    assert with_invalid.by_run_id("invalid-run").valid_manifest is False
    assert workflow_run_catalog_summary(catalog)["run_count"] == 2


def test_workflow_run_catalog_health_groups_unhealthy_runs(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="health-success")

    functions = FunctionStepRegistry()
    functions.register(
        "sample.fail",
        lambda buffer: (_ for _ in ()).throw(RuntimeError("step failed")),
    )
    failing_executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )
    failing_executor.execute(
        WorkflowSpec(
            workflow_id="health-failed",
            name="Health Failed",
            version="1.0",
            start_step_id="fail",
            steps=[
                StepSpec(
                    step_id="fail",
                    implementation="sample.fail",
                    write_keys=["report"],
                )
            ],
        ),
        {},
        profile="test",
        run_id="health-failed",
    )
    invalid_dir = tmp_path / "health-invalid"
    invalid_dir.mkdir()
    (invalid_dir / "manifest.json").write_text("{not-json", encoding="utf-8")

    catalog = list_workflow_runs(tmp_path, include_invalid=True, limit=None)
    health = build_run_catalog_health(catalog)
    direct_health = workflow_run_catalog_health(tmp_path)

    assert health.severity == "error"
    assert health.healthy is False
    assert health.invalid_run_count == 1
    assert health.failed_count == 1
    assert health.latest_successful_run_id in {"health-success", None}
    assert failed_run_items(catalog)[0].run_id == "health-failed"
    assert invalid_run_items(catalog)[0].run_id == "health-invalid"
    assert unhealthy_run_items(catalog)
    assert catalog_runs_by_status(catalog, WorkflowStatus.SUCCEEDED)[0].run_id == "health-success"
    assert catalog_runs_by_workflow(catalog, "inspect-sample")[0].run_id == "health-success"
    assert paused_run_items(catalog) == []
    assert workflow_run_catalog_health_summary(health)["invalid_run_count"] == 1
    assert direct_health.invalid_run_count == 1


def test_workflow_run_catalog_respects_offset_and_limit(tmp_path) -> None:
    executor = _sample_executor(tmp_path)
    executor.execute(_sample_spec(), {"topic": "one"}, profile="test", run_id="catalog-one")
    executor.execute(_sample_spec(), {"topic": "two"}, profile="test", run_id="catalog-two")
    executor.execute(_sample_spec(), {"topic": "three"}, profile="test", run_id="catalog-three")

    catalog = WorkflowRunInspector(tmp_path).list_runs(limit=1, offset=1)

    assert catalog.total_run_count == 3
    assert catalog.returned_run_count == 1
    assert len(catalog.runs) == 1
    assert catalog.filters["limit"] == 1
    assert catalog.filters["offset"] == 1


def test_workflow_run_comparison_reports_step_and_output_changes(tmp_path) -> None:
    functions = FunctionStepRegistry()
    functions.register("sample.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})
    functions.register("sample.write", lambda buffer: {"report": f"Report: {buffer.read('plan')}"})
    functions.register(
        "sample.write.v2",
        lambda buffer: {
            "report": f"Report: {buffer.read('plan')}",
            "summary": f"Summary: {buffer.read('plan')}",
        },
    )
    executor = WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )
    executor.execute(_sample_spec(), {"topic": "ai"}, profile="test", run_id="compare-base")
    executor.execute(
        _sample_spec(
            version="2.0",
            write_implementation="sample.write.v2",
            write_keys=["report", "summary"],
            write_required_output_keys=["report", "summary"],
        ),
        {"topic": "ai"},
        profile="test",
        run_id="compare-target",
    )

    comparison = compare_workflow_runs(tmp_path, "compare-base", "compare-target", strict=True)
    direct_comparison = compare_workflow_run_inspections(
        inspect_workflow_run(tmp_path / "compare-base", strict=True),
        inspect_workflow_run(tmp_path / "compare-target", strict=True),
    )

    assert comparison.same_workflow is True
    assert comparison.status_changed is False
    assert comparison.workflow_version_changed is True
    assert comparison.added_output_keys == {"write": ["summary"]}
    assert comparison.has_behavioral_change is True
    assert comparison.to_dict()["target_workflow_version"] == "2.0"
    assert workflow_run_comparison_summary(comparison)["has_behavioral_change"] is True
    assert direct_comparison.added_output_keys == comparison.added_output_keys


def test_workflow_runner_exposes_run_catalog_and_compare(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})
    registry.register("sample.write", lambda buffer: {"report": f"Report: {buffer.read('plan')}"})
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)

    runner.run(_sample_spec(), {"topic": "ai"}, profile="test", run_id="runner-catalog-a")
    runner.run(_sample_spec(), {"topic": "ml"}, profile="test", run_id="runner-catalog-b")

    catalog = runner.list_runs(workflow_id="inspect-sample")
    latest = runner.latest_run(workflow_id="inspect-sample")
    health = runner.catalog_health(workflow_id="inspect-sample")
    comparison = runner.compare_runs("runner-catalog-a", "runner-catalog-b", strict=True)

    assert catalog.total_run_count == 2
    assert latest.run_id in {"runner-catalog-a", "runner-catalog-b"}
    assert health.severity == "ok"
    assert comparison.same_workflow is True
    assert comparison.status_changed is False


def test_workflow_run_inspector_rejects_run_id_path_traversal(tmp_path) -> None:
    inspector = WorkflowRunInspector(tmp_path)

    with pytest.raises(WorkflowRunInspectionError, match="artifact root"):
        inspector.inspect_run("../outside")
    with pytest.raises(WorkflowRunInspectionError, match="artifact root"):
        resolve_run_dir(tmp_path, "../outside")


def test_workflow_runner_exposes_inspection_and_replay_bundle(tmp_path) -> None:
    registry = FunctionStepRegistry()
    registry.register("sample.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})
    registry.register("sample.write", lambda buffer: {"report": f"Report: {buffer.read('plan')}"})
    runner = WorkflowRunner(artifact_root=tmp_path, function_registry=registry)

    result = runner.run(_sample_spec(), {"topic": "ai"}, profile="test", run_id="runner-inspect")

    inspection = runner.inspect_run("runner-inspect", strict=True)
    replay_bundle = runner.build_replay_bundle("runner-inspect", strict=True)
    replay_content_bundle = runner.build_replay_content_bundle("runner-inspect")
    diagnostics = runner.inspect_run_diagnostics("runner-inspect", strict=True)
    health = runner.inspect_run_health("runner-inspect", strict=True)

    assert result.status == WorkflowStatus.SUCCEEDED
    assert inspection.run_id == "runner-inspect"
    assert inspection.step_by_id("write").succeeded is True
    assert replay_bundle.output["report"] == "Report: ai"
    assert replay_content_bundle.artifact_by_key("output").content["report"] == "Report: ai"
    assert diagnostics.healthy is True
    assert health.severity == "ok"


def _sample_spec(
    *,
    version: str = "1.0",
    write_implementation: str = "sample.write",
    write_keys: list[str] | None = None,
    write_required_output_keys: list[str] | None = None,
) -> WorkflowSpec:
    write_keys = write_keys or ["report"]
    write_required_output_keys = write_required_output_keys or ["report"]
    return WorkflowSpec(
        workflow_id="inspect-sample",
        name="Inspect Sample",
        version=version,
        start_step_id="plan",
        steps=[
            StepSpec(
                step_id="plan",
                implementation="sample.plan",
                read_keys=["request"],
                write_keys=["plan"],
                required_output_keys=["plan"],
            ),
            StepSpec(
                step_id="write",
                implementation=write_implementation,
                read_keys=["plan"],
                write_keys=write_keys,
                required_output_keys=write_required_output_keys,
            ),
        ],
        edges=[
            EdgeSpec("plan-to-write", "plan", "write"),
        ],
    )


def _sample_executor(tmp_path) -> WorkflowExecutor:
    functions = FunctionStepRegistry()
    functions.register("sample.plan", lambda buffer: {"plan": buffer.read("request")["topic"]})
    functions.register("sample.write", lambda buffer: {"report": f"Report: {buffer.read('plan')}"})
    return WorkflowExecutor(
        function_step_runner=FunctionStepRunner(functions),
        artifact_manager=ArtifactManager(tmp_path),
    )
