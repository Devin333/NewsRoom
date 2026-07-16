from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from framework.events.errors import EventContractError, EventStoreUnavailableError
from framework.events.ports import QuarantineStorePort
from framework.events.runtime.models import (
    QuarantineDisposition,
    QuarantinePage,
    QuarantineQuery,
    QuarantineReason,
    QuarantineRecord,
)
from interfaces.services.event_delivery_operations_service import (
    EventOperationNotFoundError,
)
from interfaces.services.event_reader_service import (
    EventAuthorizationContext,
    EventAuthorizerPort,
    EventPermission,
    EventServiceAvailability,
    authorize_event_operation,
)


@dataclass(frozen=True, slots=True)
class QuarantineLookupResult:
    availability: EventServiceAvailability
    tenant_id: str | None
    record: QuarantineRecord | None = None
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.unavailable_reason_class is not None:
                raise ValueError("available quarantine lookup has no failure reason")
        elif self.record is not None:
            raise ValueError("unavailable quarantine lookup cannot contain a record")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable quarantine lookup requires a reason class")


@dataclass(frozen=True, slots=True)
class QuarantineListResult:
    availability: EventServiceAvailability
    tenant_id: str | None
    page: QuarantinePage | None = None
    unavailable_reason_class: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "availability", EventServiceAvailability(self.availability))
        if self.availability is EventServiceAvailability.AVAILABLE:
            if self.page is None:
                raise ValueError("available quarantine list requires a page")
            if self.unavailable_reason_class is not None:
                raise ValueError("available quarantine list has no failure reason")
        elif self.page is not None:
            raise ValueError("unavailable quarantine list cannot contain a page")
        elif self.unavailable_reason_class is None:
            raise ValueError("unavailable quarantine list requires a reason class")


class EventQuarantineService:
    """Authorized tenant-scoped inspection and disposition of quarantine."""

    def __init__(
        self,
        store: QuarantineStorePort,
        *,
        authorizer: EventAuthorizerPort,
    ) -> None:
        if store is None:
            raise ValueError("quarantine store is required")
        if authorizer is None:
            raise ValueError("event authorizer is required")
        self._store = store
        self._authorizer = authorizer

    def get(
        self,
        quarantine_id: str,
        *,
        authorization: EventAuthorizationContext,
    ) -> QuarantineLookupResult:
        normalized_id = _required_text(quarantine_id, "quarantine_id")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.QUARANTINE_READ,
            target={"quarantine_id": normalized_id},
        )
        try:
            record = self._store.get_quarantine(
                normalized_id,
                tenant_id=authorization.tenant_id,
            )
        except EventStoreUnavailableError as error:
            return QuarantineLookupResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                tenant_id=authorization.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        self._validate_scope(record, authorization)
        if record is not None and record.quarantine_id != normalized_id:
            raise EventContractError("quarantine store returned another target")
        return QuarantineLookupResult(
            availability=EventServiceAvailability.AVAILABLE,
            tenant_id=authorization.tenant_id,
            record=record,
        )

    def list(
        self,
        *,
        authorization: EventAuthorizationContext,
        reason: QuarantineReason | None = None,
        disposition: QuarantineDisposition | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> QuarantineListResult:
        query = QuarantineQuery(
            reason=reason,
            tenant_id=authorization.tenant_id,
            disposition=disposition,
            cursor=cursor,
            limit=limit,
        )
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.QUARANTINE_READ,
            target={
                "reason": None if query.reason is None else query.reason.value,
                "disposition": (
                    None if query.disposition is None else query.disposition.value
                ),
                "cursor": query.cursor,
                "limit": query.limit,
            },
        )
        try:
            page = self._store.list_quarantine(query)
        except EventStoreUnavailableError as error:
            return QuarantineListResult(
                availability=EventServiceAvailability.UNAVAILABLE,
                tenant_id=authorization.tenant_id,
                unavailable_reason_class=type(error).__name__,
            )
        if not isinstance(page, QuarantinePage):
            raise EventContractError("quarantine store returned an invalid page")
        if len(page.records) > query.limit:
            raise EventContractError("quarantine store exceeded the requested limit")
        if page.next_cursor is not None and page.next_cursor == query.cursor:
            raise EventContractError("quarantine cursor did not advance")
        if len({record.quarantine_id for record in page.records}) != len(page.records):
            raise EventContractError("quarantine store returned duplicate records")
        if any(
            record.tenant_id != authorization.tenant_id
            or (query.reason is not None and record.reason is not query.reason)
            or (
                query.disposition is not None
                and record.disposition is not query.disposition
            )
            for record in page.records
        ):
            raise EventContractError("quarantine store violated the query filters")
        return QuarantineListResult(
            availability=EventServiceAvailability.AVAILABLE,
            tenant_id=authorization.tenant_id,
            page=page,
        )

    def resolve(
        self,
        quarantine_id: str,
        disposition: QuarantineDisposition,
        *,
        operator_reason: str,
        resolved_at: datetime,
        authorization: EventAuthorizationContext,
    ) -> QuarantineRecord:
        normalized_id = _required_text(quarantine_id, "quarantine_id")
        target_disposition = QuarantineDisposition(disposition)
        if target_disposition is QuarantineDisposition.PENDING:
            raise ValueError("quarantine resolution requires a terminal disposition")
        reason = _required_text(operator_reason, "operator_reason")
        authorize_event_operation(
            self._authorizer,
            authorization,
            EventPermission.QUARANTINE_RESOLVE,
            target={
                "quarantine_id": normalized_id,
                "disposition": target_disposition.value,
                "operator_reason": reason,
                "resolved_at": resolved_at.isoformat(),
            },
        )
        scoped = self._store.get_quarantine(
            normalized_id,
            tenant_id=authorization.tenant_id,
        )
        if scoped is None:
            raise EventOperationNotFoundError("quarantine record is not available in scope")
        self._validate_scope(scoped, authorization)
        resolved = self._store.resolve_quarantine(
            normalized_id,
            target_disposition,
            operator_id=authorization.principal_id,
            reason=reason,
            resolved_at=resolved_at,
        )
        self._validate_scope(resolved, authorization)
        if resolved.quarantine_id != normalized_id:
            raise EventContractError("quarantine store resolved another record")
        return resolved

    @staticmethod
    def _validate_scope(
        record: QuarantineRecord | None,
        authorization: EventAuthorizationContext,
    ) -> None:
        if record is not None and record.tenant_id != authorization.tenant_id:
            raise EventContractError("quarantine store crossed the tenant scope")


def _required_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


__all__ = [
    "EventQuarantineService",
    "QuarantineListResult",
    "QuarantineLookupResult",
]
