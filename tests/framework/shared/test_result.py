from __future__ import annotations

import pytest

from framework.shared import ErrorDetail, Result
from framework.shared.errors import RuntimeExecutionError


def test_error_detail_serializes_and_can_be_built_from_exception() -> None:
    error = ErrorDetail.from_exception(ValueError("bad"), code="bad_value")

    assert error.to_dict() == {
        "code": "bad_value",
        "message": "bad",
        "details": {"type": "ValueError"},
    }


def test_result_success_unwraps_and_serializes() -> None:
    result = Result.success({"ok": True}, warnings=["minor"])

    assert result.unwrap() == {"ok": True}
    assert result.to_dict()["warnings"] == ["minor"]


def test_result_failure_raises_framework_error_on_unwrap() -> None:
    result = Result.failure("failed", "it failed", details={"step": "x"})

    with pytest.raises(RuntimeExecutionError) as exc_info:
        result.unwrap()

    assert exc_info.value.code == "failed"
    assert result.to_dict()["error"] == {
        "code": "failed",
        "message": "it failed",
        "details": {"step": "x"},
    }
