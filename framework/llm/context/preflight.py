from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from math import floor
from typing import Any

from framework.llm.context.normalization import (
    LLMRequestNormalizerRegistry,
    NormalizedLLMRequest,
)
from framework.llm.context.profile import ModelContextProfile
from framework.llm.context.tokens import (
    LLMTokenCount,
    LLMTokenCounterRegistry,
    canonical_json_bytes,
)
from framework.llm.models.request import LLMRequest


class LLMContextAdmissionStatus(StrEnum):
    ADMITTED = "admitted"
    PROFILE_REQUIRED = "profile_required"
    NORMALIZER_UNAVAILABLE = "normalizer_unavailable"
    COUNTER_UNAVAILABLE = "counter_unavailable"
    OUTPUT_LIMIT_EXCEEDED = "output_limit_exceeded"
    INPUT_LIMIT_EXCEEDED = "input_limit_exceeded"
    PROVIDER_AUTO_TRUNCATION_FORBIDDEN = "provider_auto_truncation_forbidden"


@dataclass(frozen=True)
class EffectiveContextBudget:
    physical_limit_tokens: int
    operational_limit_tokens: int
    requested_output_tokens: int
    reserved_output_tokens: int
    safety_margin_tokens: int
    max_input_tokens: int

    def __post_init__(self) -> None:
        for field_name in (
            "physical_limit_tokens",
            "operational_limit_tokens",
            "requested_output_tokens",
            "reserved_output_tokens",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if (
            isinstance(self.safety_margin_tokens, bool)
            or not isinstance(self.safety_margin_tokens, int)
            or self.safety_margin_tokens < 0
        ):
            raise ValueError("safety_margin_tokens must be a non-negative integer")
        if isinstance(self.max_input_tokens, bool) or not isinstance(self.max_input_tokens, int):
            raise ValueError("max_input_tokens must be an integer")
        if self.operational_limit_tokens > self.physical_limit_tokens:
            raise ValueError("operational_limit_tokens must not exceed physical_limit_tokens")

    def to_dict(self) -> dict[str, int]:
        return {
            "physical_limit_tokens": self.physical_limit_tokens,
            "operational_limit_tokens": self.operational_limit_tokens,
            "requested_output_tokens": self.requested_output_tokens,
            "reserved_output_tokens": self.reserved_output_tokens,
            "safety_margin_tokens": self.safety_margin_tokens,
            "max_input_tokens": self.max_input_tokens,
        }


@dataclass(frozen=True)
class LLMContextAdmission:
    status: LLMContextAdmissionStatus
    reason: str
    provider_call_authorized: bool

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("reason must be a non-empty string")
        if self.provider_call_authorized != (self.status is LLMContextAdmissionStatus.ADMITTED):
            raise ValueError("provider_call_authorized must be true only for admitted requests")

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "provider_call_authorized": self.provider_call_authorized,
        }


@dataclass(frozen=True)
class PreparedLLMRequest:
    normalized_request: LLMRequest
    payload_fingerprint: str
    deployment_id: str
    provider: str
    model: str
    profile_revision: str
    normalizer_revision: str
    token_count: LLMTokenCount
    effective_budget: EffectiveContextBudget
    admission: LLMContextAdmission

    def __post_init__(self) -> None:
        if not self.payload_fingerprint.startswith("sha256:") or len(self.payload_fingerprint) != 71:
            raise ValueError("payload_fingerprint must be a sha256 digest")
        object.__setattr__(
            self,
            "normalized_request",
            LLMRequest.from_dict(self.normalized_request.to_dict(redact=False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_fingerprint": self.payload_fingerprint,
            "deployment_id": self.deployment_id,
            "provider": self.provider,
            "model": self.model,
            "profile_revision": self.profile_revision,
            "normalizer_revision": self.normalizer_revision,
            "token_count": self.token_count.to_dict(),
            "effective_budget": self.effective_budget.to_dict(),
            "admission": self.admission.to_dict(),
        }


class LLMRequestPreparer:
    def __init__(
        self,
        *,
        normalizers: LLMRequestNormalizerRegistry,
        token_counters: LLMTokenCounterRegistry,
        forbid_provider_auto_truncation: bool = True,
    ) -> None:
        self._normalizers = normalizers
        self._token_counters = token_counters
        self._forbid_provider_auto_truncation = forbid_provider_auto_truncation

    def prepare(
        self,
        request: LLMRequest,
        profile: ModelContextProfile,
    ) -> PreparedLLMRequest:
        normalizer = self._normalizers.resolve(
            provider=profile.provider,
            revision=profile.normalizer_revision,
        )
        if normalizer is None:
            normalized = _unavailable_normalized_request(request, profile)
            token_count = LLMTokenCount.unavailable(profile)
            budget = _effective_budget(request, profile)
            return _prepared(
                normalized,
                profile,
                token_count,
                budget,
                status=LLMContextAdmissionStatus.NORMALIZER_UNAVAILABLE,
                reason="no request normalizer is registered for the deployment profile",
            )

        normalized = normalizer.normalize(
            request,
            provider=profile.provider,
            model=profile.model,
        )
        if normalized.provider.casefold() != profile.provider.casefold():
            raise ValueError("request normalizer returned a mismatched provider")
        if normalized.normalizer_revision != profile.normalizer_revision:
            raise ValueError("request normalizer revision does not match context profile")

        token_count = self._token_counters.count(
            normalized.payload,
            profile=profile,
            normalizer_revision=normalized.normalizer_revision,
        )
        budget = _effective_budget(request, profile)
        if token_count is None:
            return _prepared(
                normalized,
                profile,
                LLMTokenCount.unavailable(profile),
                budget,
                status=LLMContextAdmissionStatus.COUNTER_UNAVAILABLE,
                reason="no permitted token counter is available for the deployment profile",
            )

        requested_output = budget.requested_output_tokens
        if requested_output > profile.max_output_tokens:
            return _prepared(
                normalized,
                profile,
                token_count,
                budget,
                status=LLMContextAdmissionStatus.OUTPUT_LIMIT_EXCEEDED,
                reason="requested output exceeds the deployment maximum output",
            )
        if self._forbid_provider_auto_truncation and profile.provider_auto_truncation:
            return _prepared(
                normalized,
                profile,
                token_count,
                budget,
                status=LLMContextAdmissionStatus.PROVIDER_AUTO_TRUNCATION_FORBIDDEN,
                reason="provider auto-truncation is forbidden for strict context admission",
            )
        if budget.max_input_tokens < 1 or token_count.total_input_tokens > budget.max_input_tokens:
            return _prepared(
                normalized,
                profile,
                token_count,
                budget,
                status=LLMContextAdmissionStatus.INPUT_LIMIT_EXCEEDED,
                reason="normalized input exceeds the deployment effective input budget",
            )
        return _prepared(
            normalized,
            profile,
            token_count,
            budget,
            status=LLMContextAdmissionStatus.ADMITTED,
            reason="normalized request fits the deployment effective context budget",
        )


def _effective_budget(
    request: LLMRequest,
    profile: ModelContextProfile,
) -> EffectiveContextBudget:
    requested_output = request.max_tokens
    if requested_output is None:
        requested_output = profile.default_output_tokens
    if isinstance(requested_output, bool) or not isinstance(requested_output, int) or requested_output < 1:
        raise ValueError("request max_tokens must be a positive integer when provided")
    operational_limit = floor(
        profile.physical_context_window_tokens * profile.operational_input_fraction
    )
    return EffectiveContextBudget(
        physical_limit_tokens=profile.physical_context_window_tokens,
        operational_limit_tokens=operational_limit,
        requested_output_tokens=requested_output,
        reserved_output_tokens=requested_output,
        safety_margin_tokens=profile.safety_margin_tokens,
        max_input_tokens=(
            operational_limit - requested_output - profile.safety_margin_tokens
        ),
    )


def _prepared(
    normalized: NormalizedLLMRequest,
    profile: ModelContextProfile,
    token_count: LLMTokenCount,
    budget: EffectiveContextBudget,
    *,
    status: LLMContextAdmissionStatus,
    reason: str,
) -> PreparedLLMRequest:
    fingerprint = prepared_request_fingerprint(
        normalized.payload,
        profile=profile,
        normalizer_revision=normalized.normalizer_revision,
    )
    return PreparedLLMRequest(
        normalized_request=normalized.request,
        payload_fingerprint=fingerprint,
        deployment_id=profile.deployment_id,
        provider=profile.provider,
        model=profile.model,
        profile_revision=profile.profile_revision,
        normalizer_revision=normalized.normalizer_revision,
        token_count=token_count,
        effective_budget=budget,
        admission=LLMContextAdmission(
            status=status,
            reason=reason,
            provider_call_authorized=status is LLMContextAdmissionStatus.ADMITTED,
        ),
    )


def prepared_request_fingerprint(
    payload: dict[str, Any],
    *,
    profile: ModelContextProfile,
    normalizer_revision: str,
) -> str:
    identity = {
        "schema": "newsroom.llm_prepared_request.v1",
        "deployment_id": profile.deployment_id,
        "provider": profile.provider,
        "model": profile.model,
        "profile_revision": profile.profile_revision,
        "normalizer_revision": normalizer_revision,
        "payload": payload,
    }
    return f"sha256:{sha256(canonical_json_bytes(identity)).hexdigest()}"


def _unavailable_normalized_request(
    request: LLMRequest,
    profile: ModelContextProfile,
) -> NormalizedLLMRequest:
    normalized_request = LLMRequest.from_dict(
        {
            **request.to_dict(redact=False),
            "model": profile.model,
        }
    )
    payload = normalized_request.to_dict(redact=False)
    payload.pop("metadata", None)
    return NormalizedLLMRequest(
        request=normalized_request,
        payload=payload,
        provider=profile.provider,
        normalizer_revision=profile.normalizer_revision,
    )
