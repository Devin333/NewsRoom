from __future__ import annotations

from fastapi import APIRouter

from interfaces.api.deps import ApiRouteHelpers, ApiServices
from interfaces.models import TopicSubscriptionCreateRequest


def create_router(services: ApiServices, helpers: ApiRouteHelpers) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/subscriptions")
    def list_subscriptions(enabled_only: bool = False, cadence: str | None = None):
        try:
            result = services.subscription_service_factory().list_topic_subscriptions(
                enabled_only=enabled_only,
                cadence=cadence,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_subscription_list_request", message=str(exc))
        return helpers.success(result.to_dict())

    @router.post("/api/v1/subscriptions")
    def create_subscription(request: TopicSubscriptionCreateRequest):
        try:
            subscription = services.subscription_service_factory().create_topic_subscription(
                topic=request.topic,
                cadence=request.cadence,
                profile=request.profile,
                source_limit=request.source_limit,
                subscription_id=request.subscription_id,
                enabled=request.enabled,
                metadata=request.metadata,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_subscription_request", message=str(exc))
        return helpers.success(subscription.to_dict())

    @router.post("/api/v1/subscriptions/{subscription_id}/enable")
    def enable_subscription(subscription_id: str):
        return _set_subscription_enabled(subscription_id, enabled=True)

    @router.post("/api/v1/subscriptions/{subscription_id}/disable")
    def disable_subscription(subscription_id: str):
        return _set_subscription_enabled(subscription_id, enabled=False)

    @router.delete("/api/v1/subscriptions/{subscription_id}")
    def delete_subscription(subscription_id: str):
        deleted = services.subscription_service_factory().delete_topic_subscription(subscription_id)
        return helpers.success({"subscription_id": subscription_id, "deleted": deleted})

    def _set_subscription_enabled(subscription_id: str, *, enabled: bool):
        try:
            subscription = services.subscription_service_factory().set_enabled(subscription_id, enabled=enabled)
        except KeyError as exc:
            return helpers.error(
                status_code=404,
                code="subscription_not_found",
                message=str(exc),
                user_action_required=True,
            )
        except ValueError as exc:
            return helpers.error(status_code=400, code="invalid_subscription_request", message=str(exc))
        return helpers.success(subscription.to_dict())

    return router
