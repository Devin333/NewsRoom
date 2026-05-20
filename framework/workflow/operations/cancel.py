"""Cancel-run operation facade."""

from framework.workflow.operations.service import LocalWorkflowRunOperationService


CancelRunOperation = LocalWorkflowRunOperationService

__all__ = ["CancelRunOperation"]


