from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class ModelContextProfile:
    provider: str
    model: str
    deployment_id: str
    physical_context_window_tokens: int
    max_output_tokens: int
    default_output_tokens: int
    tokenizer_family: str
    tokenizer_revision: str
    normalizer_revision: str
    profile_revision: str
    operational_input_fraction: float = 0.9
    safety_margin_tokens: int = 0
    allow_conservative_fallback: bool = False
    provider_auto_truncation: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "provider",
            "model",
            "deployment_id",
            "tokenizer_family",
            "tokenizer_revision",
            "normalizer_revision",
            "profile_revision",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
            object.__setattr__(self, field_name, value.strip())

        for field_name in (
            "physical_context_window_tokens",
            "max_output_tokens",
            "default_output_tokens",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")

        if self.default_output_tokens > self.max_output_tokens:
            raise ValueError("default_output_tokens must not exceed max_output_tokens")
        if (
            not isinstance(self.operational_input_fraction, (int, float))
            or isinstance(self.operational_input_fraction, bool)
            or not isfinite(float(self.operational_input_fraction))
            or not 0 < float(self.operational_input_fraction) <= 1
        ):
            raise ValueError("operational_input_fraction must be in (0, 1]")
        if (
            isinstance(self.safety_margin_tokens, bool)
            or not isinstance(self.safety_margin_tokens, int)
            or self.safety_margin_tokens < 0
        ):
            raise ValueError("safety_margin_tokens must be a non-negative integer")
        if not isinstance(self.allow_conservative_fallback, bool):
            raise ValueError("allow_conservative_fallback must be a boolean")
        if not isinstance(self.provider_auto_truncation, bool):
            raise ValueError("provider_auto_truncation must be a boolean")

    def assert_deployment_identity(
        self,
        *,
        deployment_id: str,
        provider: str,
        model: str,
    ) -> None:
        expected = (self.deployment_id, self.provider, self.model)
        actual = (deployment_id, provider, model)
        if actual != expected:
            raise ValueError(
                "context profile identity does not match deployment: "
                f"expected={expected!r}, actual={actual!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "deployment_id": self.deployment_id,
            "physical_context_window_tokens": self.physical_context_window_tokens,
            "max_output_tokens": self.max_output_tokens,
            "default_output_tokens": self.default_output_tokens,
            "tokenizer_family": self.tokenizer_family,
            "tokenizer_revision": self.tokenizer_revision,
            "normalizer_revision": self.normalizer_revision,
            "profile_revision": self.profile_revision,
            "operational_input_fraction": self.operational_input_fraction,
            "safety_margin_tokens": self.safety_margin_tokens,
            "allow_conservative_fallback": self.allow_conservative_fallback,
            "provider_auto_truncation": self.provider_auto_truncation,
        }
