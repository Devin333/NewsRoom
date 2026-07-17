from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.events.runtime.models import (
    RedeliveryRequest,
    RetirementCancellationRequest,
    SubscriptionKey,
)
from framework.shared.time import ensure_utc, format_datetime


MAX_AUTHORIZATION_REASON_CLASS_LENGTH = 128


@dataclass(frozen=True, slots=True)
class RedeliveryAuthorizationRequest:
    """Complete immutable operator scope presented to an authorizer."""

    redelivery_id: str
    subscription: SubscriptionKey
    source_stream_id: str
    from_sequence: int
    through_sequence: int | None
    requested_at: datetime
    operator_id: str
    operator_reason: str
    authorization_evidence_ref: str
    tenant_id: str | None
    request_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "redelivery_id",
            "source_stream_id",
            "operator_id",
            "operator_reason",
            "authorization_evidence_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if not isinstance(self.subscription, SubscriptionKey):
            raise TypeError("subscription must be SubscriptionKey")
        object.__setattr__(
            self,
            "from_sequence",
            _positive_int(self.from_sequence, "from_sequence"),
        )
        through_sequence = (
            None
            if self.through_sequence is None
            else _positive_int(self.through_sequence, "through_sequence")
        )
        if through_sequence is not None and through_sequence < self.from_sequence:
            raise ValueError("through_sequence cannot precede from_sequence")
        object.__setattr__(self, "through_sequence", through_sequence)
        object.__setattr__(
            self,
            "requested_at",
            _required_utc(self.requested_at, "requested_at"),
        )
        object.__setattr__(self, "tenant_id", _optional_text(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self,
            "request_checksum",
            checksum_for(self.checksum_projection()),
        )

    @classmethod
    def from_redelivery(
        cls,
        request: RedeliveryRequest,
    ) -> RedeliveryAuthorizationRequest:
        if not isinstance(request, RedeliveryRequest):
            raise TypeError("request must be RedeliveryRequest")
        return cls(
            redelivery_id=request.redelivery_id,
            subscription=request.subscription,
            source_stream_id=request.source_stream_id,
            from_sequence=request.from_sequence,
            through_sequence=request.through_sequence,
            requested_at=request.requested_at,
            operator_id=request.operator_id,
            operator_reason=request.operator_reason,
            authorization_evidence_ref=request.authorization_evidence_ref,
            tenant_id=request.tenant_id,
        )

    def checksum_projection(self) -> dict[str, object]:
        return {
            "redelivery_id": self.redelivery_id,
            "subscription_id": self.subscription.subscription_id,
            "subscription_version": self.subscription.subscription_version,
            "source_stream_id": self.source_stream_id,
            "from_sequence": self.from_sequence,
            "through_sequence": self.through_sequence,
            "requested_at": format_datetime(self.requested_at),
            "operator_id": self.operator_id,
            "operator_reason": self.operator_reason,
            "authorization_evidence_ref": self.authorization_evidence_ref,
            "tenant_id": self.tenant_id,
        }

    def verify_integrity(self) -> None:
        if checksum_for(self.checksum_projection()) != self.request_checksum:
            raise ValueError("redelivery authorization request checksum does not match")


@dataclass(frozen=True, slots=True)
class RedeliveryAuthorizationDecision:
    """Integrity-bound authorization result for exactly one request."""

    request: RedeliveryAuthorizationRequest
    authorized: bool
    decided_at: datetime
    authorization_evidence_ref: str | None = None
    denial_reason_class: str | None = None
    decision_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, RedeliveryAuthorizationRequest):
            raise TypeError("request must be RedeliveryAuthorizationRequest")
        self.request.verify_integrity()
        if not isinstance(self.authorized, bool):
            raise TypeError("authorized must be a boolean")
        decided_at = _required_utc(self.decided_at, "decided_at")
        if decided_at < self.request.requested_at:
            raise ValueError("decided_at cannot precede requested_at")
        object.__setattr__(self, "decided_at", decided_at)
        evidence_ref = _optional_text(
            self.authorization_evidence_ref,
            "authorization_evidence_ref",
        )
        denial_reason = _optional_text(
            self.denial_reason_class,
            "denial_reason_class",
        )
        if denial_reason is not None and len(denial_reason) > MAX_AUTHORIZATION_REASON_CLASS_LENGTH:
            raise ValueError("denial_reason_class exceeds the bounded diagnostic limit")
        if self.authorized:
            if evidence_ref != self.request.authorization_evidence_ref:
                raise ValueError(
                    "authorized decision evidence must match the requested evidence"
                )
            if denial_reason is not None:
                raise ValueError("authorized decision cannot contain a denial reason")
        else:
            if denial_reason is None:
                raise ValueError("denied decision requires a denial_reason_class")
            if evidence_ref is not None:
                raise ValueError("denied decision cannot contain authorization evidence")
        object.__setattr__(self, "authorization_evidence_ref", evidence_ref)
        object.__setattr__(self, "denial_reason_class", denial_reason)
        object.__setattr__(
            self,
            "decision_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, object]:
        return {
            "request_checksum": self.request.request_checksum,
            "authorized": self.authorized,
            "decided_at": format_datetime(self.decided_at),
            "authorization_evidence_ref": self.authorization_evidence_ref,
            "denial_reason_class": self.denial_reason_class,
        }

    def verify_integrity(self) -> None:
        self.request.verify_integrity()
        if checksum_for(self.checksum_projection()) != self.decision_checksum:
            raise ValueError("redelivery authorization decision checksum does not match")


@dataclass(frozen=True, slots=True)
class RetirementCancellationAuthorizationRequest:
    """Exact retired-subscription cancellation scope presented to an authorizer."""

    cancellation_id: str
    subscription: SubscriptionKey
    requested_at: datetime
    operator_id: str
    operator_reason: str
    authorization_evidence_ref: str
    tenant_id: str | None
    limit: int
    request_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        for field_name in (
            "cancellation_id",
            "operator_id",
            "operator_reason",
            "authorization_evidence_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name),
            )
        if not isinstance(self.subscription, SubscriptionKey):
            raise TypeError("subscription must be SubscriptionKey")
        object.__setattr__(
            self,
            "requested_at",
            _required_utc(self.requested_at, "requested_at"),
        )
        object.__setattr__(self, "tenant_id", _optional_text(self.tenant_id, "tenant_id"))
        object.__setattr__(self, "limit", _positive_int(self.limit, "limit"))
        object.__setattr__(
            self,
            "request_checksum",
            checksum_for(self.checksum_projection()),
        )

    @classmethod
    def from_cancellation(
        cls,
        request: RetirementCancellationRequest,
    ) -> RetirementCancellationAuthorizationRequest:
        if not isinstance(request, RetirementCancellationRequest):
            raise TypeError("request must be RetirementCancellationRequest")
        return cls(
            cancellation_id=request.cancellation_id,
            subscription=request.subscription,
            requested_at=request.requested_at,
            operator_id=request.operator_id,
            operator_reason=request.operator_reason,
            authorization_evidence_ref=request.authorization_evidence_ref,
            tenant_id=request.tenant_id,
            limit=request.limit,
        )

    def checksum_projection(self) -> dict[str, object]:
        return {
            "cancellation_id": self.cancellation_id,
            "subscription_id": self.subscription.subscription_id,
            "subscription_version": self.subscription.subscription_version,
            "requested_at": format_datetime(self.requested_at),
            "operator_id": self.operator_id,
            "operator_reason": self.operator_reason,
            "authorization_evidence_ref": self.authorization_evidence_ref,
            "tenant_id": self.tenant_id,
            "limit": self.limit,
        }

    def verify_integrity(self) -> None:
        if checksum_for(self.checksum_projection()) != self.request_checksum:
            raise ValueError(
                "retirement cancellation authorization request checksum does not match"
            )


@dataclass(frozen=True, slots=True)
class RetirementCancellationAuthorizationDecision:
    """Integrity-bound authorization result for one cancellation command."""

    request: RetirementCancellationAuthorizationRequest
    authorized: bool
    decided_at: datetime
    authorization_evidence_ref: str | None = None
    denial_reason_class: str | None = None
    decision_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, RetirementCancellationAuthorizationRequest):
            raise TypeError(
                "request must be RetirementCancellationAuthorizationRequest"
            )
        self.request.verify_integrity()
        if not isinstance(self.authorized, bool):
            raise TypeError("authorized must be a boolean")
        decided_at = _required_utc(self.decided_at, "decided_at")
        if decided_at < self.request.requested_at:
            raise ValueError("decided_at cannot precede requested_at")
        object.__setattr__(self, "decided_at", decided_at)
        evidence_ref = _optional_text(
            self.authorization_evidence_ref,
            "authorization_evidence_ref",
        )
        denial_reason = _optional_text(
            self.denial_reason_class,
            "denial_reason_class",
        )
        if denial_reason is not None and len(denial_reason) > MAX_AUTHORIZATION_REASON_CLASS_LENGTH:
            raise ValueError("denial_reason_class exceeds the bounded diagnostic limit")
        if self.authorized:
            if evidence_ref != self.request.authorization_evidence_ref:
                raise ValueError(
                    "authorized decision evidence must match the requested evidence"
                )
            if denial_reason is not None:
                raise ValueError("authorized decision cannot contain a denial reason")
        else:
            if denial_reason is None:
                raise ValueError("denied decision requires a denial_reason_class")
            if evidence_ref is not None:
                raise ValueError("denied decision cannot contain authorization evidence")
        object.__setattr__(self, "authorization_evidence_ref", evidence_ref)
        object.__setattr__(self, "denial_reason_class", denial_reason)
        object.__setattr__(
            self,
            "decision_checksum",
            checksum_for(self.checksum_projection()),
        )

    def checksum_projection(self) -> dict[str, object]:
        return {
            "request_checksum": self.request.request_checksum,
            "authorized": self.authorized,
            "decided_at": format_datetime(self.decided_at),
            "authorization_evidence_ref": self.authorization_evidence_ref,
            "denial_reason_class": self.denial_reason_class,
        }

    def verify_integrity(self) -> None:
        self.request.verify_integrity()
        if checksum_for(self.checksum_projection()) != self.decision_checksum:
            raise ValueError(
                "retirement cancellation authorization decision checksum does not match"
            )


@runtime_checkable
class RedeliveryAuthorizerPort(Protocol):
    def authorize(
        self,
        request: RedeliveryAuthorizationRequest,
    ) -> RedeliveryAuthorizationDecision:
        """Authorize one complete tenant-scoped operator request."""
        ...


@runtime_checkable
class RetirementCancellationAuthorizerPort(Protocol):
    def authorize(
        self,
        request: RetirementCancellationAuthorizationRequest,
    ) -> RetirementCancellationAuthorizationDecision:
        """Authorize one exact tenant-scoped retirement cancellation."""
        ...


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name)


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _required_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return ensure_utc(value)


__all__ = [
    "MAX_AUTHORIZATION_REASON_CLASS_LENGTH",
    "RedeliveryAuthorizationDecision",
    "RedeliveryAuthorizationRequest",
    "RedeliveryAuthorizerPort",
    "RetirementCancellationAuthorizationDecision",
    "RetirementCancellationAuthorizationRequest",
    "RetirementCancellationAuthorizerPort",
]
