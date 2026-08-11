from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
UTC = _tz.utc
from typing import Any

from framework.llm.budget import ModelPricing
from framework.llm.context.profile import ModelContextProfile
from framework.llm.models import LLMClient, ModelCapabilities


@dataclass(frozen=True)
class ModelDeployment:
    deployment_id: str
    provider: str
    model: str
    client: LLMClient
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    pricing: ModelPricing | None = None
    enabled: bool = True
    cooldown_until: datetime | None = None
    metadata: dict[str, Any] | None = None
    context_profile: ModelContextProfile | None = None

    def __post_init__(self) -> None:
        if self.context_profile is not None:
            self.context_profile.assert_deployment_identity(
                deployment_id=self.deployment_id,
                provider=self.provider,
                model=self.model,
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "provider": self.provider,
            "model": self.model,
            "capabilities": self.capabilities.to_dict(),
            "pricing": (
                {
                    "input_usd_per_1m_tokens": self.pricing.input_usd_per_1m_tokens,
                    "output_usd_per_1m_tokens": self.pricing.output_usd_per_1m_tokens,
                }
                if self.pricing is not None
                else None
            ),
            "enabled": self.enabled,
            "cooldown_until": _datetime_to_json(self.cooldown_until),
            "metadata": dict(self.metadata or {}),
            "context_profile": (
                self.context_profile.to_dict() if self.context_profile is not None else None
            ),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any], client: LLMClient) -> ModelDeployment:
        capabilities_payload = payload.get("capabilities") or {}
        pricing_payload = payload.get("pricing") or None
        return cls(
            deployment_id=str(payload.get("deployment_id") or ""),
            provider=str(payload.get("provider") or ""),
            model=str(payload.get("model") or ""),
            client=client,
            capabilities=ModelCapabilities(**capabilities_payload),
            pricing=(
                ModelPricing(
                    input_usd_per_1m_tokens=pricing_payload.get("input_usd_per_1m_tokens"),
                    output_usd_per_1m_tokens=pricing_payload.get("output_usd_per_1m_tokens"),
                )
                if isinstance(pricing_payload, dict)
                else None
            ),
            enabled=bool(payload.get("enabled", True)),
            metadata=dict(payload.get("metadata") or {}),
            context_profile=(
                ModelContextProfile(**payload["context_profile"])
                if isinstance(payload.get("context_profile"), dict)
                else None
            ),
        )


def _datetime_to_json(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat().replace("+00:00", "Z")
