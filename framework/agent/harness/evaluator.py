from __future__ import annotations

from typing import Any

from framework.agent.harness.scenario import AgentHarnessScenario
from framework.agent.models import AgentLoopResult


class AgentHarnessEvaluator:
    def evaluate(
        self,
        result: AgentLoopResult,
        scenario: AgentHarnessScenario | None = None,
    ) -> dict[str, Any]:
        expected = dict(scenario.expected) if scenario else {}
        expected_status = expected.get("status")
        expected_output_keys = [str(key) for key in expected.get("output_keys", [])]
        issues: list[str] = []
        if expected_status is not None and result.status.value != str(expected_status):
            issues.append(f"expected status {expected_status}, got {result.status.value}")
        missing_output_keys = [key for key in expected_output_keys if key not in result.output]
        if missing_output_keys:
            issues.append(f"missing output keys: {', '.join(missing_output_keys)}")
        return {
            "passed": not issues and result.success,
            "issues": issues,
            "status": result.status.value,
            "iterations": result.iterations,
        }
