from __future__ import annotations


class EventRuntimeError(RuntimeError):
    """Base class for event runtime errors."""


class EventPublishError(EventRuntimeError):
    """Raised when an event cannot be published."""


class EventSubscriberError(EventRuntimeError):
    """Raised when an event subscriber fails."""


class EventReplayError(EventRuntimeError):
    """Raised when event replay fails."""
