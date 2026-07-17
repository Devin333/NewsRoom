from __future__ import annotations


def test_public_imports_are_available() -> None:
    import framework.events as events

    from framework.events import (  # noqa: PLC0415
        Event,
        EventEnvelope,
        EventFilter,
        EventType,
        InMemoryEventBus,
        InMemoryEventRecorder,
        DETERMINISTIC_HISTORY_EXTENSION,
        DeterministicHistoryRecord,
        HistoryCommandMismatchError,
        HistoryVerificationError,
        RedeliveryAuthorizationDecision,
        RedeliveryAuthorizationRequest,
        RedeliveryAuthorizerPort,
        RedeliveryReport,
        RedeliveryRequest,
        RedeliveryStorePort,
        RetirementCancellationAuthorizationDecision,
        RetirementCancellationAuthorizationRequest,
        RetirementCancellationAuthorizerPort,
        RetirementCancellationReport,
        RetirementCancellationRequest,
        RetirementCancellationStorePort,
        ReplayCheckpointCollisionError,
        ReplayCheckpointCorruptionError,
        ReplayActivityResolverPort,
        ReplayActivityCorruptionError,
        ReplayActivityMissingError,
        ReplayEvent,
        RecordedActivityStorePort,
        ResolvedReplayActivity,
        REQUIRED_SECURE_PAYLOAD_CAPABILITIES,
        SecurePayloadCapability,
        SecurePayloadValidation,
        SecurityExportProjection,
        WholeDocumentReferenceDisposition,
    )

    assert Event is not None
    assert EventEnvelope is not None
    assert EventFilter is not None
    assert EventType is not None
    assert InMemoryEventBus is not None
    assert InMemoryEventRecorder is not None
    for retired_name in (
        "EventBus",
        "EventPublisher",
        "EventRecord",
        "EventRecorder",
        "EventReplay",
        "FunctionEventSubscriber",
    ):
        assert not hasattr(events, retired_name)
    assert DETERMINISTIC_HISTORY_EXTENSION == "deterministic_history"
    assert DeterministicHistoryRecord is not None
    assert HistoryCommandMismatchError is not None
    assert HistoryVerificationError is not None
    assert RedeliveryAuthorizationDecision is not None
    assert RedeliveryAuthorizationRequest is not None
    assert RedeliveryAuthorizerPort is not None
    assert RedeliveryReport is not None
    assert RedeliveryRequest is not None
    assert RedeliveryStorePort is not None
    assert RetirementCancellationAuthorizationDecision is not None
    assert RetirementCancellationAuthorizationRequest is not None
    assert RetirementCancellationAuthorizerPort is not None
    assert RetirementCancellationReport is not None
    assert RetirementCancellationRequest is not None
    assert RetirementCancellationStorePort is not None
    assert ReplayCheckpointCollisionError is not None
    assert ReplayCheckpointCorruptionError is not None
    assert ReplayActivityResolverPort is not None
    assert ReplayActivityCorruptionError is not None
    assert ReplayActivityMissingError is not None
    assert ReplayEvent is not None
    assert RecordedActivityStorePort is not None
    assert ResolvedReplayActivity is not None
    assert REQUIRED_SECURE_PAYLOAD_CAPABILITIES == frozenset(SecurePayloadCapability)
    assert SecurePayloadValidation is not None
    assert SecurityExportProjection is not None
    assert WholeDocumentReferenceDisposition is not None
