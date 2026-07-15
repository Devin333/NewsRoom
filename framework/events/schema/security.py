from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from framework.events.errors import (
    EventReservedFieldError,
    EventSecurePayloadRequiredError,
    EventSecurityError,
)
from framework.events.schema.policy import FieldDisposition, SensitivityPolicy


class SecurityClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


PROTECTED_CLASSIFICATIONS = {
    SecurityClassification.CONFIDENTIAL,
    SecurityClassification.RESTRICTED,
}

RESERVED_EVENT_FIELDS = frozenset(
    {
        "envelope_schema",
        "event_id",
        "event_type",
        "data_schema",
        "source",
        "subject",
        "occurred_at",
        "observed_at",
        "stream_id",
        "stream_sequence",
        "correlation_id",
        "causation_id",
        "business_context",
        "producer",
        "trace",
        "tenant_id",
        "security_classification",
        "content_type",
        "payload",
        "payload_ref",
        "extensions",
        "content_checksum",
        "record_checksum",
    }
)

# Exact normalized key matches only. Legitimate keys such as ``token_count``
# and ``secretary`` must not be redacted by substring coincidence.
DEFAULT_FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "auth_token",
        "authorization",
        "bearer_token",
        "client_secret",
        "cookie",
        "credentials",
        "database_url",
        "dsn",
        "id_token",
        "jwt",
        "passphrase",
        "password",
        "private_key",
        "proxy_authorization",
        "refresh_token",
        "secret",
        "secret_key",
        "session_token",
        "set_cookie",
        "ssh_private_key",
        "access_token",
        "x_api_key",
    }
)


def redact_event_value(
    value: Any,
    *,
    forbidden_secret_keys: frozenset[str] = DEFAULT_FORBIDDEN_SECRET_KEYS,
) -> Any:
    """Return a detached export-safe value using exact secret-key policy.

    Secret values found under forbidden keys are also removed from sibling
    diagnostic strings so compatibility exports cannot leak the same token in
    a free-form message. This helper is for read/export projection only; live
    publication still uses the fail-closed projector above.
    """

    normalized_keys = frozenset(_normalize_key(key) for key in forbidden_secret_keys)
    secret_values: set[str] = set()
    _collect_secret_values(value, normalized_keys, secret_values)
    return _redact_value(value, normalized_keys, secret_values)


@dataclass(frozen=True)
class SecurePayloadCapabilities:
    tenant_authorization: bool
    encryption_in_transit: bool
    encryption_at_rest: bool
    integrity_verification: bool
    audited_access: bool

    def __post_init__(self) -> None:
        for field_name in (
            "tenant_authorization",
            "encryption_in_transit",
            "encryption_at_rest",
            "integrity_verification",
            "audited_access",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise TypeError(f"{field_name} must be a bool")

    @property
    def complete(self) -> bool:
        return all(
            (
                self.tenant_authorization,
                self.encryption_in_transit,
                self.encryption_at_rest,
                self.integrity_verification,
                self.audited_access,
            )
        )


@runtime_checkable
class SecurePayloadStorePort(Protocol):
    def validate_reference(
        self,
        reference: Any,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> SecurePayloadCapabilities:
        ...


@dataclass(frozen=True)
class SecurityProjection:
    payload: Mapping[str, Any] | None
    payload_ref: Mapping[str, Any] | None
    extensions: Mapping[str, Any]
    tenant_id: str | None
    classification: SecurityClassification

    def __post_init__(self) -> None:
        if self.payload is not None and not isinstance(self.payload, Mapping):
            raise EventSecurityError("projected payload must be an object")
        if self.payload_ref is not None and not isinstance(self.payload_ref, Mapping):
            raise EventSecurityError("projected payload reference must be an object")
        if not isinstance(self.extensions, Mapping):
            raise EventSecurityError("projected extensions must be an object")
        object.__setattr__(
            self,
            "payload",
            None if self.payload is None else _freeze_projected_mapping(self.payload),
        )
        object.__setattr__(
            self,
            "payload_ref",
            (
                None
                if self.payload_ref is None
                else _freeze_projected_mapping(self.payload_ref)
            ),
        )
        object.__setattr__(
            self,
            "extensions",
            _freeze_projected_mapping(self.extensions),
        )
        object.__setattr__(self, "tenant_id", _optional_text(self.tenant_id))
        object.__setattr__(
            self,
            "classification",
            SecurityClassification(self.classification),
        )


class EventSecurityProjector:
    """Applies one fail-closed schema/security policy before durable writes."""

    def __init__(
        self,
        *,
        secure_payload_store: SecurePayloadStorePort | None = None,
        forbidden_secret_keys: frozenset[str] = DEFAULT_FORBIDDEN_SECRET_KEYS,
    ) -> None:
        self._secure_payload_store = secure_payload_store
        self._forbidden_secret_keys = frozenset(
            _normalize_key(key) for key in forbidden_secret_keys
        )

    def project(
        self,
        *,
        payload: Mapping[str, Any] | None,
        payload_ref: Any | None,
        extensions: Mapping[str, Any] | None,
        policy: SensitivityPolicy,
        classification: SecurityClassification | str = SecurityClassification.INTERNAL,
        tenant_id: str | None = None,
    ) -> SecurityProjection:
        try:
            actual_classification = SecurityClassification(classification)
        except (TypeError, ValueError) as exc:
            raise EventSecurityError("invalid security classification") from exc
        actual_tenant = _optional_text(tenant_id)
        if extensions is not None and not isinstance(extensions, Mapping):
            raise EventSecurityError("event extensions must be an object")
        actual_extensions = _thaw_projector_value(extensions or {}, path="/extensions")
        self._validate_reserved_extensions(actual_extensions)

        if payload is not None and payload_ref is not None:
            raise EventSecurityError("payload and payload_ref are mutually exclusive")
        if payload is None and payload_ref is None:
            actual_payload: dict[str, Any] | None = {}
        elif payload is None:
            actual_payload = None
        else:
            if not isinstance(payload, Mapping):
                raise EventSecurityError("event payload must be an object")
            self._validate_reserved_payload(payload)
            payload_copy = _thaw_projector_value(payload, path="/payload")
            actual_payload = self._project_value(payload_copy, policy=policy, pointer="")

        requires_secure_reference = actual_classification in PROTECTED_CLASSIFICATIONS
        if payload_ref is not None and policy.has_reference_only_fields:
            requires_secure_reference = True

        if requires_secure_reference:
            if actual_payload not in (None, {}):
                raise EventSecurePayloadRequiredError(
                    "protected event content must not be stored inline"
                )
            self._validate_secure_reference(
                payload_ref,
                tenant_id=actual_tenant,
                classification=actual_classification,
            )
        elif payload_ref is not None:
            _validate_integrity_reference(payload_ref)
            size_bytes = _reference_size_bytes(payload_ref)
            if not policy.permits_ordinary_reference(size_bytes=size_bytes):
                raise EventSecurityError(
                    "ordinary payload reference requires schema permission and "
                    "declared oversized non-sensitive content"
                )

        detached_reference = _detach_reference(payload_ref)

        return SecurityProjection(
            payload=actual_payload,
            payload_ref=detached_reference,
            extensions=self._project_value(
                actual_extensions,
                policy=SensitivityPolicy(
                    field_rules={},
                    redact_sensitive=policy.redact_sensitive,
                ),
                pointer="/extensions",
            ),
            tenant_id=actual_tenant,
            classification=actual_classification,
        )

    def _project_value(
        self,
        value: Any,
        *,
        policy: SensitivityPolicy,
        pointer: str,
    ) -> Any:
        disposition = policy.disposition_for(pointer)
        if disposition is FieldDisposition.FORBIDDEN:
            raise EventSecurityError("forbidden event field", path=pointer or "/")
        if disposition is FieldDisposition.REFERENCE_ONLY:
            raise EventSecurePayloadRequiredError(
                "reference-only event field cannot be stored inline",
                path=pointer or "/",
            )
        if disposition is FieldDisposition.SENSITIVE:
            if policy.redact_sensitive:
                return "[REDACTED]"
            raise EventSecurityError(
                "sensitive event field requires an explicit protected representation",
                path=pointer or "/",
            )
        if isinstance(value, Mapping):
            projected: dict[str, Any] = {}
            for raw_key, item in value.items():
                if not isinstance(raw_key, str):
                    raise EventSecurityError(
                        "event object keys must be strings",
                        path=pointer or "/",
                    )
                key = str(raw_key)
                child_pointer = f"{pointer}/{_escape_pointer(key)}"
                if _normalize_key(key) in self._forbidden_secret_keys:
                    raise EventSecurityError("forbidden secret field", path=child_pointer)
                projected[key] = self._project_value(
                    item,
                    policy=policy,
                    pointer=child_pointer,
                )
            return projected
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [
                self._project_value(
                    item,
                    policy=policy,
                    pointer=f"{pointer}/{index}",
                )
                for index, item in enumerate(value)
            ]
        return copy.deepcopy(value)

    def _validate_reserved_extensions(self, extensions: Mapping[str, Any]) -> None:
        for raw_key in extensions:
            if not isinstance(raw_key, str):
                raise EventSecurityError(
                    "event extension keys must be strings",
                    path="/extensions",
                )
            key = str(raw_key)
            if _normalize_key(key) in RESERVED_EVENT_FIELDS:
                raise EventReservedFieldError(
                    "extension cannot override an infrastructure-owned event field",
                    path=f"/extensions/{_escape_pointer(key)}",
                )

    def _validate_reserved_payload(self, payload: Mapping[str, Any]) -> None:
        for raw_key in payload:
            if not isinstance(raw_key, str):
                raise EventSecurityError(
                    "event payload keys must be strings",
                    path="/payload",
                )
            key = str(raw_key)
            if _normalize_key(key) in RESERVED_EVENT_FIELDS:
                raise EventReservedFieldError(
                    "payload cannot override an infrastructure-owned event field",
                    path=f"/payload/{_escape_pointer(key)}",
                )

    def _validate_secure_reference(
        self,
        reference: Any | None,
        *,
        tenant_id: str | None,
        classification: SecurityClassification,
    ) -> None:
        if reference is None:
            raise EventSecurePayloadRequiredError(
                "protected event content requires a secure payload reference"
            )
        _validate_integrity_reference(reference)
        if tenant_id is None:
            raise EventSecurePayloadRequiredError(
                "secure payload reference requires an authoritative tenant scope"
            )
        if self._secure_payload_store is None:
            raise EventSecurePayloadRequiredError(
                "secure payload store is not configured"
            )
        try:
            capabilities = self._secure_payload_store.validate_reference(
                reference,
                tenant_id=tenant_id,
                classification=classification,
            )
        except EventSecurityError:
            raise
        except Exception as exc:
            raise EventSecurePayloadRequiredError(
                "secure payload reference validation failed"
            ) from exc
        if not isinstance(capabilities, SecurePayloadCapabilities) or not capabilities.complete:
            raise EventSecurePayloadRequiredError(
                "secure payload store does not satisfy required capabilities"
            )


def _validate_integrity_reference(reference: Any) -> None:
    uri = _reference_value(reference, "uri") or _reference_value(reference, "reference")
    checksum = _reference_value(reference, "expected_checksum") or _reference_value(
        reference, "checksum"
    )
    if not uri:
        raise EventSecurityError("payload reference uri is required")
    if not checksum or re.fullmatch(r"sha256:[0-9a-fA-F]{64}", str(checksum)) is None:
        raise EventSecurityError("payload reference sha256 checksum is required")


def _reference_value(reference: Any, name: str) -> Any:
    if isinstance(reference, Mapping):
        return reference.get(name)
    return getattr(reference, name, None)


def _reference_size_bytes(reference: Any) -> int | None:
    value = _reference_value(reference, "size_bytes")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _detach_reference(reference: Any | None) -> dict[str, Any] | None:
    if reference is None:
        return None
    uri = _reference_value(reference, "uri") or _reference_value(reference, "reference")
    checksum = _reference_value(reference, "expected_checksum") or _reference_value(
        reference,
        "checksum",
    )
    content_type = _reference_value(reference, "content_type") or "application/json"
    size_bytes = _reference_size_bytes(reference)
    if not isinstance(uri, str) or not uri.strip():
        raise EventSecurityError("payload reference uri is required")
    if not isinstance(checksum, str):
        raise EventSecurityError("payload reference sha256 checksum is required")
    if not isinstance(content_type, str) or not content_type.strip():
        raise EventSecurityError("payload reference content_type is required")
    return {
        "uri": uri.strip(),
        "expected_checksum": checksum.strip().lower(),
        "content_type": content_type.strip(),
        "size_bytes": size_bytes,
    }


def _normalize_key(key: str) -> str:
    return str(key).strip().casefold().replace("-", "_")


def _escape_pointer(value: str) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EventSecurityError("tenant_id must be a string")
    text = value.strip()
    return text or None


def _thaw_projector_value(value: Any, *, path: str) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise EventSecurityError("event object keys must be strings", path=path)
            result[key] = _thaw_projector_value(item, path=f"{path}/{_escape_pointer(key)}")
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _thaw_projector_value(item, path=f"{path}/{index}")
            for index, item in enumerate(value)
        ]
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise EventSecurityError("event number must be finite", path=path)
        return 0 if value == 0 else value
    raise EventSecurityError(
        f"unsupported event value type: {type(value).__name__}",
        path=path,
    )


def _freeze_projected_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            key: _freeze_projected_value(item)
            for key, item in value.items()
        }
    )


def _freeze_projected_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_projected_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_projected_value(item) for item in value)
    return value


def _collect_secret_values(
    value: Any,
    forbidden_keys: frozenset[str],
    collected: set[str],
) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            if _normalize_key(str(raw_key)) in forbidden_keys:
                _collect_string_leaves(item, collected)
                continue
            _collect_secret_values(item, forbidden_keys, collected)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_secret_values(item, forbidden_keys, collected)


def _collect_string_leaves(value: Any, collected: set[str]) -> None:
    if isinstance(value, str):
        if value:
            collected.add(value)
            if value.casefold().startswith("bearer "):
                bearer_value = value[7:].strip()
                if bearer_value:
                    collected.add(bearer_value)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            _collect_string_leaves(item, collected)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            _collect_string_leaves(item, collected)


def _redact_value(
    value: Any,
    forbidden_keys: frozenset[str],
    secret_values: set[str],
) -> Any:
    if isinstance(value, Mapping):
        return {
            str(raw_key): (
                "[REDACTED]"
                if _normalize_key(str(raw_key)) in forbidden_keys
                else _redact_value(item, forbidden_keys, secret_values)
            )
            for raw_key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_value(item, forbidden_keys, secret_values) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in sorted(secret_values, key=len, reverse=True):
            redacted = re.sub(re.escape(secret), "[REDACTED]", redacted, flags=re.IGNORECASE)
        return redacted
    return copy.deepcopy(value)
