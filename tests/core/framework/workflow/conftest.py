from __future__ import annotations

import pytest

from core.framework.workflow import FunctionStepRegistry


@pytest.fixture
def workflow_function_registry() -> FunctionStepRegistry:
    return FunctionStepRegistry()


@pytest.fixture
def workflow_request() -> dict[str, str]:
    return {"topic": "contract"}
