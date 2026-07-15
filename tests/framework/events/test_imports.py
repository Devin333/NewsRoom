from __future__ import annotations


def test_public_imports_are_available() -> None:
    import framework.events as events

    from framework.events import (  # noqa: PLC0415
        Event,
        EventBus,
        EventEnvelope,
        EventFilter,
        EventPublisher,
        EventReplay,
        EventType,
        FunctionEventSubscriber,
        InMemoryEventBus,
        InMemoryEventRecorder,
        ReplayCheckpointCollisionError,
        ReplayCheckpointCorruptionError,
        REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
        SecurePayloadCapability,
        SecurePayloadValidation,
        SecurityExportProjection,
        WholeDocumentReferenceDisposition,
    )

    assert Event is not None
    assert EventBus is InMemoryEventBus
    assert EventEnvelope is not None
    assert EventFilter is not None
    assert EventPublisher is not None
    assert not hasattr(events, "EventRecord")
    assert not hasattr(events, "EventRecorder")
    assert EventReplay is not None
    assert EventType is not None
    assert FunctionEventSubscriber is not None
    assert InMemoryEventRecorder is not None
    assert ReplayCheckpointCollisionError is not None
    assert ReplayCheckpointCorruptionError is not None
    assert REQUIRED_SECURE_PAYLOAD_CAPABILITIES == frozenset(SecurePayloadCapability)
    assert SecurePayloadValidation is not None
    assert SecurityExportProjection is not None
    assert WholeDocumentReferenceDisposition is not None
