from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from interfaces.services.board_service import BoardWorkflowApplicationService
from tests.business.final_runtime_fixtures import sample_raw_items


FORBIDDEN_FIELD_NAMES = {
    "raw_payload",
    "raw_content",
    "raw_html",
    "full_text",
    "secret",
    "api_key",
    "token",
}


def test_final_business_run_outputs_do_not_expose_raw_or_secret_fields() -> None:
    final_run = BoardWorkflowApplicationService().build_final_business_run(sample_raw_items())
    surfaces = [
        ("final_run", final_run),
        ("final_run.model_dump", final_run.model_dump(mode="json", exclude_none=True)),
        ("cross_board_result", final_run.cross_board_result),
        ("quality_summary", final_run.quality_summary),
        ("artifacts", [artifact.metadata for artifact in final_run.artifacts]),
        ("feedback_events", final_run.feedback_events),
        ("learning_signals", final_run.learning_signals),
        ("policy_candidates", final_run.policy_candidates),
        ("regression_guard_results", final_run.regression_guard_results),
        *[
            (f"workflow_result.{board_type}", workflow_result)
            for board_type, workflow_result in final_run.board_workflow_results.items()
        ],
        *[
            (f"artifact.{artifact.artifact_id}", artifact)
            for artifact in final_run.artifacts
        ],
        *[
            (f"board_card.{board_type}.{card.card_id}", card)
            for board_type, workflow_result in final_run.board_workflow_results.items()
            for card in workflow_result.result.cards
        ],
        *[(f"cross_board_path.{path.path_id}", path) for path in final_run.cross_board_paths],
        *[(f"cross_board_insight.{candidate.candidate_id}", candidate) for candidate in final_run.cross_board_insights],
    ]

    violations: list[str] = []
    for label, surface in surfaces:
        violations.extend(_forbidden_paths(surface, root=label))

    assert violations == []


def _forbidden_paths(value: Any, *, root: str) -> list[str]:
    payload = _to_plain(value)
    violations: list[str] = []
    _walk(payload, path=root, violations=violations)
    return violations


def _walk(value: Any, *, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}"
            if key_text.casefold() in FORBIDDEN_FIELD_NAMES:
                violations.append(next_path)
            _walk(item, path=next_path, violations=violations)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, path=f"{path}[{index}]", violations=violations)


def _to_plain(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        return value
    if isinstance(value, list | tuple):
        return [_to_plain(item) for item in value]
    return value
