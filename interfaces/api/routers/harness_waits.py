from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Path, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from framework.events import EventStoreUnavailableError
from framework.harness import HarnessValidationError
from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import ActorContext
from interfaces.services.harness_wait_service import (
    HarnessWaitApplicationError,
    HarnessWaitApplicationService,
    HarnessWaitAuthorizationError,
    HarnessWaitInspectionResult,
    HarnessWaitNotFoundError,
    HarnessWaitOperationResult,
    HarnessWaitRequestError,
)


_MAX_ID_LENGTH = 256
_MAX_REASON_CODE_LENGTH = 128
_MAX_REFERENCE_LENGTH = 512


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class HarnessWaitSignalRequest(_StrictRequest):
    signal_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    signal_schema_ref: str = Field(min_length=1, max_length=_MAX_REFERENCE_LENGTH)
    correlation: dict[str, object]
    payload_ref: str = Field(min_length=1, max_length=_MAX_REFERENCE_LENGTH)


class HarnessWaitApprovalRequest(_StrictRequest):
    approval_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    approved: StrictBool


class HarnessWaitCancellationRequest(_StrictRequest):
    cancellation_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    reason_code: str = Field(min_length=1, max_length=_MAX_REASON_CODE_LENGTH)


HarnessWaitCall = Callable[
    [HarnessWaitApplicationService],
    HarnessWaitInspectionResult | HarnessWaitOperationResult,
]


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/runs/{run_id}/waits/{node_instance_id}")
    def inspect_wait(
        request: Request,
        run_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
        node_instance_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.inspect_wait(run_id, node_instance_id),
        )

    @router.post("/api/v1/runs/{run_id}/waits/{node_instance_id}/signals")
    def deliver_signal(
        body: HarnessWaitSignalRequest,
        request: Request,
        run_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
        node_instance_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.deliver_signal(
                run_id,
                node_instance_id,
                signal_id=body.signal_id,
                signal_schema_ref=body.signal_schema_ref,
                correlation=body.correlation,
                payload_ref=body.payload_ref,
            ),
        )

    @router.post("/api/v1/runs/{run_id}/waits/{node_instance_id}/approval")
    def decide_approval(
        body: HarnessWaitApprovalRequest,
        request: Request,
        run_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
        node_instance_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.decide_approval(
                run_id,
                node_instance_id,
                approval_id=body.approval_id,
                approved=body.approved,
            ),
        )

    @router.post("/api/v1/runs/{run_id}/waits/{node_instance_id}/cancel")
    def cancel_wait(
        body: HarnessWaitCancellationRequest,
        request: Request,
        run_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
        node_instance_id: str = Path(min_length=1, max_length=_MAX_ID_LENGTH),
    ):
        return _invoke(
            request,
            services=services,
            helpers=helpers,
            operation=lambda service: service.cancel_wait(
                run_id,
                node_instance_id,
                cancellation_id=body.cancellation_id,
                reason_code=body.reason_code,
            ),
        )

    return router


def _invoke(
    request: Request,
    *,
    services: ApiServices,
    helpers: ApiRouteHelpers,
    operation: HarnessWaitCall,
):
    actor = getattr(request.state, "actor_context", None)
    if not isinstance(actor, ActorContext):
        return helpers.error(
            status_code=401,
            code="unauthorized",
            message="authenticated Harness Wait actor required",
            user_action_required=True,
            headers={"WWW-Authenticate": "Bearer"},
        )
    factory = services.harness_wait_service_factory
    if factory is None:
        return _capability_unavailable(helpers)
    try:
        result = operation(factory(actor))
    except HarnessWaitAuthorizationError:
        return helpers.error(
            status_code=403,
            code="forbidden",
            message="Harness Wait operation is not authorized",
            user_action_required=True,
        )
    except HarnessWaitNotFoundError:
        return helpers.error(
            status_code=404,
            code="wait_not_found",
            message="Harness Wait was not found",
        )
    except HarnessWaitRequestError as exc:
        return helpers.error(
            status_code=409,
            code=exc.code,
            message=str(exc),
            user_action_required=True,
        )
    except HarnessValidationError as exc:
        return helpers.error(
            status_code=409,
            code=exc.code,
            message="Harness Wait request conflicts with durable state",
        )
    except EventStoreUnavailableError:
        return helpers.error(
            status_code=503,
            code="event_store_unavailable",
            message="event store is unavailable",
            retryable=True,
        )
    except HarnessWaitApplicationError as exc:
        return helpers.error(
            status_code=503,
            code=exc.code,
            message="Harness Wait service capability is unavailable",
            retryable=True,
        )
    return helpers.success(result.to_dict())


def _capability_unavailable(helpers: ApiRouteHelpers):
    return helpers.error(
        status_code=503,
        code="harness_wait_capability_unavailable",
        message="Harness Wait service capability is unavailable",
        retryable=True,
    )


__all__ = [
    "HarnessWaitApprovalRequest",
    "HarnessWaitCancellationRequest",
    "HarnessWaitSignalRequest",
    "create_router",
]
