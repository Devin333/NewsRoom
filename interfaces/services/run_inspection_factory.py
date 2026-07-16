from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from framework.events.ports import EventStorePort
from framework.events.schema import EventSchemaCatalog
from interfaces.services.event_projection_service import EventProjectionService
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizationDecision,
    EventAuthorizationRequest,
    EventPermission,
    EventReaderService,
)
from interfaces.services.run_inspection_service import RunInspectionService


class RunInspectionEventAuthorizer:
    """Fixed-scope service authorizer for online run-event reads."""

    def __init__(self, authorization: EventAuthorizationContext) -> None:
        if not isinstance(authorization, EventAuthorizationContext):
            raise TypeError("authorization must be an EventAuthorizationContext")
        self._authorization = authorization

    def authorize(
        self,
        request: EventAuthorizationRequest,
    ) -> EventAuthorizationDecision:
        if not isinstance(request, EventAuthorizationRequest):
            raise TypeError("request must be an EventAuthorizationRequest")
        matches_scope = (
            request.principal_id == self._authorization.principal_id
            and request.tenant_id == self._authorization.tenant_id
            and request.authentication_evidence_ref
            == self._authorization.authentication_evidence_ref
        )
        authorized = matches_scope and request.operation in {
            EventPermission.READ,
            EventPermission.PROJECTION_READ,
        }
        return EventAuthorizationDecision(
            request=request,
            authorized=authorized,
            authorization_evidence_ref=(
                "authz://service/run-inspection-read" if authorized else None
            ),
            denial_reason_class=None if authorized else "operation_not_allowed",
        )


class DurableEventInspectionStorage(Protocol):
    event_store: EventStorePort
    schema_catalog: EventSchemaCatalog


def build_run_inspection_service(
    *,
    artifact_root: str | Path,
    event_storage: DurableEventInspectionStorage,
    tenant_id: str | None,
    principal_id: str = "newsroom-run-inspection",
    authentication_evidence_ref: str = "authn://service/run-inspection",
    allow_stale_projection: bool = True,
) -> RunInspectionService:
    """Compose application services from an already selected storage bundle."""

    reader, projection, authorization, schema_catalog = _build_event_services(
        artifact_root=artifact_root,
        event_storage=event_storage,
        tenant_id=tenant_id,
        principal_id=principal_id,
        authentication_evidence_ref=authentication_evidence_ref,
    )
    return RunInspectionService(
        artifact_root,
        event_reader_service=reader,
        event_projection_service=projection,
        event_authorization=authorization,
        event_schema_catalog=schema_catalog,
        allow_stale_projection=allow_stale_projection,
    )


def _build_event_services(
    *,
    artifact_root: str | Path,
    event_storage: DurableEventInspectionStorage,
    tenant_id: str | None,
    principal_id: str,
    authentication_evidence_ref: str,
) -> tuple[
    EventReaderService,
    EventProjectionService,
    EventAuthorizationContext,
    EventSchemaCatalog,
]:
    if event_storage is None:
        raise ValueError("event_storage is required")
    resolved_root = Path(artifact_root)
    authorization = EventAuthorizationContext(
        principal_id=principal_id,
        tenant_id=tenant_id,
        authentication_evidence_ref=authentication_evidence_ref,
    )
    authorizer = RunInspectionEventAuthorizer(authorization)
    reader = EventReaderService(event_storage.event_store, authorizer=authorizer)
    projection = EventProjectionService(
        reader=event_storage.event_store,
        authorizer=authorizer,
        artifact_root=resolved_root,
        schema_catalog=event_storage.schema_catalog,
    )
    return reader, projection, authorization, event_storage.schema_catalog


def run_inspection_service_from_env(
    artifact_root: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    allow_stale_projection: bool = True,
) -> RunInspectionService:
    """Select durable storage once, then compose the application services."""

    from infrastructure.storage.events.factory import durable_event_storage_from_env

    values = env if env is not None else os.environ
    configured_root = str(values.get("NEWS_ARTIFACT_ROOT") or "").strip()
    resolved_root = Path(artifact_root or configured_root or ".newsroom/runs")
    tenant_id = str(values.get("NEWS_TENANT_ID") or "").strip() or None
    def compose_event_services():
        event_storage = durable_event_storage_from_env(
            artifact_root=resolved_root,
            env=values,
        )
        return _build_event_services(
            artifact_root=resolved_root,
            event_storage=event_storage,
            tenant_id=tenant_id,
            principal_id="newsroom-run-inspection",
            authentication_evidence_ref="authn://service/run-inspection",
        )

    return RunInspectionService(
        resolved_root,
        event_services_factory=compose_event_services,
        allow_stale_projection=allow_stale_projection,
    )


__all__ = [
    "RunInspectionEventAuthorizer",
    "build_run_inspection_service",
    "run_inspection_service_from_env",
]
