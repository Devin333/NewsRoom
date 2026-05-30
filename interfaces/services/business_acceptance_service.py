from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone as _tz
UTC = _tz.utc
from pathlib import Path
from typing import Any
from uuid import uuid4

from framework.specs import WorkflowStatus

from business.boards._artifact_publisher import BOARD_ARTIFACTS
from business.boards.final_runtime_fixtures import sample_raw_items
from business.boards._runner import runner_for_board_type
from business.boards.cross_board.intelligence_service import CrossBoardIntelligenceService
from business.boards.cross_board.profiles import LEGACY_DAILY_WORKFLOW_ID
from business.boards.cross_board.workflows.weekly_intelligence.runner import WeeklyIntelligenceRunner
from business.evaluation import BoardEvalRunner, board_eval_cases
from interfaces.services.board_service import BoardWorkflowApplicationService
from interfaces.models.business_acceptance import AcceptanceCheck, AcceptanceResult


BOARD_TYPES = ("ai_news", "project_radar", "paper_radar", "community_pulse")
BOARD_TOPICS = {
    "ai_news": "Agent Memory",
    "project_radar": "Agent Memory",
    "paper_radar": "Agent Memory",
    "community_pulse": "Agent Memory",
}
REQUIRED_BOARD_ARTIFACTS = (
    "request.json",
    "workflow_spec.json",
    "output.json",
    "manifest.json",
    "board_output.json",
    "cards.json",
    "detail_pages.json",
    "insights.json",
    "quality_summary.json",
    "subscription_payload.json",
    "feedback_events.json",
    "learning_signals.json",
    "improvement_recommendations.json",
    "improvement_proposals.json",
    "applied_overrides.json",
    "improvement_measurement.json",
    "summary.md",
)
WEEKLY_ARTIFACTS = (
    "weekly_trends.json",
    "weekly_timeline.json",
    "weekly_quality.json",
    "weekly_subscription_payload.json",
    "weekly_improvement_report.json",
)
FORBIDDEN_PUBLIC_FIELD_NAMES = {
    "raw_payload",
    "raw_content",
    "raw_html",
    "full_text",
    "secret",
    "api_key",
    "token",
}


class BusinessAcceptanceService:
    def run_final_business_acceptance(
        self,
        *,
        artifact_root: str | Path | None = None,
        run_id: str | None = None,
    ) -> AcceptanceResult:
        resolved_run_id = run_id or f"accept-final-{_short_id()}"
        checks: list[AcceptanceCheck] = []
        try:
            final_run = BoardWorkflowApplicationService().build_final_business_run(sample_raw_items())
            dumped = final_run.model_dump(mode="json", exclude_none=True)
            forbidden_paths = _forbidden_paths(dumped)
            artifact_refs = list(final_run.artifacts)
            artifact_payloads = [_plain(artifact) for artifact in artifact_refs]
            artifact_metadata_ok = all(
                isinstance(payload, dict)
                and payload.get("artifact_type")
                and payload.get("run_id")
                and isinstance(payload.get("metadata"), dict)
                and payload["metadata"].get("board_type")
                and payload["metadata"].get("run_id")
                and payload["metadata"].get("artifact_type")
                for payload in artifact_payloads
            )
            checks.extend(
                [
                    _check(
                        "final_business_run_surface",
                        "final business",
                        set(final_run.board_workflow_results) == set(BOARD_TYPES)
                        and final_run.cross_board_graph == final_run.cross_board_result.graph
                        and final_run.cross_board_paths == final_run.cross_board_result.paths
                        and final_run.cross_board_insights == final_run.cross_board_result.insights,
                        "final business run exposes expected public surfaces",
                        {"board_count": len(final_run.board_workflow_results)},
                    ),
                    _check(
                        "no_raw_payload",
                        "raw payload safety",
                        not forbidden_paths,
                        "final business run serialization contains no forbidden raw or secret field names",
                        {"violations": forbidden_paths},
                    ),
                    _check(
                        "four_board_workflows",
                        "final business",
                        len(final_run.board_workflow_results) == 4
                        and all(result.result.cards for result in final_run.board_workflow_results.values()),
                        "final business run contains four populated board workflows",
                        {"boards": sorted(final_run.board_workflow_results)},
                    ),
                    _check(
                        "cross_board_graph",
                        "cross-board",
                        bool(final_run.cross_board_graph.nodes),
                        "cross-board graph has nodes",
                        {"node_count": len(final_run.cross_board_graph.nodes)},
                    ),
                    _check(
                        "cross_board_paths",
                        "cross-board",
                        bool(final_run.cross_board_paths)
                        and all(path.metadata.get("scoring_result") for path in final_run.cross_board_paths),
                        "cross-board paths are present and scored",
                        {"path_count": len(final_run.cross_board_paths)},
                    ),
                    _check(
                        "cross_board_insights",
                        "cross-board",
                        bool(final_run.cross_board_insights)
                        and all(insight.metadata.get("scoring_result") for insight in final_run.cross_board_insights),
                        "cross-board insights are present and scored",
                        {"insight_count": len(final_run.cross_board_insights)},
                    ),
                    _check(
                        "feedback_events",
                        "feedback",
                        bool(final_run.feedback_events),
                        "feedback events are present",
                        {"feedback_count": len(final_run.feedback_events)},
                    ),
                    _check(
                        "learning_signals",
                        "feedback",
                        bool(final_run.learning_signals),
                        "learning signals are present",
                        {"learning_signal_count": len(final_run.learning_signals)},
                    ),
                    _check(
                        "policy_candidates",
                        "policy",
                        bool(final_run.policy_candidates),
                        "policy candidates are present",
                        {"policy_candidate_count": len(final_run.policy_candidates)},
                    ),
                    _check(
                        "regression_guards",
                        "quality",
                        bool(final_run.regression_guard_results),
                        "regression guard results are present",
                        {"guard_result_count": len(final_run.regression_guard_results)},
                    ),
                    _check(
                        "artifacts_present",
                        "artifacts",
                        bool(artifact_refs)
                        and final_run.metadata.get("artifact_count") == len(artifact_refs)
                        and artifact_metadata_ok
                        and not _forbidden_paths(artifact_payloads),
                        "artifact refs are present, counted, serializable, and metadata-complete",
                        {
                            "artifact_count": len(artifact_refs),
                            "metadata_artifact_count": final_run.metadata.get("artifact_count"),
                        },
                    ),
                    _check(
                        "serializable_model_dump",
                        "serialization",
                        isinstance(dumped, dict) and bool(dumped),
                        "final business run model_dump(mode='json') is serializable",
                        {"top_level_keys": sorted(dumped)[:20]},
                    ),
                ]
            )
        except Exception as exc:
            checks.append(
                _check(
                    "final_business_run_surface",
                    "final business",
                    False,
                    f"final business acceptance failed: {type(exc).__name__}: {exc}",
                    {"run_id": resolved_run_id},
                )
            )
        return AcceptanceResult.from_checks(
            run_id=resolved_run_id,
            checks=checks,
            artifact_root=str(artifact_root) if artifact_root is not None else None,
            summary={"area": "final-business"},
        )

    def run_board_acceptance(
        self,
        board_type: str,
        *,
        artifact_root: str | Path = ".newsroom/acceptance",
        run_id: str | None = None,
    ) -> AcceptanceResult:
        normalized = _normalize_board_type(board_type)
        root = Path(artifact_root)
        resolved_run_id = run_id or f"accept-{normalized}-{_short_id()}"
        checks: list[AcceptanceCheck] = []
        try:
            result = runner_for_board_type(normalized, artifact_root=root).run(
                signals=_signals_for_board(normalized),
                topic=BOARD_TOPICS[normalized],
                run_id=resolved_run_id,
            )
            checks.append(
                _check(
                    "board.run",
                    "board runtime",
                    result.status == WorkflowStatus.SUCCEEDED,
                    f"{normalized} run status is {result.status.value}",
                    {"board_type": normalized, "run_id": result.run_id},
                )
            )
            checks.extend(_board_artifact_checks(normalized, result))
            checks.extend(_board_output_checks(normalized, result))
        except Exception as exc:
            checks.append(
                _check(
                    "board.run",
                    "board runtime",
                    False,
                    f"{normalized} acceptance failed: {type(exc).__name__}: {exc}",
                    {"board_type": normalized, "run_id": resolved_run_id},
                )
            )
        return AcceptanceResult.from_checks(
            run_id=resolved_run_id,
            checks=checks,
            artifact_root=str(root),
            summary={"board_type": normalized},
        )

    def run_all_board_acceptance(
        self,
        *,
        artifact_root: str | Path = ".newsroom/acceptance",
        run_id_prefix: str | None = None,
    ) -> AcceptanceResult:
        root = Path(artifact_root)
        prefix = run_id_prefix or f"accept-all-{_short_id()}"
        results = [
            self.run_board_acceptance(
                board_type,
                artifact_root=root,
                run_id=f"{prefix}-{board_type}",
            )
            for board_type in BOARD_TYPES
        ]
        checks = _prefixed_checks(results)
        return AcceptanceResult.from_checks(
            run_id=prefix,
            checks=checks,
            artifact_root=str(root),
            summary={
                "board_count": len(results),
                "boards": {result.summary.get("board_type"): result.status for result in results},
            },
        )

    def run_cross_board_acceptance(
        self,
        *,
        artifact_root: str | Path = ".newsroom/acceptance",
        run_id: str | None = None,
    ) -> AcceptanceResult:
        root = Path(artifact_root)
        resolved_run_id = run_id or f"accept-cross-board-{_short_id()}"
        checks: list[AcceptanceCheck] = []
        try:
            board_results = _run_productized_boards(root, run_id_prefix=resolved_run_id)
            checks.extend(_board_run_checks(board_results))
            output = CrossBoardIntelligenceService().build(
                {board_type: result.output for board_type, result in board_results.items()},
                topic="Agent Memory",
            )
            required = (
                "cross_board_summary",
                "shared_entities",
                "shared_trends",
                "conflicting_signals",
                "board_coverage",
                "recommendations",
                "subscription_payload",
                "improvement_report",
            )
            for key in required:
                checks.append(
                    _check(
                        f"cross_board.{key}",
                        "cross-board",
                        key in output,
                        f"cross-board output includes {key}",
                        {"key": key},
                    )
                )
            subscription = _dict(output.get("subscription_payload"))
            tags = _subscription_tags(subscription)
            expected_tags = {"ai_news", "github", "paper", "community"}
            checks.append(
                _check(
                    "cross_board.subscription_tags",
                    "cross-board",
                    expected_tags <= set(tags),
                    "cross-board subscription aggregates board tags",
                    {"tags": sorted(tags), "expected_tags": sorted(expected_tags)},
                )
            )
            improvement = _dict(output.get("improvement_report"))
            checks.append(
                _check(
                    "cross_board.improvement",
                    "cross-board",
                    isinstance(improvement.get("recommendations"), list),
                    "cross-board improvement report aggregates recommendations",
                    {"recommendation_count": len(improvement.get("recommendations") or [])},
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "cross_board.run",
                    "cross-board",
                    False,
                    f"cross-board acceptance failed: {type(exc).__name__}: {exc}",
                    {"run_id": resolved_run_id},
                )
            )
        return AcceptanceResult.from_checks(
            run_id=resolved_run_id,
            checks=checks,
            artifact_root=str(root),
            summary={"area": "cross-board"},
        )

    def run_weekly_acceptance(
        self,
        *,
        artifact_root: str | Path = ".newsroom/acceptance",
        run_id: str | None = None,
    ) -> AcceptanceResult:
        root = Path(artifact_root)
        resolved_run_id = run_id or f"accept-weekly-{_short_id()}"
        checks: list[AcceptanceCheck] = []
        try:
            end = datetime(2026, 5, 22, 23, 59, 59, tzinfo=UTC)
            start = end - timedelta(days=7)
            _write_weekly_source_report_fixture(root, "accept-daily-source-1", finished_at=end - timedelta(days=1))
            _write_weekly_source_report_fixture(root, "accept-cross-source-1", finished_at=end - timedelta(days=2))
            result = WeeklyIntelligenceRunner(artifact_root=root).run(
                topic="Agent Memory",
                period_start=start.isoformat().replace("+00:00", "Z"),
                period_end=end.isoformat().replace("+00:00", "Z"),
                source_limit=5,
                run_id=resolved_run_id,
            )
            checks.append(
                _check(
                    "weekly.run",
                    "weekly",
                    result.status == WorkflowStatus.SUCCEEDED,
                    f"weekly run status is {result.status.value}",
                    {"run_id": result.run_id},
                )
            )
            for key in (
                "weekly_trends",
                "weekly_timeline",
                "weekly_quality",
                "weekly_subscription_payload",
                "weekly_improvement_report",
            ):
                checks.append(
                    _check(
                        f"weekly.output.{key}",
                        "weekly",
                        key in result.output,
                        f"weekly output includes {key}",
                        {"key": key},
                    )
                )
            run_dir = _run_dir(result)
            for file_name in WEEKLY_ARTIFACTS:
                checks.append(
                    _check(
                        f"weekly.artifact.{file_name}",
                        "weekly",
                        (run_dir / file_name).exists(),
                        f"weekly artifact exists: {file_name}",
                        {"path": str(run_dir / file_name)},
                    )
                )
        except Exception as exc:
            checks.append(
                _check(
                    "weekly.run",
                    "weekly",
                    False,
                    f"weekly acceptance failed: {type(exc).__name__}: {exc}",
                    {"run_id": resolved_run_id},
                )
            )
        return AcceptanceResult.from_checks(
            run_id=resolved_run_id,
            checks=checks,
            artifact_root=str(root),
            summary={"area": "weekly"},
        )

    def run_eval_acceptance(
        self,
        *,
        artifact_root: str | Path = ".newsroom/acceptance",
        run_id: str | None = None,
    ) -> AcceptanceResult:
        root = Path(artifact_root)
        resolved_run_id = run_id or f"accept-eval-{_short_id()}"
        checks: list[AcceptanceCheck] = []
        try:
            cases = board_eval_cases()
            report = BoardEvalRunner(artifact_root=root / resolved_run_id).run_suite(cases)
            counts_by_board: dict[str, int] = {}
            for case in cases:
                counts_by_board[case.board_type] = counts_by_board.get(case.board_type, 0) + 1
            checks.append(
                _check(
                    "eval.case_count",
                    "eval",
                    len(cases) >= 20 and all(count >= 5 for count in counts_by_board.values()),
                    "eval suite has at least 20 cases and 5 per board",
                    {"case_count": len(cases), "counts_by_board": counts_by_board},
                )
            )
            checks.append(
                _check(
                    "eval.run_suite",
                    "eval",
                    report.case_count == len(cases),
                    "eval suite returned a result for every case",
                    {"case_count": report.case_count},
                )
            )
            checks.append(
                _check(
                    "eval.pass_rate",
                    "eval",
                    0.0 <= report.pass_rate <= 1.0,
                    "eval report exposes pass_rate",
                    {"pass_rate": report.pass_rate, "passed": report.passed},
                )
            )
            unhandled = [
                result.case_id
                for result in report.results
                if result.metrics.get("unhandled_errors")
            ]
            checks.append(
                _check(
                    "eval.unhandled_errors",
                    "eval",
                    not unhandled,
                    "eval suite has no unhandled errors",
                    {"unhandled_cases": unhandled},
                )
            )
        except Exception as exc:
            checks.append(
                _check(
                    "eval.run_suite",
                    "eval",
                    False,
                    f"eval acceptance failed: {type(exc).__name__}: {exc}",
                    {"run_id": resolved_run_id},
                )
            )
        return AcceptanceResult.from_checks(
            run_id=resolved_run_id,
            checks=checks,
            artifact_root=str(root),
            summary={"area": "eval"},
        )

    def run_full_acceptance(
        self,
        *,
        artifact_root: str | Path = ".newsroom/acceptance",
        run_id: str | None = None,
    ) -> AcceptanceResult:
        root = Path(artifact_root)
        resolved_run_id = run_id or f"accept-full-{_short_id()}"
        results = [
            self.run_final_business_acceptance(artifact_root=root, run_id=f"{resolved_run_id}-final"),
            self.run_all_board_acceptance(artifact_root=root, run_id_prefix=f"{resolved_run_id}-boards"),
            self.run_cross_board_acceptance(artifact_root=root, run_id=f"{resolved_run_id}-cross-board"),
            self.run_weekly_acceptance(artifact_root=root, run_id=f"{resolved_run_id}-weekly"),
            self.run_eval_acceptance(artifact_root=root, run_id=f"{resolved_run_id}-eval"),
        ]
        return AcceptanceResult.from_checks(
            run_id=resolved_run_id,
            checks=_prefixed_checks(results),
            artifact_root=str(root),
            summary={"areas": {result.run_id: result.status for result in results}},
        )


def _board_artifact_checks(board_type: str, result: Any) -> list[AcceptanceCheck]:
    checks: list[AcceptanceCheck] = []
    run_dir = _run_dir(result)
    manifest = _read_json(run_dir / "manifest.json")
    metadata = _dict(manifest.get("business_productization"))
    checks.append(
        _check(
            "artifact.metadata",
            "artifacts",
            metadata.get("board_type") == board_type
            and metadata.get("run_id") == result.run_id
            and bool(metadata.get("schema_version")),
            "manifest includes productized artifact metadata",
            {"metadata": metadata},
        )
    )
    for file_name in REQUIRED_BOARD_ARTIFACTS:
        path = run_dir / file_name
        exists = path.exists()
        checks.append(
            _check(
                f"artifact.exists.{file_name}",
                "artifacts",
                exists,
                f"artifact exists: {file_name}",
                {"path": str(path)},
            )
        )
        if exists and file_name.endswith(".json"):
            try:
                payload = _read_json(path)
                parse_ok = isinstance(payload, (dict, list))
            except json.JSONDecodeError:
                parse_ok = False
            checks.append(
                _check(
                    f"artifact.parse.{file_name}",
                    "artifacts",
                    parse_ok,
                    f"artifact JSON parses: {file_name}",
                    {"path": str(path)},
                )
            )
        if exists and file_name == "summary.md":
            checks.append(
                _check(
                    "artifact.summary_md",
                    "artifacts",
                    path.read_text(encoding="utf-8").strip() != "",
                    "summary.md is non-empty",
                    {"path": str(path)},
                )
            )
    missing_from_manifest = [
        key
        for key, file_name in BOARD_ARTIFACTS.items()
        if _dict(manifest.get("artifacts")).get(key) != file_name
    ]
    checks.append(
        _check(
            "artifact.manifest_refs",
            "artifacts",
            not missing_from_manifest,
            "manifest references productized board artifacts",
            {"missing_keys": missing_from_manifest},
        )
    )
    return checks


def _board_output_checks(board_type: str, result: Any) -> list[AcceptanceCheck]:
    output = _dict(result.output)
    board_output = _dict(output.get("board_output"))
    quality = _dict(output.get("quality_summary"))
    subscription = _dict(output.get("subscription_payload"))
    improvement_proposals = _list(output.get("improvement_proposals"))
    checks = [
        _check(
            "board_output.board_type",
            "board runtime",
            board_output.get("board_type") == board_type,
            "board output has the requested board_type",
            {"board_type": board_output.get("board_type")},
        ),
        _check(
            "subscription.targets",
            "subscription",
            bool(subscription.get("targets")),
            "subscription payload has targets",
            {"target_count": len(subscription.get("targets") or [])},
        ),
        _check(
            "subscription.ready",
            "subscription",
            bool(_dict(subscription.get("delivery_hints")).get("subscription_ready")),
            "subscription payload is ready",
            {"delivery_hints": subscription.get("delivery_hints")},
        ),
        _check(
            "quality.score_status",
            "artifacts",
            quality.get("score") is not None and bool(quality.get("status")),
            "quality summary has score and status",
            {"score": quality.get("score"), "status": quality.get("status")},
        ),
        _check(
            "skills.trace",
            "board runtime",
            _has_skill_trace(output),
            "board output includes skill trace metadata",
            {"skill_trace_count": len(output.get("skill_traces") or [])},
        ),
        _check(
            "feedback.events",
            "feedback",
            isinstance(output.get("feedback_events"), list),
            "feedback events are present",
            {"feedback_count": len(output.get("feedback_events") or [])},
        ),
        _check(
            "improvement.trace",
            "improvement",
            isinstance(output.get("learning_signals"), list)
            and isinstance(output.get("improvement_recommendations"), list)
            and isinstance(improvement_proposals, list)
            and isinstance(output.get("improvement_measurement"), dict),
            "improvement trace artifacts are present",
            {
                "learning_signal_count": len(output.get("learning_signals") or []),
                "recommendation_count": len(output.get("improvement_recommendations") or []),
                "proposal_count": len(improvement_proposals),
            },
        ),
        _check(
            "improvement.proposal_status",
            "improvement",
            all(isinstance(item, dict) and item.get("status") for item in improvement_proposals),
            "improvement proposals expose status when present",
            {"proposal_count": len(improvement_proposals)},
        ),
    ]
    return checks


def _run_productized_boards(root: Path, *, run_id_prefix: str) -> dict[str, Any]:
    return {
        board_type: runner_for_board_type(board_type, artifact_root=root).run(
            signals=_signals_for_board(board_type),
            topic=BOARD_TOPICS[board_type],
            run_id=f"{run_id_prefix}-{board_type}",
        )
        for board_type in BOARD_TYPES
    }


def _board_run_checks(results: dict[str, Any]) -> list[AcceptanceCheck]:
    return [
        _check(
            f"board.{board_type}.run",
            "board runtime",
            result.status == WorkflowStatus.SUCCEEDED,
            f"{board_type} run status is {result.status.value}",
            {"board_type": board_type, "run_id": result.run_id},
        )
        for board_type, result in results.items()
    ]


def _prefixed_checks(results: Iterable[AcceptanceResult]) -> list[AcceptanceCheck]:
    checks: list[AcceptanceCheck] = []
    for result in results:
        for check in result.checks:
            checks.append(
                AcceptanceCheck(
                    check_id=f"{result.run_id}.{check.check_id}",
                    area=check.area,
                    passed=check.passed,
                    message=check.message,
                    metadata={**dict(check.metadata), "parent_run_id": result.run_id},
                )
            )
    return checks


def _write_weekly_source_report_fixture(root: Path, run_id: str, *, finished_at: datetime) -> None:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    finished = finished_at.isoformat().replace("+00:00", "Z")
    report = {
        "title": "Daily Intelligence: Agent Memory",
        "source_urls": ["https://example.com/agent-memory"],
        "sections": [
            {
                "title": "Executive Summary",
                "content": "Agent Memory appeared across OpenAI, LangChain, and community signals.",
                "sources": ["https://example.com/agent-memory"],
            }
        ],
        "metadata": {
            "topic": "Agent Memory",
            "quality_score": 0.82,
            "subscription_payload": {
                "targets": [
                    {
                        "board_type": "cross_board",
                        "topic": "Agent Memory",
                        "tags": ["ai_news", "github", "paper", "community"],
                        "entities": ["OpenAI", "LangChain", "Agent Memory"],
                        "source_types": ["rss", "github", "arxiv", "hackernews"],
                        "priority": "normal",
                    }
                ]
            },
        },
    }
    manifest = {
        "run_id": run_id,
        "workflow_id": LEGACY_DAILY_WORKFLOW_ID,
        "workflow_version": "0.1.0",
        "profile": "live-offline",
        "status": "succeeded",
        "finished_at": finished,
        "quality_score": 0.82,
        "artifacts": {"report_json": "report.json", "report_markdown": "report.md"},
    }
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text("# Daily Intelligence: Agent Memory\n\nOffline acceptance fixture.\n", encoding="utf-8")
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _signals_for_board(board_type: str) -> list[dict[str, Any]]:
    signal_type = {
        "ai_news": "ai_news",
        "project_radar": "github_project",
        "paper_radar": "paper",
        "community_pulse": "community_discussion",
    }[board_type]
    source_types = {
        "ai_news": ("official_blog", "rss", "web_page"),
        "project_radar": ("github", "hackernews", "devto"),
        "paper_radar": ("arxiv", "paper_index", "arxiv"),
        "community_pulse": ("reddit", "hackernews", "stackoverflow"),
    }[board_type]
    return [
        _signal(signal_type, 1, title="OpenAI Agent Memory product update", source_type=source_types[0], reliability="high"),
        _signal(signal_type, 2, title="OpenAI Agent Memory product update", source_type=source_types[1], reliability="high"),
        _signal(signal_type, 3, title="Sparse Agent Memory workflow note", source_type=source_types[2], reliability="medium", sparse=True),
        _signal(signal_type, 4, title="Low quality Agent Memory rumor", source_type=source_types[2], reliability="low"),
        _signal(signal_type, 5, title="LangChain and OpenAI Agent Memory integration", source_type=source_types[0], reliability="high"),
        _signal("ai_news" if signal_type != "ai_news" else "paper", 99, title="Irrelevant mixed signal", source_type="manual", reliability="low"),
    ]


def _signal(
    signal_type: str,
    index: int,
    *,
    title: str,
    source_type: str,
    reliability: str,
    sparse: bool = False,
) -> dict[str, Any]:
    summary = (
        "OpenAI, LangChain, LlamaIndex, RAG, MCP, and Agent Memory are referenced in this offline acceptance signal."
        if not sparse
        else "Agent Memory short note."
    )
    authority = {"high": 0.92, "medium": 0.65, "low": 0.25}.get(reliability, 0.5)
    return {
        "source_item_id": f"{signal_type}-{index}",
        "source_id": f"{source_type}-source-{index}",
        "source_name": f"{source_type.title()} Source",
        "source_type": source_type,
        "signal_type": signal_type,
        "title": title,
        "summary": summary,
        "content": summary,
        "url": f"https://example.com/{signal_type}/{index}",
        "language": "en",
        "authors": ["Acceptance Fixture"],
        "tags": ["agent memory", "subscription", signal_type],
        "fetched_at": "2026-05-19T01:00:00Z",
        "published_at": "2026-05-19T00:00:00Z",
        "metadata": {
            "source_reliability": reliability,
            "source_authority_score": authority,
            "fixture_kind": "business_runtime_acceptance",
        },
    }


def _normalize_board_type(value: str) -> str:
    normalized = str(value).strip().lower().replace("-", "_")
    if normalized not in BOARD_TYPES:
        raise ValueError(f"unsupported board_type: {value}")
    return normalized


def _run_dir(result: Any) -> Path:
    if result.artifact_dir:
        return Path(result.artifact_dir)
    return Path(result.manifest_path or "").parent


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _subscription_tags(payload: dict[str, Any]) -> set[str]:
    tags: set[str] = set()
    for target in payload.get("targets") or []:
        if isinstance(target, dict):
            tags.update(str(tag) for tag in target.get("tags") or [])
    return tags


def _has_skill_trace(output: dict[str, Any]) -> bool:
    if output.get("skill_traces"):
        return True
    quality = _dict(output.get("quality_summary"))
    if quality.get("skill_trace_metadata"):
        return True
    metadata = _dict(_dict(output.get("board_output")).get("metadata"))
    return bool(metadata.get("skill_trace_metadata"))


def _forbidden_paths(value: Any, *, root: str = "payload") -> list[str]:
    violations: list[str] = []
    _walk_forbidden(_plain(value), path=root, violations=violations)
    return violations


def _walk_forbidden(value: Any, *, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}"
            if key_text.casefold() in FORBIDDEN_PUBLIC_FIELD_NAMES:
                violations.append(next_path)
            _walk_forbidden(item, path=next_path, violations=violations)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, path=f"{path}[{index}]", violations=violations)


def _plain(value: Any) -> Any:
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json", exclude_none=True)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _check(
    check_id: str,
    area: str,
    passed: bool,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> AcceptanceCheck:
    return AcceptanceCheck(
        check_id=check_id,
        area=area,
        passed=bool(passed),
        message=message,
        metadata=dict(metadata or {}),
    )


def _short_id() -> str:
    return uuid4().hex[:8]


__all__ = ["BOARD_TYPES", "BusinessAcceptanceService", "REQUIRED_BOARD_ARTIFACTS", "WEEKLY_ARTIFACTS"]
