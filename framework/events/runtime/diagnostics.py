from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Final, Iterable

from framework.events.subscriber import (
    ConsumerFailure,
    MAX_CONSUMER_REASON_CLASS_LENGTH,
)


_REASON_CODE: Final = re.compile(r"[a-z][a-z0-9_.-]*\Z")
_DIAGNOSTIC_PREFIX: Final = "redacted:sha256:"


@dataclass(frozen=True, slots=True)
class ProjectedDeliveryDiagnostic:
    reason_class: str
    redacted_diagnostic: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reason_class",
            _reason_code(self.reason_class, "reason_class"),
        )
        if self.redacted_diagnostic is not None:
            value = str(self.redacted_diagnostic)
            if not value.startswith(_DIAGNOSTIC_PREFIX):
                raise ValueError("projected diagnostic must be a redaction fingerprint")
            digest = value.removeprefix(_DIAGNOSTIC_PREFIX)
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise ValueError("projected diagnostic fingerprint is invalid")
            object.__setattr__(self, "redacted_diagnostic", value)


class DeliveryDiagnosticProjector:
    """Projects untrusted consumer diagnostics before durable persistence.

    Caller-provided diagnostics are never persisted verbatim.  Reason classes
    are retained only when composition explicitly allowlists the exact code;
    otherwise the runtime-owned fallback classification is used.  A stable
    fingerprint supports correlation without retaining credentials, headers,
    exception messages, or arbitrary consumer text.
    """

    def __init__(self, allowed_reason_classes: Iterable[str] = ()) -> None:
        if isinstance(allowed_reason_classes, (str, bytes)):
            raise TypeError("allowed_reason_classes must be a collection")
        self._allowed_reason_classes = frozenset(
            _reason_code(value, "allowed reason_class")
            for value in allowed_reason_classes
        )

    def project(
        self,
        *,
        reason_class: str,
        redacted_diagnostic: str | None,
        fallback_reason_class: str,
    ) -> ProjectedDeliveryDiagnostic:
        fallback = _reason_code(fallback_reason_class, "fallback_reason_class")
        raw_reason = str(reason_class)
        persisted_reason = (
            raw_reason
            if raw_reason in self._allowed_reason_classes
            else fallback
        )
        fingerprint = _fingerprint(raw_reason, redacted_diagnostic)
        return ProjectedDeliveryDiagnostic(
            reason_class=persisted_reason,
            redacted_diagnostic=fingerprint,
        )

    def project_failure(
        self,
        failure: ConsumerFailure,
        *,
        fallback_reason_class: str,
    ) -> ConsumerFailure:
        if not isinstance(failure, ConsumerFailure):
            raise TypeError("failure must be ConsumerFailure")
        projected = self.project(
            reason_class=failure.reason_class,
            redacted_diagnostic=failure.redacted_diagnostic,
            fallback_reason_class=fallback_reason_class,
        )
        return ConsumerFailure(
            kind=failure.kind,
            reason_class=projected.reason_class,
            redacted_diagnostic=projected.redacted_diagnostic,
        )


def _fingerprint(reason_class: str, diagnostic: str | None) -> str | None:
    if not reason_class and diagnostic is None:
        return None
    digest = sha256()
    digest.update(b"newsroom-delivery-diagnostic-v1\0")
    digest.update(reason_class.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    if diagnostic is not None:
        digest.update(str(diagnostic).encode("utf-8", errors="replace"))
    return f"{_DIAGNOSTIC_PREFIX}{digest.hexdigest()}"


def _reason_code(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_CONSUMER_REASON_CLASS_LENGTH
        or _REASON_CODE.fullmatch(normalized) is None
    ):
        raise ValueError(
            f"{field_name} must be a bounded lowercase diagnostic code"
        )
    return normalized


__all__ = [
    "DeliveryDiagnosticProjector",
    "ProjectedDeliveryDiagnostic",
]
