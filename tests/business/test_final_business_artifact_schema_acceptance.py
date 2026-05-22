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


def test_final_business_artifact_schema_acceptance() -> None:
    result = BoardWorkflowApplicationService().build_final_business_run(sample_raw_items())

    assert result.artifacts
    assert result.metadata["artifact_count"] == len(result.artifacts)
    assert result.model_dump(mode="json", exclude_none=True)

    serialized = []
    for artifact in result.artifacts:
        payload = artifact.model_dump(mode="json", exclude_none=True)
        serialized.append(payload)
        assert payload["artifact_id"]
        assert payload["artifact_type"]
        assert payload["run_id"]
        assert payload["metadata"]["board_type"]
        assert payload["metadata"]["run_id"] == payload["run_id"]
        assert payload["metadata"]["artifact_type"] == payload["artifact_type"]

    assert _forbidden_paths(serialized) == []


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
