from __future__ import annotations


def test_public_imports_are_available() -> None:
    from framework.events import (  # noqa: PLC0415
        Event,
        EventBus,
        EventEnvelope,
        EventFilter,
        EventPublisher,
        EventRecord,
        EventRecorder,
        EventReplay,
        EventType,
        FunctionEventSubscriber,
        InMemoryEventBus,
        InMemoryEventRecorder,
        ReplayCheckpointCollisionError,
        ReplayCheckpointCorruptionError,
    )

    assert Event is not None
    assert EventBus is InMemoryEventBus
    assert EventEnvelope is not None
    assert EventFilter is not None
    assert EventPublisher is not None
    assert EventRecord is not None
    assert EventRecorder is not None
    assert EventReplay is not None
    assert EventType is not None
    assert FunctionEventSubscriber is not None
    assert InMemoryEventRecorder is not None
    assert ReplayCheckpointCollisionError is not None
    assert ReplayCheckpointCorruptionError is not None
