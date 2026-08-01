"""Compatibility names for the TaskPlan capability authority.

The implementation lives in ``capability`` so candidate validation and runtime
binding cannot drift into separate registries.
"""

from framework.harness.task_plan.capability import (
    ResolvedCapabilityBinding,
    ResolvedSubAgentTaskAdapter,
    TaskCapabilityRegistration,
    TaskCapabilityRegistry,
)


TaskPlanWorkerBinding = TaskCapabilityRegistration
TaskPlanCapabilityRegistry = TaskCapabilityRegistry


__all__ = [
    "ResolvedCapabilityBinding",
    "ResolvedSubAgentTaskAdapter",
    "TaskCapabilityRegistration",
    "TaskCapabilityRegistry",
    "TaskPlanCapabilityRegistry",
    "TaskPlanWorkerBinding",
]
