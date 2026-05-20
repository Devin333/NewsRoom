from __future__ import annotations

from framework.shared.errors import (
    BoundaryViolationError,
    ConfigurationError,
    DependencyError,
    FrameworkError,
    RuntimeExecutionError,
    ValidationError,
)


def test_framework_error_converts_to_error_detail() -> None:
    error = FrameworkError("bad runtime", code="bad_runtime", details={"run_id": "run-1"})

    detail = error.to_error_detail()

    assert detail.code == "bad_runtime"
    assert detail.message == "bad runtime"
    assert detail.details == {"run_id": "run-1"}


def test_error_subclasses_keep_framework_error_behavior() -> None:
    for error_type in [
        ValidationError,
        ConfigurationError,
        DependencyError,
        RuntimeExecutionError,
        BoundaryViolationError,
    ]:
        error = error_type("message")
        assert isinstance(error, FrameworkError)
        assert error.to_error_detail().message == "message"
