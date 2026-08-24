"""Legacy approval router intentionally has no production routes.

Approval decisions are Graph Wait causes and are exposed by
``harness_waits``.  Keeping this module as an empty router preserves the
router import surface for downstream integrations while preventing the old
``/api/v1/approvals`` and resume-context endpoints from being registered.
"""

from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    del services, helpers
    return APIRouter()


__all__ = ["create_router"]
