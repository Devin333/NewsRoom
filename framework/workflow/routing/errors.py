"""Routing errors."""

from framework.workflow.routing.engine import ConditionalExpressionError


class RoutingError(RuntimeError):
    pass


__all__ = ["ConditionalExpressionError", "RoutingError"]


