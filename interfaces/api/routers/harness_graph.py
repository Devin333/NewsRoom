from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Path, Query, Request

from framework.events import EventStoreUnavailableError
from framework.harness import HarnessValidationError
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import ActorContext
from interfaces.services.harness_graph_service import (
    HarnessGraphApplicationError,
    HarnessGraphApplicationService,
    HarnessGraphAuthorizationError,
    HarnessGraphNotFoundError,
)


_MAX_ID_LENGTH = 256
HarnessGraphCall = Callable[[HarnessGraphApplicationService], object]


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v2/graph-runs/{run_id}/graph")
    def inspect_graph(
        request: Request,
        run_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
        verify_history: bool = Query(default=False),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.inspect_run(
                run_id,
                verify_history=verify_history,
            ),
        )

    @router.get("/api/v2/graph-runs/{run_id}/graph/health")
    def inspect_graph_health(
        request: Request,
        run_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.inspect_health(run_id),
        )

    return router


def _invoke(
    request: Request,
    *,
    services: ApiServices,
    helpers: ApiRouteHelpers,
    operation: HarnessGraphCall,
):
    actor = getattr(request.state, "actor_context", None)
    if not isinstance(actor, ActorContext):
        return helpers.error(
            status_code=401,
            code="unauthorized",
            message="authenticated Harness graph actor required",
            user_action_required=True,
            headers={"WWW-Authenticate": "Bearer"},
        )
    factory = services.harness_graph_service_factory
    if factory is None:
        return helpers.error(
            status_code=503,
            code="harness_graph_capability_unavailable",
            message="Harness graph inspection is unavailable",
            retryable=True,
        )
    try:
        result = operation(factory(actor))
    except HarnessGraphAuthorizationError:
        return helpers.error(
            status_code=403,
            code="forbidden",
            message="Harness graph inspection is not authorized",
            user_action_required=True,
        )
    except HarnessGraphNotFoundError:
        return helpers.error(
            status_code=404,
            code="graph_run_not_found",
            message="Harness graph run was not found",
        )
    except HarnessValidationError as exc:
        return helpers.error(
            status_code=409,
            code=exc.code,
            message="Harness graph history could not be inspected safely",
        )
    except EventStoreUnavailableError:
        return helpers.error(
            status_code=503,
            code="event_store_unavailable",
            message="event store is unavailable",
            retryable=True,
        )
    except HarnessGraphApplicationError as exc:
        return helpers.error(
            status_code=503,
            code=exc.code,
            message="Harness graph inspection capability is unavailable",
            retryable=True,
        )
    to_dict = getattr(result, "to_dict", None)
    if not callable(to_dict):
        return helpers.error(
            status_code=503,
            code="invalid_harness_graph_projection",
            message="Harness graph inspection returned an invalid projection",
        )
    return helpers.success(to_dict())


__all__ = ["create_router"]
