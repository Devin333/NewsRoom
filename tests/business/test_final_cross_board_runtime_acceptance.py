from __future__ import annotations

import json
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


def test_final_cross_board_runtime_acceptance() -> None:
    result = BoardWorkflowApplicationService().build_final_business_run(sample_raw_items())

    assert result.cross_board_graph.nodes
    assert result.cross_board_paths
    assert all(path.metadata.get("scoring_result") for path in result.cross_board_paths)
    assert result.cross_board_insights
    assert all(insight.metadata.get("scoring_result") for insight in result.cross_board_insights)

    payload = {
        "cross_board_result": result.cross_board_result.model_dump(mode="json", exclude_none=True),
        "cross_board_graph": _to_plain(result.cross_board_graph),
        "cross_board_paths": _to_plain(result.cross_board_paths),
        "cross_board_insights": _to_plain(result.cross_board_insights),
        "metadata": _to_plain(result.metadata),
    }
    json.dumps(payload, ensure_ascii=False, sort_keys=True)
    assert _forbidden_paths(payload) == []


def _forbidden_paths(value: Any, *, root: str = "payload") -> list[str]:
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
    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump(mode="json", exclude_none=True)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items()}
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        return value
    if isinstance(value, list | tuple):
        return [_to_plain(item) for item in value]
    return value
