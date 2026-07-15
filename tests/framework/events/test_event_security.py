from __future__ import annotations

from dataclasses import dataclass

import pytest

from framework.events.errors import (
    EventReservedFieldError,
    EventSecurePayloadRequiredError,
    EventSecurityError,
)
from framework.events.schema import (
    EventSecurityProjector,
    SecurePayloadCapabilities,
    SecurityClassification,
    SensitivityPolicy,
)


@dataclass(frozen=True)
class _Reference:
    uri: str = "secure://tenant/event-payload"
    expected_checksum: str = "sha256:" + "a" * 64
    size_bytes: int | None = 128 * 1024


class _SecureStore:
    def __init__(self, capabilities: SecurePayloadCapabilities) -> None:
        self.capabilities = capabilities
        self.calls: list[tuple[object, str | None, SecurityClassification]] = []

    def validate_reference(
        self,
        reference: object,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> SecurePayloadCapabilities:
        self.calls.append((reference, tenant_id, classification))
        return self.capabilities


def _complete_capabilities() -> SecurePayloadCapabilities:
    return SecurePayloadCapabilities(
        tenant_authorization=True,
        encryption_in_transit=True,
        encryption_at_rest=True,
        integrity_verification=True,
        audited_access=True,
    )


def test_projector_rejects_reserved_extension_override() -> None:
    with pytest.raises(EventReservedFieldError):
        EventSecurityProjector().project(
            payload={"safe": True},
            payload_ref=None,
            extensions={"tenant_id": "forged"},
            policy=SensitivityPolicy(),
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"tenant_id": "forged"},
        {"security-classification": "public"},
        {"event_type": "forged"},
    ],
)
def test_projector_rejects_reserved_payload_scope(payload: dict[str, str]) -> None:
    with pytest.raises(EventReservedFieldError):
        EventSecurityProjector().project(
            payload=payload,
            payload_ref=None,
            extensions={},
            policy=SensitivityPolicy(),
        )


@pytest.mark.parametrize("container", [{1: "a", "1": "b"}, {1: "a"}])
def test_projector_rejects_non_string_object_keys(container: dict[object, str]) -> None:
    with pytest.raises(EventSecurityError):
        EventSecurityProjector().project(
            payload=container,
            payload_ref=None,
            extensions={},
            policy=SensitivityPolicy(),
        )


def test_projector_rejects_exact_secret_keys_without_substring_false_positive() -> None:
    secret = "must-not-appear-in-diagnostic"
    projector = EventSecurityProjector()

    safe = projector.project(
        payload={"token_count": 5, "secretary": "Ada"},
        payload_ref=None,
        extensions={},
        policy=SensitivityPolicy(),
    )
    assert safe.payload == {"token_count": 5, "secretary": "Ada"}

    with pytest.raises(EventSecurityError) as caught:
        projector.project(
            payload={"nested": {"api-key": secret}},
            payload_ref=None,
            extensions={},
            policy=SensitivityPolicy(),
        )
    assert caught.value.path == "/nested/api-key"
    assert secret not in str(caught.value)


def test_sensitive_field_is_rejected_or_explicitly_redacted_by_schema_policy() -> None:
    projector = EventSecurityProjector()
    with pytest.raises(EventSecurityError):
        projector.project(
            payload={"answer": "private"},
            payload_ref=None,
            extensions={},
            policy=SensitivityPolicy(field_rules={"/answer": "sensitive"}),
        )

    projected = projector.project(
        payload={"answer": "private", "safe": True},
        payload_ref=None,
        extensions={},
        policy=SensitivityPolicy(
            field_rules={"/answer": "sensitive"},
            redact_sensitive=True,
        ),
    )
    assert projected.payload == {"answer": "[REDACTED]", "safe": True}


@pytest.mark.parametrize(
    "classification",
    [SecurityClassification.CONFIDENTIAL, SecurityClassification.RESTRICTED],
)
def test_protected_content_fails_without_secure_payload_store(
    classification: SecurityClassification,
) -> None:
    with pytest.raises(EventSecurePayloadRequiredError):
        EventSecurityProjector().project(
            payload=None,
            payload_ref=_Reference(),
            extensions={},
            tenant_id="tenant-1",
            classification=classification,
            policy=SensitivityPolicy(allow_payload_reference=True),
        )


def test_secure_reference_still_requires_schema_reference_permission() -> None:
    with pytest.raises(EventSecurityError, match="does not permit"):
        EventSecurityProjector().project(
            payload=None,
            payload_ref=_Reference(),
            extensions={},
            tenant_id="tenant-1",
            classification=SecurityClassification.CONFIDENTIAL,
            policy=SensitivityPolicy(),
        )


def test_ordinary_reference_is_allowed_only_for_schema_permitted_non_sensitive_data() -> None:
    reference = _Reference(uri="artifact://run-1/large.json")

    with pytest.raises(EventSecurityError):
        EventSecurityProjector().project(
            payload=None,
            payload_ref=reference,
            extensions={},
            policy=SensitivityPolicy(),
        )

    projected = EventSecurityProjector().project(
        payload=None,
        payload_ref=reference,
        extensions={},
        policy=SensitivityPolicy(allow_payload_reference=True),
    )
    assert projected.payload_ref == {
        "uri": reference.uri,
        "expected_checksum": reference.expected_checksum,
        "content_type": "application/json",
        "size_bytes": reference.size_bytes,
    }

    for unproven_size in (None, 64 * 1024):
        with pytest.raises(EventSecurityError):
            EventSecurityProjector().project(
                payload=None,
                payload_ref=_Reference(size_bytes=unproven_size),
                extensions={},
                policy=SensitivityPolicy(allow_payload_reference=True),
            )


def test_secure_store_must_prove_every_required_capability() -> None:
    incomplete = SecurePayloadCapabilities(
        tenant_authorization=True,
        encryption_in_transit=True,
        encryption_at_rest=False,
        integrity_verification=True,
        audited_access=True,
    )
    with pytest.raises(EventSecurePayloadRequiredError):
        EventSecurityProjector(secure_payload_store=_SecureStore(incomplete)).project(
            payload=None,
            payload_ref=_Reference(),
            extensions={},
            tenant_id="tenant-1",
            classification=SecurityClassification.CONFIDENTIAL,
            policy=SensitivityPolicy(allow_payload_reference=True),
        )

    store = _SecureStore(_complete_capabilities())
    reference = _Reference()
    projected = EventSecurityProjector(secure_payload_store=store).project(
        payload=None,
        payload_ref=reference,
        extensions={},
        tenant_id="tenant-1",
        classification=SecurityClassification.CONFIDENTIAL,
        policy=SensitivityPolicy(allow_payload_reference=True),
    )
    assert projected.payload_ref == {
        "uri": reference.uri,
        "expected_checksum": reference.expected_checksum,
        "content_type": "application/json",
        "size_bytes": reference.size_bytes,
    }
    assert store.calls == [(reference, "tenant-1", SecurityClassification.CONFIDENTIAL)]


def test_reference_only_policy_fails_closed_without_secure_store() -> None:
    with pytest.raises(EventSecurePayloadRequiredError):
        EventSecurityProjector().project(
            payload=None,
            payload_ref=_Reference(),
            extensions={},
            policy=SensitivityPolicy(
                field_rules={"/body": "reference_only"},
                allow_payload_reference=True,
            ),
        )


def test_reference_only_field_is_optional_but_secure_when_present() -> None:
    policy = SensitivityPolicy(
        field_rules={"/items/*/body": "reference_only"},
        allow_payload_reference=True,
    )
    projected = EventSecurityProjector().project(
        payload={"items": [{"title": "safe"}]},
        payload_ref=None,
        extensions={},
        policy=policy,
    )
    assert projected.payload == {"items": ({"title": "safe"},)}

    with pytest.raises(EventSecurePayloadRequiredError) as caught:
        EventSecurityProjector().project(
            payload={"items": [{"body": "protected"}]},
            payload_ref=None,
            extensions={},
            policy=policy,
        )
    assert caught.value.path == "/items/0/body"
    assert "protected" not in str(caught.value)


def test_secure_reference_requires_authoritative_tenant_scope() -> None:
    store = _SecureStore(_complete_capabilities())
    with pytest.raises(EventSecurePayloadRequiredError, match="tenant scope"):
        EventSecurityProjector(secure_payload_store=store).project(
            payload=None,
            payload_ref=_Reference(),
            extensions={},
            classification=SecurityClassification.CONFIDENTIAL,
            policy=SensitivityPolicy(allow_payload_reference=True),
        )
    assert store.calls == []


@pytest.mark.parametrize(
    "missing_capability",
    [
        "tenant_authorization",
        "encryption_in_transit",
        "encryption_at_rest",
        "integrity_verification",
        "audited_access",
    ],
)
def test_secure_reference_requires_each_capability(missing_capability: str) -> None:
    values = {
        "tenant_authorization": True,
        "encryption_in_transit": True,
        "encryption_at_rest": True,
        "integrity_verification": True,
        "audited_access": True,
    }
    values[missing_capability] = False
    store = _SecureStore(SecurePayloadCapabilities(**values))

    with pytest.raises(EventSecurePayloadRequiredError, match="capabilities"):
        EventSecurityProjector(secure_payload_store=store).project(
            payload=None,
            payload_ref=_Reference(),
            extensions={},
            tenant_id="tenant-1",
            classification=SecurityClassification.RESTRICTED,
            policy=SensitivityPolicy(allow_payload_reference=True),
        )
    assert len(store.calls) == 1


def test_tenant_and_classification_are_authoritative_and_propagated() -> None:
    projected = EventSecurityProjector().project(
        payload={"safe": True},
        payload_ref=None,
        extensions={"io.newsroom.feature": "enabled"},
        tenant_id=" tenant-1 ",
        classification=SecurityClassification.INTERNAL,
        policy=SensitivityPolicy(),
    )
    assert projected.tenant_id == "tenant-1"
    assert projected.classification is SecurityClassification.INTERNAL

    for container in (
        {"Tenant-ID": "forged"},
        {"SECURITY_CLASSIFICATION": "public"},
    ):
        with pytest.raises(EventReservedFieldError):
            EventSecurityProjector().project(
                payload={"safe": True},
                payload_ref=None,
                extensions=container,
                tenant_id="tenant-1",
                policy=SensitivityPolicy(),
            )


def test_redacted_diagnostic_removes_secret_values_without_key_substring_false_positive() -> None:
    from framework.events.schema import redact_event_value

    secret = "CaseSensitiveCredential-42"
    projected = redact_event_value(
        {
            "authorization": f"Bearer {secret}",
            "message": f"request failed for casesensitivecredential-42",
            "token_count": 9,
            "secretary": "Ada",
        }
    )

    assert projected["authorization"] == "[REDACTED]"
    assert secret.casefold() not in projected["message"].casefold()
    assert projected["token_count"] == 9
    assert projected["secretary"] == "Ada"


def test_projected_content_is_detached_from_caller_mutation() -> None:
    source = {"nested": {"items": [1, 2]}}
    extensions = {"io.newsroom.safe": {"enabled": True}}
    projected = EventSecurityProjector().project(
        payload=source,
        payload_ref=None,
        extensions=extensions,
        policy=SensitivityPolicy(),
    )
    source["nested"]["items"].append(3)
    extensions["io.newsroom.safe"]["enabled"] = False

    assert projected.payload == {"nested": {"items": (1, 2)}}
    assert projected.extensions == {"io.newsroom.safe": {"enabled": True}}
    with pytest.raises(TypeError):
        projected.payload["nested"]["items"] += (3,)  # type: ignore[index,operator]
    with pytest.raises(TypeError):
        projected.extensions["io.newsroom.safe"]["enabled"] = False  # type: ignore[index]


def test_projector_accepts_existing_canonical_immutable_views() -> None:
    from framework.events.canonical import normalize_canonical_json

    payload = normalize_canonical_json({"nested": {"items": [1, 2]}})
    extensions = normalize_canonical_json({"io.newsroom.safe": {"enabled": True}})
    projected = EventSecurityProjector().project(
        payload=payload,
        payload_ref=None,
        extensions=extensions,
        policy=SensitivityPolicy(),
    )

    assert projected.payload == {"nested": {"items": (1, 2)}}
