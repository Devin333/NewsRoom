from __future__ import annotations

from typing import Any


class EventRuntimeError(RuntimeError):
    """Base class for event runtime errors."""


class EventContractError(EventRuntimeError, ValueError):
    """Base class for deterministic event contract violations."""


class EventCanonicalizationError(EventContractError):
    """Raised when input cannot be represented as canonical JSON."""


class EventContextConflictError(EventContractError):
    """Raised when legacy duplicate context contains conflicting values."""

    def __init__(self, field_name: str) -> None:
        self.field_name = str(field_name)
        super().__init__(f"conflicting authoritative event field: {self.field_name}")


class EventTimeError(EventContractError):
    """Raised when an event occurrence or observation time is invalid."""


class EventPayloadTooLargeError(EventContractError):
    """Raised when an inline payload exceeds its configured nonzero limit."""


class EventExtensionLimitError(EventContractError):
    """Raised when event extensions exceed count or encoded-size limits."""


class EventSchemaError(EventContractError):
    """Base class for event schema registration and validation errors."""


class EventUnknownSchemaError(EventSchemaError):
    """Raised when an event type/data-schema pair is not registered."""

    def __init__(self, event_type: str, data_schema: str) -> None:
        self.event_type = str(event_type)
        self.data_schema = str(data_schema)
        super().__init__(
            f"unregistered event schema: {self.event_type} ({self.data_schema})"
        )


class EventSchemaValidationError(EventSchemaError):
    """Schema validation failure whose message never includes instance values."""

    def __init__(
        self,
        *,
        event_type: str,
        data_schema: str,
        path: str,
        rule: str,
    ) -> None:
        self.event_type = str(event_type)
        self.data_schema = str(data_schema)
        self.path = str(path)
        self.rule = str(rule)
        super().__init__(
            "event payload validation failed: "
            f"{self.event_type} ({self.data_schema}) at {self.path}; rule={self.rule}"
        )


class EventUpcastError(EventSchemaError):
    """Raised when a historical event cannot be deterministically upcast."""


class EventSecurityError(EventContractError):
    """Base class for pre-storage security projection failures."""

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        safe_message = str(message)
        if path:
            safe_message = f"{safe_message}: {path}"
        super().__init__(safe_message)


class EventReservedFieldError(EventSecurityError):
    """Raised when extensions try to override an infrastructure-owned field."""


class EventSecurePayloadRequiredError(EventSecurityError):
    """Raised when protected content lacks an approved secure payload store."""


class EventIdentityCollisionError(EventContractError):
    """Raised when one event id is reused for different canonical content."""

    def __init__(self, event_id: str) -> None:
        self.event_id = str(event_id)
        super().__init__(f"event identity collision: {self.event_id}")


class EventIntegrityError(EventContractError):
    """Raised when a content, record, projection, or checkpoint checksum fails."""


class EventStoreError(EventRuntimeError):
    """Base class for durable event-store failures."""


class EventStoreUnavailableError(EventStoreError):
    """Raised when a required durable store is unavailable."""


class EventStoreCapacityError(EventStoreError):
    """Raised when durable admission capacity is exhausted."""


class EventStoreCorruptionError(EventStoreError):
    """Raised when the durable store fails an integrity check."""


class ReplayCheckpointCollisionError(EventStoreError):
    """Raised when a replay-owned checkpoint slot is reused incompatibly."""

    def __init__(self, checkpoint_id: str, *, reason: str) -> None:
        self.checkpoint_id = str(checkpoint_id)
        self.reason = str(reason)
        super().__init__(
            f"replay checkpoint collision: {self.checkpoint_id}; {self.reason}"
        )


class ReplayCheckpointCorruptionError(EventStoreCorruptionError):
    """Raised when a durable replay checkpoint cannot pass integrity checks."""


class EventSubscriptionPositionError(EventStoreError, ValueError):
    """Raised when a subscription start cannot be represented for a stream."""

    def __init__(
        self,
        *,
        subscription_id: str,
        subscription_version: int,
        stream_id: str,
        requested_sequence: int,
        maximum_sequence: int,
    ) -> None:
        self.subscription_id = str(subscription_id)
        self.subscription_version = int(subscription_version)
        self.stream_id = str(stream_id)
        self.requested_sequence = int(requested_sequence)
        self.maximum_sequence = int(maximum_sequence)
        super().__init__(
            "subscription start position exceeds the retained one-past-end boundary: "
            f"{self.subscription_id}@{self.subscription_version} stream={self.stream_id}; "
            f"requested={self.requested_sequence}, maximum={self.maximum_sequence}"
        )


class EventDeliveryError(EventRuntimeError):
    """Base class for durable delivery-state failures."""


class EventConsumerIdempotencyError(EventDeliveryError):
    """Raised when an external-effect consumer lacks an idempotency boundary."""


class EventStaleLeaseError(EventDeliveryError):
    """Raised when a stale claim generation tries to mutate delivery state."""


class EventQuarantineError(EventRuntimeError):
    """Raised when a quarantined record is requested as a normal event."""

    def __init__(self, reason: str, *, source: str | None = None) -> None:
        self.reason = str(reason)
        self.source = source
        message = f"event record quarantined: {self.reason}"
        if source:
            message = f"{message} ({source})"
        super().__init__(message)


class EventPublishError(EventRuntimeError):
    """Raised when an event cannot be published."""


class EventSubscriberError(EventRuntimeError):
    """Raised when an event subscriber fails."""


class EventReplayError(EventRuntimeError):
    """Raised when event replay fails."""


class EventReplayMismatchError(EventReplayError):
    """Raised when deterministic history verification finds a mismatch."""

    def __init__(self, *, sequence: int, reason: str, details: Any | None = None) -> None:
        self.sequence = int(sequence)
        self.reason = str(reason)
        self.details = details
        super().__init__(
            f"event replay mismatch at sequence {self.sequence}: {self.reason}"
        )


class EventIncompleteHistoryError(EventReplayError):
    """Raised when replay requires an activity outcome that was not recorded."""
