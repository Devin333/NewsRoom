from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from framework.events.canonical import (
    BusinessContext,
    ProducerIdentity,
    StoredEvent,
    thaw_canonical_json,
)
from framework.events.ports import EventReaderPort, EventRuntimePort
from framework.events.runtime.models import StreamReadRequest
from framework.events.runtime.publisher import EventPublishRequest
from framework.governance.budget import (
    BUDGET_EVENT_SCHEMA_VERSION,
    BudgetEvent,
    BudgetHistoryError,
)
from framework.shared.graph_identity import GraphExecutionIdentity, GraphRunIdentity


BUDGET_EVENT_DATA_SCHEMA = "newsroom.budget-event/v1"
BUDGET_EVENT_SOURCE = "framework.governance.budget"
BUDGET_EVENT_TYPES = tuple(sorted(BudgetEvent.ALLOWED_TYPES))


@dataclass(frozen=True, slots=True)
class CanonicalBudgetFact:
    event: BudgetEvent
    fact_ref: str
    stream_sequence: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_ref": self.fact_ref,
            "event_id": self.event.event_id,
            "event_type": self.event.event_type,
            "operation_id": self.event.operation_id,
            "reservation_id": self.event.reservation_id,
            "scope_id": self.event.scope.scope_id,
            "policy_digest": self.event.policy_digest,
            "ledger_revision": self.event.ledger_revision,
            "reason_codes": list(self.event.reason_codes),
            "outcome": self.event.outcome,
            "stream_sequence": self.stream_sequence,
        }


class CanonicalBudgetEventSink:
    """Publishes canonical budget facts through the existing event runtime."""

    required = True

    def __init__(
        self,
        runtime: EventRuntimePort,
        *,
        tenant_id: str | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        if tenant_id is not None:
            if not isinstance(tenant_id, str) or not tenant_id.strip():
                raise ValueError("tenant_id must be a non-blank string")
            tenant_id = tenant_id.strip()
        self._runtime = runtime
        self._tenant_id = tenant_id
        self._now_fn = now_fn or (lambda: datetime.now(UTC))

    def append(self, event: BudgetEvent) -> None:
        if not isinstance(event, BudgetEvent):
            raise TypeError("event must be BudgetEvent")
        self._runtime.publish(
            EventPublishRequest(
                event_id=event.event_id,
                event_type=event.event_type,
                data_schema=BUDGET_EVENT_DATA_SCHEMA,
                source=BUDGET_EVENT_SOURCE,
                occurred_at=self._now_fn(),
                stream_id=f"budget:{event.run_id}",
                business_context=_budget_business_context(event),
                producer=ProducerIdentity(
                    component=BUDGET_EVENT_SOURCE,
                    version="1",
                ),
                subject=event.scope.scope_id,
                correlation_id=event.operation_id,
                causation_id=event.reservation_id,
                tenant_id=self._tenant_id,
                payload=budget_event_payload(event),
            )
        )


class DurableBudgetFactResolver:
    """Resolve one operation fact from the authoritative ordered budget stream."""

    def __init__(
        self,
        reader: EventReaderPort,
        *,
        tenant_id: str | None = None,
        page_size: int = 100,
    ) -> None:
        if not isinstance(reader, EventReaderPort):
            raise TypeError("reader must implement EventReaderPort")
        if isinstance(page_size, bool) or not isinstance(page_size, int):
            raise TypeError("page_size must be an integer")
        if page_size < 1 or page_size > 1_000:
            raise ValueError("page_size must be between 1 and 1000")
        self._reader = reader
        self._tenant_id = tenant_id
        self._page_size = page_size

    def resolve(
        self,
        *,
        run_id: str,
        operation_id: str,
        ledger_revision: int,
        expected_identity: GraphRunIdentity | GraphExecutionIdentity | None = None,
    ) -> CanonicalBudgetFact | None:
        run_id = _required_text(run_id, "run_id")
        operation_id = _required_text(operation_id, "operation_id")
        if (
            isinstance(ledger_revision, bool)
            or not isinstance(ledger_revision, int)
            or ledger_revision < 1
        ):
            raise ValueError("ledger_revision must be a positive integer")
        if expected_identity is not None:
            if not isinstance(
                expected_identity,
                (GraphRunIdentity, GraphExecutionIdentity),
            ):
                raise TypeError("expected_identity must be a Graph identity")
            if expected_identity.run_id != run_id:
                raise BudgetHistoryError(
                    "expected budget Graph identity crossed the run scope"
                )
        stream_id = f"budget:{run_id}"
        high_watermark = self._reader.get_stream_high_watermark(
            stream_id,
            tenant_id=self._tenant_id,
        )
        if high_watermark is None:
            return None

        cursor = None
        expected_revision = 1
        match: CanonicalBudgetFact | None = None
        while True:
            page = self._reader.read_stream(
                StreamReadRequest(
                    stream_id=stream_id,
                    cursor=cursor,
                    limit=self._page_size,
                    through_sequence=high_watermark,
                    tenant_id=self._tenant_id,
                    event_types=frozenset(BUDGET_EVENT_TYPES),
                    data_schemas=frozenset({BUDGET_EVENT_DATA_SCHEMA}),
                )
            )
            if page.high_watermark != high_watermark:
                raise BudgetHistoryError("budget stream high watermark changed")
            for stored in page.events:
                event = budget_event_from_stored_event(stored)
                if event.ledger_revision != expected_revision:
                    raise BudgetHistoryError(
                        "budget stream ledger revisions are not contiguous"
                    )
                expected_revision += 1
                if (
                    event.operation_id == operation_id
                    and event.ledger_revision == ledger_revision
                ):
                    _validate_expected_budget_identity(expected_identity, event)
                    candidate = CanonicalBudgetFact(
                        event=event,
                        fact_ref=stored.content_checksum,
                        stream_sequence=stored.stream_sequence,
                    )
                    if match is not None and match != candidate:
                        raise BudgetHistoryError(
                            "budget operation resolves to conflicting durable facts"
                        )
                    match = candidate
            if page.next_cursor is None:
                return match
            cursor = page.next_cursor


def budget_event_from_stored_event(stored: StoredEvent) -> BudgetEvent:
    if not isinstance(stored, StoredEvent):
        raise TypeError("stored must be StoredEvent")
    stored.verify_integrity()
    if (
        stored.data_schema != BUDGET_EVENT_DATA_SCHEMA
        or stored.source != BUDGET_EVENT_SOURCE
        or stored.event_type not in BudgetEvent.ALLOWED_TYPES
    ):
        raise BudgetHistoryError("stored event is not a canonical budget fact")
    run_id = stored.business_context.run_id
    if run_id is None or stored.stream_id != f"budget:{run_id}":
        raise BudgetHistoryError("budget event run scope is inconsistent")
    payload = thaw_canonical_json(stored.payload or {})
    if not isinstance(payload, dict):
        raise BudgetHistoryError("budget event payload must be an object")
    try:
        event = BudgetEvent.from_dict(
            {
                "schema_version": BUDGET_EVENT_SCHEMA_VERSION,
                "event_id": stored.event_id,
                "event_type": stored.event_type,
                "run_id": run_id,
                **payload,
            }
        )
    except Exception as exc:
        raise BudgetHistoryError("stored budget payload is invalid") from exc
    if (
        stored.subject != event.scope.scope_id
        or stored.correlation_id != event.operation_id
        or stored.causation_id != event.reservation_id
    ):
        raise BudgetHistoryError("budget event envelope conflicts with its payload")
    _validate_budget_business_context(stored.business_context, event)
    return event


def _budget_business_context(event: BudgetEvent) -> BusinessContext:
    identity = event.scope.execution_identity
    if isinstance(identity, GraphExecutionIdentity):
        return BusinessContext(
            run_id=identity.run_id,
            graph_id=identity.graph_id,
            graph_version=identity.graph_version,
            graph_ref=identity.graph_ref,
            graph_checksum=identity.graph_checksum,
            execution_identity=identity,
            stage_id=identity.node_id,
            node_instance_id=identity.node_instance_id,
        )
    if isinstance(identity, GraphRunIdentity):
        return BusinessContext(
            run_id=identity.run_id,
            graph_id=identity.graph_id,
            graph_version=identity.graph_version,
            graph_ref=identity.graph_ref,
            graph_checksum=identity.graph_checksum,
        )
    return BusinessContext(run_id=event.run_id)


def _validate_budget_business_context(
    context: BusinessContext,
    event: BudgetEvent,
) -> None:
    identity = event.scope.execution_identity
    if identity is None:
        if context.graph_identity is not None or context.physical_identity is not None:
            raise BudgetHistoryError("budget event has unexpected Graph business context")
        return
    if isinstance(identity, GraphExecutionIdentity):
        if context.physical_identity != identity:
            raise BudgetHistoryError("budget event Graph execution identity is inconsistent")
        return
    if context.graph_identity != identity or context.physical_identity is not None:
        raise BudgetHistoryError("budget event Graph run identity is inconsistent")


def _validate_expected_budget_identity(
    expected_identity: GraphRunIdentity | GraphExecutionIdentity | None,
    event: BudgetEvent,
) -> None:
    if expected_identity is None:
        return
    if event.scope.execution_identity != expected_identity:
        raise BudgetHistoryError(
            "budget event Graph identity does not match the expected execution"
        )


def budget_event_payload(event: BudgetEvent) -> dict[str, Any]:
    return {
        "scope": event.scope.to_dict(),
        "policy_digest": event.policy_digest,
        "ledger_revision": event.ledger_revision,
        "operation_id": event.operation_id,
        "idempotency_key": event.idempotency_key,
        "reservation_id": event.reservation_id,
        "amounts": event.amounts.to_dict(),
        "reason_codes": list(event.reason_codes),
        "outcome": event.outcome,
        "reservation": event.reservation.to_dict() if event.reservation else None,
        "settlement": event.settlement.to_dict() if event.settlement else None,
    }


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


__all__ = [
    "BUDGET_EVENT_DATA_SCHEMA",
    "BUDGET_EVENT_SOURCE",
    "BUDGET_EVENT_TYPES",
    "CanonicalBudgetFact",
    "CanonicalBudgetEventSink",
    "DurableBudgetFactResolver",
    "budget_event_from_stored_event",
    "budget_event_payload",
]
