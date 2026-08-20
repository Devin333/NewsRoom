from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Literal, cast

from framework.llm.structured_output.contracts import (
    LLMStructuredOutputError,
    StructuredOutputContract,
    StructuredOutputDiagnostic,
)
from framework.llm.structured_output.release import (
    ProviderStructuredOutputRelease,
)
from framework.shared.graph_identity import GraphExecutionIdentity


ProviderStructuredOutputMode = Literal[
    "native_strict", "constrained", "json_object", "none"
]
ProviderSchemaProjectionMode = Literal[
    "native_strict", "constrained", "json_object_local_gate"
]

_CAPABILITY_MODES = frozenset(
    {"native_strict", "constrained", "json_object", "none"}
)
_NATIVE_MODES = frozenset({"native_strict", "constrained"})
_ANNOTATION_KEYWORDS = frozenset(
    {
        "$comment",
        "$id",
        "$schema",
        "contentEncoding",
        "contentMediaType",
        "default",
        "deprecated",
        "description",
        "examples",
        "format",
        "readOnly",
        "title",
        "writeOnly",
    }
)
_SCHEMA_VALUE_KEYWORDS = frozenset(
    {
        "additionalProperties",
        "contains",
        "contentSchema",
        "else",
        "if",
        "items",
        "not",
        "propertyNames",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
    }
)
_SCHEMA_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})
_SCHEMA_MAP_KEYWORDS = frozenset(
    {
        "$defs",
        "definitions",
        "dependentSchemas",
        "patternProperties",
        "properties",
    }
)


@dataclass(frozen=True)
class ProviderStructuredOutputPolicy:
    require_native_enforcement: bool = False
    allow_json_object_local_gate: bool = False
    graph_scope: str = "default"

    def __post_init__(self) -> None:
        if not isinstance(self.require_native_enforcement, bool):
            raise ValueError("require_native_enforcement must be a boolean")
        if not isinstance(self.allow_json_object_local_gate, bool):
            raise ValueError("allow_json_object_local_gate must be a boolean")
        if self.require_native_enforcement and self.allow_json_object_local_gate:
            raise ValueError(
                "native enforcement cannot also allow JSON-object local-gate fallback"
            )
        scope = _required_text(self.graph_scope, field_name="graph_scope")
        object.__setattr__(self, "graph_scope", scope)

    def to_dict(self) -> dict[str, Any]:
        return {
            "require_native_enforcement": self.require_native_enforcement,
            "allow_json_object_local_gate": self.allow_json_object_local_gate,
            "graph_scope": self.graph_scope,
        }

    def for_execution_identity(
        self,
        identity: GraphExecutionIdentity,
    ) -> ProviderStructuredOutputPolicy:
        """Bind release authorization to an admitted Graph definition node."""
        if not isinstance(identity, GraphExecutionIdentity):
            raise TypeError("identity must be GraphExecutionIdentity")
        graph_scope = structured_output_graph_scope(identity)
        if self.graph_scope == graph_scope:
            return self
        return ProviderStructuredOutputPolicy(
            require_native_enforcement=self.require_native_enforcement,
            allow_json_object_local_gate=self.allow_json_object_local_gate,
            graph_scope=graph_scope,
        )

    @classmethod
    def from_any(cls, value: Any) -> ProviderStructuredOutputPolicy:
        if isinstance(value, cls):
            return value
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise TypeError("structured_output_policy must be an object")
        unknown = sorted(
            set(value)
            - {
                "require_native_enforcement",
                "allow_json_object_local_gate",
                "graph_scope",
            }
        )
        if unknown:
            raise ValueError(
                "structured_output_policy contains unsupported fields: "
                + ", ".join(unknown)
            )
        return cls(
            require_native_enforcement=value.get(
                "require_native_enforcement", False
            ),
            allow_json_object_local_gate=value.get(
                "allow_json_object_local_gate", False
            ),
            graph_scope=value.get("graph_scope", "default"),
        )


@dataclass(frozen=True)
class ProviderStructuredOutputCapability:
    provider: str
    deployment: str
    mode: ProviderStructuredOutputMode
    supported_dialect: str | None = None
    supported_keywords: frozenset[str] = field(default_factory=frozenset)
    supports_local_refs: bool = False
    supports_json_object_fallback: bool = False
    max_schema_bytes: int | None = None
    max_schema_depth: int | None = None
    supports_stream_terminal_validation: bool = False
    revision: str = ""
    release: ProviderStructuredOutputRelease | None = None

    def __post_init__(self) -> None:
        provider = _required_text(self.provider, field_name="provider")
        deployment = _required_text(self.deployment, field_name="deployment")
        revision = _required_text(self.revision, field_name="revision")
        if self.mode not in _CAPABILITY_MODES:
            raise ValueError("unsupported provider structured-output capability mode")
        keywords = frozenset(
            _required_text(keyword, field_name="supported keyword")
            for keyword in self.supported_keywords
        )
        for field_name in (
            "supports_local_refs",
            "supports_json_object_fallback",
            "supports_stream_terminal_validation",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a boolean")
        for field_name in ("max_schema_bytes", "max_schema_depth"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ValueError(f"{field_name} must be a positive integer")
        if self.mode in _NATIVE_MODES and not _optional_text(
            self.supported_dialect
        ):
            raise ValueError("native capability requires supported_dialect")
        if self.release is not None:
            if not isinstance(self.release, ProviderStructuredOutputRelease):
                raise ValueError(
                    "release must be ProviderStructuredOutputRelease"
                )
            if (
                self.release.provider != provider
                or self.release.deployment != deployment
                or self.release.capability_revision != revision
            ):
                raise ValueError(
                    "structured-output release identity does not match capability"
                )
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "deployment", deployment)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "supported_keywords", keywords)
        object.__setattr__(
            self,
            "supported_dialect",
            _optional_text(self.supported_dialect),
        )

    @property
    def supports_json_object(self) -> bool:
        return self.mode == "json_object" or self.supports_json_object_fallback

    @property
    def release_state(self) -> str:
        return self.release.rollout_state if self.release is not None else "disabled"

    def assert_identity(self, *, provider: str, deployment: str) -> None:
        if self.provider != provider or self.deployment != deployment:
            raise ValueError(
                "structured-output capability identity does not match deployment"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "deployment": self.deployment,
            "mode": self.mode,
            "supported_dialect": self.supported_dialect,
            "supported_keywords": sorted(self.supported_keywords),
            "supports_local_refs": self.supports_local_refs,
            "supports_json_object_fallback": self.supports_json_object_fallback,
            "max_schema_bytes": self.max_schema_bytes,
            "max_schema_depth": self.max_schema_depth,
            "supports_stream_terminal_validation": (
                self.supports_stream_terminal_validation
            ),
            "revision": self.revision,
            "release": self.release.to_dict() if self.release is not None else None,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ProviderStructuredOutputCapability:
        value = dict(payload)
        raw_release = value.get("release")
        if isinstance(raw_release, dict):
            value["release"] = ProviderStructuredOutputRelease.from_dict(raw_release)
        if isinstance(value.get("supported_keywords"), list):
            value["supported_keywords"] = frozenset(value["supported_keywords"])
        return cls(**value)


@dataclass(frozen=True)
class ProviderSchemaProjection:
    contract_digest: str
    provider: str
    deployment: str
    provider_capability_revision: str
    mode: ProviderSchemaProjectionMode
    provider_schema: dict[str, Any] | None
    enforced_keywords: frozenset[str]
    omitted_keywords: frozenset[str]
    projection_digest: str
    graph_scope: str = "default"
    provider_release_id: str | None = None
    provider_release_digest: str | None = None
    provider_rollout_state: str = "disabled"
    provider_rollout_revision: str | None = None
    evaluation_report_digest: str | None = None
    shadow_candidate_mode: str | None = None

    def __post_init__(self) -> None:
        if not self.contract_digest.startswith("sha256:"):
            raise ValueError("contract_digest must be a sha256 digest")
        if self.mode not in {
            "native_strict",
            "constrained",
            "json_object_local_gate",
        }:
            raise ValueError("unsupported provider schema projection mode")
        if not self.projection_digest.startswith("sha256:"):
            raise ValueError("projection_digest must be a sha256 digest")
        object.__setattr__(
            self,
            "graph_scope",
            _required_text(self.graph_scope, field_name="graph_scope"),
        )
        object.__setattr__(self, "provider_schema", deepcopy(self.provider_schema))
        object.__setattr__(
            self, "enforced_keywords", frozenset(self.enforced_keywords)
        )
        object.__setattr__(
            self, "omitted_keywords", frozenset(self.omitted_keywords)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_digest": self.contract_digest,
            "provider": self.provider,
            "deployment": self.deployment,
            "provider_capability_revision": self.provider_capability_revision,
            "mode": self.mode,
            "enforced_keywords": sorted(self.enforced_keywords),
            "omitted_keywords": sorted(self.omitted_keywords),
            "projection_digest": self.projection_digest,
            "graph_scope": self.graph_scope,
            "provider_release_id": self.provider_release_id,
            "provider_release_digest": self.provider_release_digest,
            "provider_rollout_state": self.provider_rollout_state,
            "provider_rollout_revision": self.provider_rollout_revision,
            "evaluation_report_digest": self.evaluation_report_digest,
            "shadow_candidate_mode": self.shadow_candidate_mode,
        }


class LLMStructuredOutputProjectionError(LLMStructuredOutputError):
    """Raised when a deployment cannot honestly project a local contract."""


def project_structured_output_contract(
    contract: StructuredOutputContract,
    capability: ProviderStructuredOutputCapability,
    *,
    policy: ProviderStructuredOutputPolicy | None = None,
    streaming: bool = False,
) -> ProviderSchemaProjection:
    resolved_policy = policy or ProviderStructuredOutputPolicy()
    used_keywords = structured_output_enforcement_keywords(
        contract.canonical_schema
    )
    native_issues = _native_projection_issues(
        contract,
        capability,
        used_keywords=used_keywords,
        streaming=streaming,
        graph_scope=resolved_policy.graph_scope,
    )
    if not native_issues:
        return _build_projection(
            contract,
            capability,
            mode=cast(ProviderSchemaProjectionMode, capability.mode),
            provider_schema=contract.canonical_schema,
            enforced_keywords=used_keywords,
            omitted_keywords=frozenset(),
            graph_scope=resolved_policy.graph_scope,
        )

    if (
        resolved_policy.allow_json_object_local_gate
        and not resolved_policy.require_native_enforcement
        and capability.supports_json_object
        and (not streaming or capability.supports_stream_terminal_validation)
    ):
        return _build_projection(
            contract,
            capability,
            mode="json_object_local_gate",
            provider_schema=None,
            enforced_keywords=frozenset(),
            omitted_keywords=used_keywords,
            graph_scope=resolved_policy.graph_scope,
            shadow_candidate_mode=(
                capability.mode
                if capability.release_state == "shadow"
                and capability.mode in _NATIVE_MODES
                else None
            ),
        )

    diagnostics = tuple(
        StructuredOutputDiagnostic(
            code=(
                "provider_release_ineligible"
                if reason.startswith("provider_release_")
                else "provider_schema_ineligible"
            ),
            message=message,
            validator=reason,
            contract_digest=contract.schema_digest,
        )
        for reason, message in native_issues
    )
    raise LLMStructuredOutputProjectionError(
        "provider deployment cannot enforce the structured-output contract",
        diagnostics=diagnostics,
    )


def structured_output_enforcement_keywords(
    schema: dict[str, Any],
) -> frozenset[str]:
    keywords: set[str] = set()

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        for keyword in node:
            if keyword not in _ANNOTATION_KEYWORDS:
                keywords.add(keyword)
        for keyword in _SCHEMA_VALUE_KEYWORDS:
            if keyword in node:
                visit(node[keyword])
        for keyword in _SCHEMA_ARRAY_KEYWORDS:
            values = node.get(keyword)
            if isinstance(values, list):
                for value in values:
                    visit(value)
        for keyword in _SCHEMA_MAP_KEYWORDS:
            values = node.get(keyword)
            if isinstance(values, dict):
                for value in values.values():
                    visit(value)

    visit(schema)
    return frozenset(keywords)


def _native_projection_issues(
    contract: StructuredOutputContract,
    capability: ProviderStructuredOutputCapability,
    *,
    used_keywords: frozenset[str],
    streaming: bool,
    graph_scope: str,
) -> list[tuple[str, str]]:
    issues: list[tuple[str, str]] = []
    if capability.mode not in _NATIVE_MODES:
        issues.append(
            (
                "provider_native_mode_unavailable",
                "provider capability does not declare native schema enforcement",
            )
        )
    else:
        release = capability.release
        if release is None:
            issues.append(
                (
                    "provider_release_missing",
                    "provider native enforcement has no approved release record",
                )
            )
        else:
            for reason in release.authorization_issues(
                provider=capability.provider,
                deployment=capability.deployment,
                capability_revision=capability.revision,
                mode=capability.mode,
                graph_scope=graph_scope,
            ):
                issues.append(
                    (
                        reason,
                        "provider native enforcement release is not eligible",
                    )
                )
    if capability.supported_dialect != contract.dialect:
        issues.append(
            (
                "provider_dialect_unsupported",
                "provider capability does not cover the local contract dialect",
            )
        )
    if used_keywords - capability.supported_keywords:
        issues.append(
            (
                "provider_keywords_unsupported",
                "provider capability omits required schema keywords",
            )
        )
    if "$ref" in used_keywords and not capability.supports_local_refs:
        issues.append(
            (
                "provider_local_refs_unsupported",
                "provider capability does not support local schema references",
            )
        )
    schema_bytes = len(_canonical_json_bytes(contract.canonical_schema))
    if (
        capability.max_schema_bytes is not None
        and schema_bytes > capability.max_schema_bytes
    ):
        issues.append(
            (
                "provider_schema_bytes_exceeded",
                "provider schema byte limit is lower than the contract",
            )
        )
    schema_depth = _schema_depth(contract.canonical_schema)
    if (
        capability.max_schema_depth is not None
        and schema_depth > capability.max_schema_depth
    ):
        issues.append(
            (
                "provider_schema_depth_exceeded",
                "provider schema depth limit is lower than the contract",
            )
        )
    if streaming and not capability.supports_stream_terminal_validation:
        issues.append(
            (
                "provider_stream_terminal_validation_unsupported",
                (
                    "provider capability does not support safe structured "
                    "streaming terminal validation"
                ),
            )
        )
    return issues


def _build_projection(
    contract: StructuredOutputContract,
    capability: ProviderStructuredOutputCapability,
    *,
    mode: ProviderSchemaProjectionMode,
    provider_schema: dict[str, Any] | None,
    enforced_keywords: frozenset[str],
    omitted_keywords: frozenset[str],
    graph_scope: str,
    shadow_candidate_mode: str | None = None,
) -> ProviderSchemaProjection:
    release = capability.release
    digest_payload = {
        "contract_digest": contract.schema_digest,
        "provider": capability.provider,
        "deployment": capability.deployment,
        "provider_capability_revision": capability.revision,
        "mode": mode,
        "provider_schema": provider_schema,
        "enforced_keywords": sorted(enforced_keywords),
        "omitted_keywords": sorted(omitted_keywords),
        "graph_scope": graph_scope,
        "provider_release_id": release.release_id if release is not None else None,
        "provider_release_digest": release.digest if release is not None else None,
        "provider_rollout_state": capability.release_state,
        "provider_rollout_revision": (
            release.rollout_revision if release is not None else None
        ),
        "evaluation_report_digest": (
            release.evaluation_report_digest if release is not None else None
        ),
        "shadow_candidate_mode": shadow_candidate_mode,
    }
    projection_digest = (
        "sha256:" + sha256(_canonical_json_bytes(digest_payload)).hexdigest()
    )
    return ProviderSchemaProjection(
        contract_digest=contract.schema_digest,
        provider=capability.provider,
        deployment=capability.deployment,
        provider_capability_revision=capability.revision,
        mode=mode,
        provider_schema=provider_schema,
        enforced_keywords=enforced_keywords,
        omitted_keywords=omitted_keywords,
        projection_digest=projection_digest,
        graph_scope=graph_scope,
        provider_release_id=(release.release_id if release is not None else None),
        provider_release_digest=(release.digest if release is not None else None),
        provider_rollout_state=capability.release_state,
        provider_rollout_revision=(
            release.rollout_revision if release is not None else None
        ),
        evaluation_report_digest=(
            release.evaluation_report_digest if release is not None else None
        ),
        shadow_candidate_mode=shadow_candidate_mode,
    )


def structured_output_graph_scope(identity: GraphExecutionIdentity) -> str:
    """Return the release scope for one immutable Graph definition node.

    Runtime-only values such as run, node instance, activity, and attempt do not
    belong in a provider release allowlist. The exact graph checksum and node
    definition still ensure the scope cannot drift or be selected by a caller.
    """
    if not isinstance(identity, GraphExecutionIdentity):
        raise TypeError("identity must be GraphExecutionIdentity")
    return f"{identity.graph_ref}:{identity.graph_checksum}:{identity.node_id}"


def _schema_depth(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + max((_schema_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_schema_depth(item) for item in value), default=0)
    return 1


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _required_text(value: Any, *, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} must be a non-empty string")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
