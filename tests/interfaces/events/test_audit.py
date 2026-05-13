from interfaces.events import AuditEmitter, InMemoryAuditSink
from interfaces.models import actor_context_from_headers


def test_actor_context_expands_role_permissions() -> None:
    actor = actor_context_from_headers(
        {"X-News-Actor": "devin", "X-News-Roles": "operator"},
        request_id="req-1",
    )

    assert actor.actor_id == "devin"
    assert actor.has_permission("runs:create") is True
    assert actor.has_permission("reports:publish") is False


def test_audit_emitter_redacts_sensitive_metadata() -> None:
    sink = InMemoryAuditSink()
    emitter = AuditEmitter(sink)
    actor = actor_context_from_headers({"Authorization": "Bearer hidden"}, request_id="req-1")

    record = emitter.emit(
        actor=actor,
        action="api_request_post",
        resource_type="runs",
        result="succeeded",
        metadata={"api_key": "secret-value", "safe": "value"},
    )

    assert record is sink.records[0]
    assert sink.records[0].metadata["api_key"] == "[redacted]"
    assert sink.records[0].metadata["safe"] == "value"
