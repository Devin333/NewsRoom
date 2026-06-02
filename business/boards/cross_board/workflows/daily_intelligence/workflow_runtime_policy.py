from __future__ import annotations

from framework.specs import WorkflowPolicySpec


DAILY_WORKFLOW_TIMEOUT_SECONDS = 30 * 60.0


def daily_workflow_runtime_policy() -> WorkflowPolicySpec:
    return WorkflowPolicySpec(
        timeout={"timeout_seconds": DAILY_WORKFLOW_TIMEOUT_SECONDS},
    )
