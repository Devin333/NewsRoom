from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from framework.llm.structured_output.contracts import StructuredOutputContract
from framework.llm.structured_output.projection import ProviderSchemaProjection

if TYPE_CHECKING:
    from framework.llm.models.request import LLMRequest
    from framework.llm.models.response import LLMResponse


STRUCTURED_OUTPUT_VALIDATION_METADATA_KEY = "structured_output_validation"
_IDENTITY_FIELDS = (
    "schema_name",
    "schema_digest",
    "schema_revision",
    "schema_dialect",
    "typed_adapter_revision",
    "projection_digest",
    "projection_mode",
    "provider_capability_revision",
)


class ManagedStructuredOutputError(ValueError):
    """Raised when a structured response lacks the trusted validation envelope."""


@dataclass(frozen=True)
class StructuredOutputCacheIdentity:
    schema_name: str
    schema_digest: str
    schema_revision: str
    schema_dialect: str
    typed_adapter_revision: str | None
    projection_digest: str
    projection_mode: str
    provider_capability_revision: str

    @classmethod
    def from_execution(
        cls,
        *,
        contract: StructuredOutputContract,
        projection: ProviderSchemaProjection,
    ) -> "StructuredOutputCacheIdentity":
        if projection.contract_digest != contract.schema_digest:
            raise ManagedStructuredOutputError(
                "structured-output projection does not match contract"
            )
        return cls(
            schema_name=contract.schema_name,
            schema_digest=contract.schema_digest,
            schema_revision=contract.schema_revision,
            schema_dialect=contract.dialect,
            typed_adapter_revision=contract.typed_adapter_revision,
            projection_digest=projection.projection_digest,
            projection_mode=projection.mode,
            provider_capability_revision=projection.provider_capability_revision,
        )

    @classmethod
    def from_request(
        cls,
        request: LLMRequest,
    ) -> "StructuredOutputCacheIdentity | None":
        if request.output_schema is None:
            return None
        contract = request.structured_output_contract()
        projection = request.provider_schema_projection()
        if contract is None or projection is None:
            return None
        return cls.from_execution(contract=contract, projection=projection)

    @classmethod
    def from_metadata(
        cls,
        metadata: Mapping[str, Any],
    ) -> "StructuredOutputCacheIdentity":
        values: dict[str, Any] = {}
        for field in _IDENTITY_FIELDS:
            value = metadata.get(field)
            if field == "typed_adapter_revision":
                if value is not None and (not isinstance(value, str) or not value):
                    raise ManagedStructuredOutputError(
                        "typed_adapter_revision must be text or null"
                    )
            elif not isinstance(value, str) or not value:
                raise ManagedStructuredOutputError(
                    f"structured-output validation envelope is missing {field}"
                )
            values[field] = value
        return cls(**values)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "schema_name": self.schema_name,
            "schema_digest": self.schema_digest,
            "schema_revision": self.schema_revision,
            "schema_dialect": self.schema_dialect,
            "typed_adapter_revision": self.typed_adapter_revision,
            "projection_digest": self.projection_digest,
            "projection_mode": self.projection_mode,
            "provider_capability_revision": self.provider_capability_revision,
        }


def structured_output_response_fingerprint(value: Mapping[str, Any]) -> str:
    if not isinstance(value, Mapping):
        raise ManagedStructuredOutputError("structured output must be an object")
    try:
        payload = json.dumps(
            dict(value),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManagedStructuredOutputError(
            "structured output cannot be fingerprinted"
        ) from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def structured_output_text_fingerprint(value: str) -> str:
    if not isinstance(value, str):
        raise ManagedStructuredOutputError("structured output text must be text")
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def managed_validation_metadata(
    *,
    identity: StructuredOutputCacheIdentity,
    value: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "validated": True,
        **identity.to_dict(),
        "response_fingerprint": structured_output_response_fingerprint(value),
    }


def require_managed_structured_output(
    *,
    request: LLMRequest,
    response: LLMResponse,
) -> StructuredOutputCacheIdentity | None:
    expected = StructuredOutputCacheIdentity.from_request(request)
    if expected is None:
        if request.output_schema is None:
            return None
        raise ManagedStructuredOutputError(
            "structured-output request has no managed execution identity"
        )
    actual = require_managed_structured_output_for_contract(
        response=response,
        contract=request.structured_output_contract(),
    )
    if actual != expected:
        raise ManagedStructuredOutputError(
            "structured response validation identity does not match request"
        )
    return actual


def require_managed_structured_output_for_contract(
    *,
    response: LLMResponse,
    contract: StructuredOutputContract | None,
) -> StructuredOutputCacheIdentity:
    if contract is None:
        raise ManagedStructuredOutputError(
            "structured-output contract is required"
        )
    if not isinstance(response.structured_output, dict):
        raise ManagedStructuredOutputError("structured response is missing terminal object")
    envelope = response.metadata.get(STRUCTURED_OUTPUT_VALIDATION_METADATA_KEY)
    if not isinstance(envelope, Mapping) or envelope.get("validated") is not True:
        raise ManagedStructuredOutputError(
            "structured response is missing managed validation envelope"
        )
    actual = StructuredOutputCacheIdentity.from_metadata(envelope)
    if (
        actual.schema_name != contract.schema_name
        or actual.schema_digest != contract.schema_digest
        or actual.schema_revision != contract.schema_revision
        or actual.schema_dialect != contract.dialect
        or actual.typed_adapter_revision != contract.typed_adapter_revision
    ):
        raise ManagedStructuredOutputError(
            "structured response validation identity does not match contract"
        )
    fingerprint = envelope.get("response_fingerprint")
    if not isinstance(fingerprint, str) or fingerprint != structured_output_response_fingerprint(
        response.structured_output
    ):
        raise ManagedStructuredOutputError(
            "structured response fingerprint does not match terminal object"
        )
    return actual


__all__ = [
    "ManagedStructuredOutputError",
    "STRUCTURED_OUTPUT_VALIDATION_METADATA_KEY",
    "StructuredOutputCacheIdentity",
    "managed_validation_metadata",
    "require_managed_structured_output",
    "require_managed_structured_output_for_contract",
    "structured_output_response_fingerprint",
    "structured_output_text_fingerprint",
]
