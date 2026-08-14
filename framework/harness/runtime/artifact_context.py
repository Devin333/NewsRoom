from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, Self, runtime_checkable

from framework.events.canonical import canonical_json_bytes, checksum_for
from framework.harness.artifacts.catalog import (
    ArtifactCatalogClaim,
    ArtifactCatalogEntry,
)
from framework.harness.artifacts.ports import (
    ArtifactCatalogPort,
    GraphResultArtifactReadPort,
)
from framework.harness.control_plane.graph_result_lineage import (
    HarnessGraphArtifactRefProjection,
    HarnessGraphResultLineage,
)
from framework.harness.runtime.materializer import RESULT_PAYLOAD_SCHEMA
from framework.harness.runtime.result_canonical import (
    boolean,
    checksum,
    enum_value,
    estimated_tokens,
    exact_keys,
    exact_reference,
    identifier,
    media_type,
    non_negative_int,
    reference,
    serialize_candidate,
    sha256_checksum,
)
from framework.harness.runtime.result_errors import (
    GraphArtifactResultError,
    GraphArtifactResultErrorCode,
    result_error,
)
from framework.harness.runtime.result_models import (
    ArtifactClass,
    BoundedSummary,
    ContextAssemblyRequest,
    ContextLoadMode,
    ContextPolicy,
    ContextPurpose,
    ResultSensitivity,
)
from framework.harness.runtime.result_policy import GraphArtifactPersistenceConfig
from framework.harness.workflow.canonical import freeze_json, thaw_json


APPROVED_ARTIFACT_LOAD_PLAN_SCHEMA = "newsroom.approved-artifact-load-plan@1"
ARTIFACT_CONTEXT_LOAD_RESULT_SCHEMA = "newsroom.artifact-context-load-result@1"
ARTIFACT_CONTEXT_PROJECTION_SCHEMA = "newsroom.artifact-context-projection@1"


@runtime_checkable
class ArtifactContextProviderPort(Protocol):
    def load_artifact_context(
        self,
        request: Mapping[str, Any],
    ) -> "ArtifactContextLoadResult": ...


@dataclass(frozen=True, slots=True)
class ApprovedArtifactLoadItem:
    ref: str
    lineage_checksum: str
    catalog_entry_id: str
    artifact_id: str
    artifact_type: str
    physical_artifact_type: str
    content_checksum: str
    source_byte_size: int
    source_token_estimate: int
    media_type: str
    artifact_class: ArtifactClass
    sensitivity: ResultSensitivity
    context_policy: ContextPolicy
    producer_revision: str
    tenant_id: str
    run_id: str
    graph_id: str
    node_id: str
    attempt_id: str
    physical_run_id: str
    physical_graph_id: str
    physical_node_id: str
    physical_attempt_id: str
    summary: BoundedSummary
    admitted_bytes: int
    admitted_tokens: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", reference(self.ref, "load_item.ref"))
        object.__setattr__(
            self,
            "lineage_checksum",
            checksum(self.lineage_checksum, "load_item.lineage_checksum"),
        )
        object.__setattr__(
            self,
            "catalog_entry_id",
            reference(self.catalog_entry_id, "load_item.catalog_entry_id"),
        )
        for field_name in (
            "artifact_id",
            "artifact_type",
            "physical_artifact_type",
            "tenant_id",
            "run_id",
            "graph_id",
            "node_id",
            "attempt_id",
            "physical_run_id",
            "physical_graph_id",
            "physical_node_id",
            "physical_attempt_id",
        ):
            object.__setattr__(
                self,
                field_name,
                identifier(getattr(self, field_name), f"load_item.{field_name}"),
            )
        object.__setattr__(
            self,
            "content_checksum",
            checksum(self.content_checksum, "load_item.content_checksum"),
        )
        for field_name in (
            "source_byte_size",
            "source_token_estimate",
            "admitted_bytes",
            "admitted_tokens",
        ):
            object.__setattr__(
                self,
                field_name,
                non_negative_int(getattr(self, field_name), f"load_item.{field_name}"),
            )
        object.__setattr__(
            self,
            "media_type",
            media_type(self.media_type, "load_item.media_type"),
        )
        object.__setattr__(
            self,
            "artifact_class",
            enum_value(ArtifactClass, self.artifact_class, "load_item.artifact_class"),
        )
        object.__setattr__(
            self,
            "sensitivity",
            enum_value(ResultSensitivity, self.sensitivity, "load_item.sensitivity"),
        )
        object.__setattr__(
            self,
            "context_policy",
            enum_value(ContextPolicy, self.context_policy, "load_item.context_policy"),
        )
        object.__setattr__(
            self,
            "producer_revision",
            exact_reference(self.producer_revision, "load_item.producer_revision"),
        )
        if not isinstance(self.summary, BoundedSummary):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="load_item.summary",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "lineage_checksum": self.lineage_checksum,
            "catalog_entry_id": self.catalog_entry_id,
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "physical_artifact_type": self.physical_artifact_type,
            "content_checksum": self.content_checksum,
            "source_byte_size": self.source_byte_size,
            "source_token_estimate": self.source_token_estimate,
            "media_type": self.media_type,
            "artifact_class": self.artifact_class.value,
            "sensitivity": self.sensitivity.value,
            "context_policy": self.context_policy.value,
            "producer_revision": self.producer_revision,
            "tenant_id": self.tenant_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "attempt_id": self.attempt_id,
            "physical_run_id": self.physical_run_id,
            "physical_graph_id": self.physical_graph_id,
            "physical_node_id": self.physical_node_id,
            "physical_attempt_id": self.physical_attempt_id,
            "summary": self.summary.to_dict(),
            "admitted_bytes": self.admitted_bytes,
            "admitted_tokens": self.admitted_tokens,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "ref",
                    "lineage_checksum",
                    "catalog_entry_id",
                    "artifact_id",
                    "artifact_type",
                    "physical_artifact_type",
                    "content_checksum",
                    "source_byte_size",
                    "source_token_estimate",
                    "media_type",
                    "artifact_class",
                    "sensitivity",
                    "context_policy",
                    "producer_revision",
                    "tenant_id",
                    "run_id",
                    "graph_id",
                    "node_id",
                    "attempt_id",
                    "physical_run_id",
                    "physical_graph_id",
                    "physical_node_id",
                    "physical_attempt_id",
                    "summary",
                    "admitted_bytes",
                    "admitted_tokens",
                }
            ),
            model=cls.__name__,
        )
        payload["summary"] = BoundedSummary.from_dict(payload["summary"])
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ApprovedArtifactLoadPlan:
    request: ContextAssemblyRequest
    policy_version: str
    items: tuple[ApprovedArtifactLoadItem, ...]
    planned_loaded_bytes: int
    planned_loaded_tokens: int
    plan_checksum: str
    schema_version: str = APPROVED_ARTIFACT_LOAD_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if not isinstance(self.request, ContextAssemblyRequest):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="load_plan.request",
            )
        policy_version = exact_reference(
            self.policy_version,
            "load_plan.policy_version",
        )
        items = tuple(self.items)
        if not all(isinstance(item, ApprovedArtifactLoadItem) for item in items):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="load_plan.items",
            )
        if items != tuple(sorted(items, key=lambda item: item.ref)):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="load_plan.items",
            )
        if (
            len({item.ref for item in items}) != len(items)
            or len({item.content_checksum for item in items}) != len(items)
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="load_plan.items",
            )
        for item in items:
            if (
                item.ref not in self.request.artifact_refs
                or (item.tenant_id, item.run_id, item.graph_id)
                != (
                    self.request.tenant_id,
                    self.request.run_id,
                    self.request.graph_id,
                )
                or item.artifact_class not in self.request.allowed_artifact_classes
                or item.sensitivity not in self.request.allowed_sensitivities
            ):
                raise result_error(
                    GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                    field="load_plan.items",
                )
        loaded_bytes = non_negative_int(
            self.planned_loaded_bytes,
            "load_plan.planned_loaded_bytes",
        )
        loaded_tokens = non_negative_int(
            self.planned_loaded_tokens,
            "load_plan.planned_loaded_tokens",
        )
        if (
            loaded_bytes != sum(item.admitted_bytes for item in items)
            or loaded_tokens != sum(item.admitted_tokens for item in items)
            or loaded_bytes > self.request.max_bytes
            or loaded_tokens > self.request.max_tokens
        ):
            raise result_error(
                GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED,
                field="load_plan.budget",
            )
        if self.schema_version != APPROVED_ARTIFACT_LOAD_PLAN_SCHEMA:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="load_plan.schema_version",
            )
        actual = checksum(self.plan_checksum, "load_plan.plan_checksum")
        expected = checksum_for(self.checksum_projection())
        if actual != expected:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="load_plan.plan_checksum",
            )
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "planned_loaded_bytes", loaded_bytes)
        object.__setattr__(self, "planned_loaded_tokens", loaded_tokens)
        object.__setattr__(self, "plan_checksum", actual)

    @classmethod
    def create(
        cls,
        *,
        request: ContextAssemblyRequest,
        policy_version: str,
        items: Sequence[ApprovedArtifactLoadItem],
    ) -> Self:
        ordered = tuple(sorted(items, key=lambda item: item.ref))
        payload = {
            "schema_version": APPROVED_ARTIFACT_LOAD_PLAN_SCHEMA,
            "request": request.to_dict(),
            "policy_version": policy_version,
            "items": [item.to_dict() for item in ordered],
            "planned_loaded_bytes": sum(item.admitted_bytes for item in ordered),
            "planned_loaded_tokens": sum(item.admitted_tokens for item in ordered),
        }
        return cls(
            request=request,
            policy_version=policy_version,
            items=ordered,
            planned_loaded_bytes=payload["planned_loaded_bytes"],
            planned_loaded_tokens=payload["planned_loaded_tokens"],
            plan_checksum=checksum_for(payload),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request": self.request.to_dict(),
            "policy_version": self.policy_version,
            "items": [item.to_dict() for item in self.items],
            "planned_loaded_bytes": self.planned_loaded_bytes,
            "planned_loaded_tokens": self.planned_loaded_tokens,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.checksum_projection(), "plan_checksum": self.plan_checksum}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "schema_version",
                    "request",
                    "policy_version",
                    "items",
                    "planned_loaded_bytes",
                    "planned_loaded_tokens",
                    "plan_checksum",
                }
            ),
            model=cls.__name__,
        )
        payload["request"] = ContextAssemblyRequest.from_dict(payload["request"])
        payload["items"] = tuple(
            ApprovedArtifactLoadItem.from_dict(item)
            for item in _mapping_sequence(payload["items"], "load_plan.items")
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class ArtifactContextItem:
    ref: str
    content_checksum: str
    source_byte_size: int
    source_token_estimate: int
    media_type: str
    artifact_class: ArtifactClass
    sensitivity: ResultSensitivity
    load_mode: ContextLoadMode
    content: Any
    encoding: str
    complete: bool
    loaded_bytes: int
    loaded_tokens: int
    loaded_checksum: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref", reference(self.ref, "context_item.ref"))
        object.__setattr__(
            self,
            "content_checksum",
            checksum(self.content_checksum, "context_item.content_checksum"),
        )
        object.__setattr__(
            self,
            "source_byte_size",
            non_negative_int(self.source_byte_size, "context_item.source_byte_size"),
        )
        object.__setattr__(
            self,
            "source_token_estimate",
            non_negative_int(
                self.source_token_estimate,
                "context_item.source_token_estimate",
            ),
        )
        object.__setattr__(
            self,
            "media_type",
            media_type(self.media_type, "context_item.media_type"),
        )
        object.__setattr__(
            self,
            "artifact_class",
            enum_value(ArtifactClass, self.artifact_class, "context_item.artifact_class"),
        )
        object.__setattr__(
            self,
            "sensitivity",
            enum_value(ResultSensitivity, self.sensitivity, "context_item.sensitivity"),
        )
        mode = enum_value(ContextLoadMode, self.load_mode, "context_item.load_mode")
        object.__setattr__(self, "load_mode", mode)
        frozen = freeze_json(self.content, "context_item.content")
        object.__setattr__(self, "content", frozen)
        if not isinstance(self.encoding, str) or self.encoding not in {
            "summary",
            "json",
            "text",
            "base64",
            "utf8_prefix",
            "base64_prefix",
        }:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context_item.encoding",
            )
        complete = boolean(self.complete, "context_item.complete")
        loaded_bytes = non_negative_int(
            self.loaded_bytes,
            "context_item.loaded_bytes",
        )
        loaded_tokens = non_negative_int(
            self.loaded_tokens,
            "context_item.loaded_tokens",
        )
        content_bytes = _context_content_bytes(frozen, self.encoding)
        if (
            loaded_bytes != len(content_bytes)
            or loaded_tokens != estimated_tokens(loaded_bytes)
            or checksum(self.loaded_checksum, "context_item.loaded_checksum")
            != sha256_checksum(content_bytes)
            or (mode is ContextLoadMode.SAMPLE and complete)
            or (mode is ContextLoadMode.FULL and not complete)
            or (
                mode is ContextLoadMode.FULL
                and (
                    loaded_bytes != self.source_byte_size
                    or self.loaded_checksum != self.content_checksum
                )
            )
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
                field="context_item.content",
            )
        object.__setattr__(self, "complete", complete)
        object.__setattr__(self, "loaded_bytes", loaded_bytes)
        object.__setattr__(self, "loaded_tokens", loaded_tokens)
        object.__setattr__(
            self,
            "loaded_checksum",
            sha256_checksum(content_bytes),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "content_checksum": self.content_checksum,
            "source_byte_size": self.source_byte_size,
            "source_token_estimate": self.source_token_estimate,
            "media_type": self.media_type,
            "artifact_class": self.artifact_class.value,
            "sensitivity": self.sensitivity.value,
            "load_mode": self.load_mode.value,
            "content": thaw_json(self.content),
            "encoding": self.encoding,
            "complete": self.complete,
            "loaded_bytes": self.loaded_bytes,
            "loaded_tokens": self.loaded_tokens,
            "loaded_checksum": self.loaded_checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        return cls(
            **exact_keys(
                value,
                required=frozenset(
                    {
                        "ref",
                        "content_checksum",
                        "source_byte_size",
                        "source_token_estimate",
                        "media_type",
                        "artifact_class",
                        "sensitivity",
                        "load_mode",
                        "content",
                        "encoding",
                        "complete",
                        "loaded_bytes",
                        "loaded_tokens",
                        "loaded_checksum",
                    }
                ),
                model=cls.__name__,
            )
        )


@dataclass(frozen=True, slots=True)
class ArtifactContextLoadResult:
    plan_checksum: str
    load_mode: ContextLoadMode
    purpose: ContextPurpose
    policy_version: str
    items: tuple[ArtifactContextItem, ...]
    total_loaded_bytes: int
    total_loaded_tokens: int
    result_checksum: str
    context_fingerprint: str
    schema_version: str = ARTIFACT_CONTEXT_LOAD_RESULT_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "plan_checksum",
            checksum(self.plan_checksum, "context_result.plan_checksum"),
        )
        object.__setattr__(
            self,
            "load_mode",
            enum_value(ContextLoadMode, self.load_mode, "context_result.load_mode"),
        )
        object.__setattr__(
            self,
            "purpose",
            enum_value(ContextPurpose, self.purpose, "context_result.purpose"),
        )
        object.__setattr__(
            self,
            "policy_version",
            exact_reference(self.policy_version, "context_result.policy_version"),
        )
        items = tuple(self.items)
        if (
            not all(isinstance(item, ArtifactContextItem) for item in items)
            or items != tuple(sorted(items, key=lambda item: item.ref))
            or len({item.content_checksum for item in items}) != len(items)
            or any(item.load_mode is not self.load_mode for item in items)
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context_result.items",
            )
        total_bytes = non_negative_int(
            self.total_loaded_bytes,
            "context_result.total_loaded_bytes",
        )
        total_tokens = non_negative_int(
            self.total_loaded_tokens,
            "context_result.total_loaded_tokens",
        )
        if (
            total_bytes != sum(item.loaded_bytes for item in items)
            or total_tokens != sum(item.loaded_tokens for item in items)
        ):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context_result.budget",
            )
        if self.schema_version != ARTIFACT_CONTEXT_LOAD_RESULT_SCHEMA:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context_result.schema_version",
            )
        actual_result = checksum(
            self.result_checksum,
            "context_result.result_checksum",
        )
        if actual_result != checksum_for(self.checksum_projection()):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="context_result.result_checksum",
            )
        actual_fingerprint = checksum(
            self.context_fingerprint,
            "context_result.context_fingerprint",
        )
        expected_fingerprint = checksum_for(
            {
                "plan_checksum": self.plan_checksum,
                "result_checksum": actual_result,
                "purpose": self.purpose.value,
                "policy_version": self.policy_version,
            }
        )
        if actual_fingerprint != expected_fingerprint:
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_IDENTITY_CONFLICT,
                field="context_result.context_fingerprint",
            )
        object.__setattr__(self, "items", items)
        object.__setattr__(self, "total_loaded_bytes", total_bytes)
        object.__setattr__(self, "total_loaded_tokens", total_tokens)
        object.__setattr__(self, "result_checksum", actual_result)
        object.__setattr__(self, "context_fingerprint", actual_fingerprint)

    @classmethod
    def create(
        cls,
        plan: ApprovedArtifactLoadPlan,
        *,
        items: Sequence[ArtifactContextItem],
    ) -> Self:
        ordered = tuple(sorted(items, key=lambda item: item.ref))
        payload = {
            "schema_version": ARTIFACT_CONTEXT_LOAD_RESULT_SCHEMA,
            "plan_checksum": plan.plan_checksum,
            "load_mode": plan.request.load_mode.value,
            "purpose": plan.request.purpose.value,
            "policy_version": plan.policy_version,
            "items": [item.to_dict() for item in ordered],
            "total_loaded_bytes": sum(item.loaded_bytes for item in ordered),
            "total_loaded_tokens": sum(item.loaded_tokens for item in ordered),
        }
        result_checksum = checksum_for(payload)
        return cls(
            plan_checksum=plan.plan_checksum,
            load_mode=plan.request.load_mode,
            purpose=plan.request.purpose,
            policy_version=plan.policy_version,
            items=ordered,
            total_loaded_bytes=payload["total_loaded_bytes"],
            total_loaded_tokens=payload["total_loaded_tokens"],
            result_checksum=result_checksum,
            context_fingerprint=checksum_for(
                {
                    "plan_checksum": plan.plan_checksum,
                    "result_checksum": result_checksum,
                    "purpose": plan.request.purpose.value,
                    "policy_version": plan.policy_version,
                }
            ),
        )

    def checksum_projection(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "plan_checksum": self.plan_checksum,
            "load_mode": self.load_mode.value,
            "purpose": self.purpose.value,
            "policy_version": self.policy_version,
            "items": [item.to_dict() for item in self.items],
            "total_loaded_bytes": self.total_loaded_bytes,
            "total_loaded_tokens": self.total_loaded_tokens,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.checksum_projection(),
            "result_checksum": self.result_checksum,
            "context_fingerprint": self.context_fingerprint,
        }

    def to_context_projection(self) -> dict[str, Any]:
        """Return the approved, compact payload that may enter worker context."""

        return {
            "schema_version": ARTIFACT_CONTEXT_PROJECTION_SCHEMA,
            "plan_checksum": self.plan_checksum,
            "result_checksum": self.result_checksum,
            "context_fingerprint": self.context_fingerprint,
            "load_mode": self.load_mode.value,
            "purpose": self.purpose.value,
            "policy_version": self.policy_version,
            "items": [
                {
                    "ref": item.ref,
                    "content_checksum": item.content_checksum,
                    "artifact_class": item.artifact_class.value,
                    "sensitivity": item.sensitivity.value,
                    "content": thaw_json(item.content),
                    "encoding": item.encoding,
                    "complete": item.complete,
                    "loaded_bytes": item.loaded_bytes,
                    "loaded_tokens": item.loaded_tokens,
                    "loaded_checksum": item.loaded_checksum,
                }
                for item in self.items
            ],
            "total_loaded_bytes": self.total_loaded_bytes,
            "total_loaded_tokens": self.total_loaded_tokens,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> Self:
        payload = exact_keys(
            value,
            required=frozenset(
                {
                    "schema_version",
                    "plan_checksum",
                    "load_mode",
                    "purpose",
                    "policy_version",
                    "items",
                    "total_loaded_bytes",
                    "total_loaded_tokens",
                    "result_checksum",
                    "context_fingerprint",
                }
            ),
            model=cls.__name__,
        )
        payload["items"] = tuple(
            ArtifactContextItem.from_dict(item)
            for item in _mapping_sequence(payload["items"], "context_result.items")
        )
        return cls(**payload)


class ArtifactContextLoadPlanner:
    def __init__(
        self,
        *,
        catalog: ArtifactCatalogPort,
        config: GraphArtifactPersistenceConfig,
    ) -> None:
        if not isinstance(catalog, ArtifactCatalogPort):
            raise TypeError("catalog must implement ArtifactCatalogPort")
        if not isinstance(config, GraphArtifactPersistenceConfig):
            raise TypeError("config must be GraphArtifactPersistenceConfig")
        self._catalog = catalog
        self._config = config

    def plan(
        self,
        request: ContextAssemblyRequest,
        *,
        accepted_lineages: Sequence[HarnessGraphResultLineage],
    ) -> ApprovedArtifactLoadPlan:
        if not isinstance(request, ContextAssemblyRequest):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context.request",
            )
        self._validate_request_budget(request)
        lineages = tuple(accepted_lineages)
        if not all(isinstance(item, HarnessGraphResultLineage) for item in lineages):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context.accepted_lineages",
            )
        projections: dict[
            str,
            list[
                tuple[
                    HarnessGraphResultLineage,
                    HarnessGraphArtifactRefProjection,
                ]
            ],
        ] = {}
        for lineage in lineages:
            self._config.ensure_readable_policy_version(lineage.policy_version)
            if (lineage.tenant_id, lineage.run_id, lineage.graph_id) != (
                request.tenant_id,
                request.run_id,
                request.graph_id,
            ):
                raise result_error(
                    GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                    field="context.accepted_lineages",
                )
            for projection in lineage.artifact_refs:
                projections.setdefault(projection.ref, []).append(
                    (lineage, projection)
                )

        items: list[ApprovedArtifactLoadItem] = []
        admitted_checksums: set[str] = set()
        for ref_value in request.artifact_refs:
            matches = projections.get(ref_value)
            if not matches:
                raise result_error(
                    GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                    field="context.artifact_refs",
                )
            verified_matches: list[
                tuple[
                    HarnessGraphResultLineage,
                    HarnessGraphArtifactRefProjection,
                    ArtifactCatalogClaim,
                    ArtifactCatalogEntry,
                ]
            ] = []
            for lineage, projection in sorted(
                matches,
                key=lambda item: (
                    item[0].lineage_checksum,
                    item[1].artifact_id,
                ),
            ):
                claim, entry = self._catalog_records(projection)
                self._validate_catalog_match(
                    lineage,
                    projection,
                    claim,
                    entry,
                    request,
                )
                verified_matches.append((lineage, projection, claim, entry))
            if len({item[3].entry_id for item in verified_matches}) != 1:
                raise result_error(
                    GraphArtifactResultErrorCode.ARTIFACT_CATALOG_CORRUPT,
                    field="context.lineage_ref",
                )
            lineage, projection, _, entry = verified_matches[0]
            if projection.content_checksum in admitted_checksums:
                continue
            admitted_checksums.add(projection.content_checksum)
            admitted_bytes, admitted_tokens = self._admitted_budget(
                lineage,
                request.load_mode,
            )
            items.append(
                ApprovedArtifactLoadItem(
                    ref=projection.ref,
                    lineage_checksum=lineage.lineage_checksum,
                    catalog_entry_id=entry.entry_id,
                    artifact_id=projection.artifact_id,
                    artifact_type=projection.artifact_type,
                    physical_artifact_type=entry.record.artifact_type,
                    content_checksum=projection.content_checksum,
                    source_byte_size=lineage.candidate_bytes,
                    source_token_estimate=lineage.candidate_tokens,
                    media_type=projection.media_type,
                    artifact_class=projection.artifact_class,
                    sensitivity=projection.sensitivity,
                    context_policy=projection.context_policy,
                    producer_revision=lineage.producer_revision,
                    tenant_id=projection.tenant_id,
                    run_id=projection.run_id,
                    graph_id=projection.graph_id,
                    node_id=projection.node_id,
                    attempt_id=projection.attempt_id,
                    physical_run_id=entry.record.run_id,
                    physical_graph_id=entry.record.graph_id,
                    physical_node_id=entry.record.node_id,
                    physical_attempt_id=entry.record.attempt_id,
                    summary=BoundedSummary.from_dict(lineage.summary.to_dict()),
                    admitted_bytes=admitted_bytes,
                    admitted_tokens=admitted_tokens,
                )
            )
        plan = ApprovedArtifactLoadPlan.create(
            request=request,
            policy_version=self._config.policy_version,
            items=items,
        )
        if (
            plan.planned_loaded_bytes > request.max_bytes
            or plan.planned_loaded_tokens > request.max_tokens
        ):
            raise result_error(
                GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED,
                field="context.load_budget",
                actual=max(
                    plan.planned_loaded_bytes,
                    plan.planned_loaded_tokens,
                ),
                limit=max(request.max_bytes, request.max_tokens),
            )
        return plan

    def _validate_request_budget(self, request: ContextAssemblyRequest) -> None:
        for field_name, actual, limit in (
            ("max_refs", request.max_refs, self._config.max_context_artifact_refs),
            ("max_bytes", request.max_bytes, self._config.max_context_loaded_bytes),
            ("max_tokens", request.max_tokens, self._config.max_context_loaded_tokens),
        ):
            if actual > limit:
                raise result_error(
                    GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED,
                    field=f"context.{field_name}",
                    actual=actual,
                    limit=limit,
                )

    def _catalog_records(
        self,
        projection: HarnessGraphArtifactRefProjection,
    ) -> tuple[ArtifactCatalogClaim, ArtifactCatalogEntry]:
        try:
            claim = self._catalog.get_claim(
                tenant_id=projection.tenant_id,
                run_id=projection.run_id,
                artifact_id=projection.artifact_id,
            )
            entry = self._catalog.get(claim.entry_id)
        except GraphArtifactResultError:
            raise
        except Exception as exc:
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_CATALOG_NOT_FOUND,
                field="context.catalog",
            ) from exc
        if not isinstance(claim, ArtifactCatalogClaim) or not isinstance(
            entry,
            ArtifactCatalogEntry,
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_CATALOG_CORRUPT,
                field="context.catalog",
            )
        return claim, entry

    @staticmethod
    def _validate_catalog_match(
        lineage: HarnessGraphResultLineage,
        projection: HarnessGraphArtifactRefProjection,
        claim: ArtifactCatalogClaim,
        entry: ArtifactCatalogEntry,
        request: ContextAssemblyRequest,
    ) -> None:
        record = claim.record
        physical_record = entry.record
        sensitivities = {
            ResultSensitivity(projection.sensitivity),
            record.sensitivity,
            physical_record.sensitivity,
        }
        if (
            ResultSensitivity.SECRET in sensitivities
        ):
            raise result_error(
                GraphArtifactResultErrorCode.SENSITIVE_PAYLOAD_REJECTED,
                field="context.sensitivity",
            )
        if (
            ArtifactClass(projection.artifact_class)
            not in request.allowed_artifact_classes
            or not sensitivities.issubset(set(request.allowed_sensitivities))
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="context.authorization",
            )
        policy = ContextPolicy(projection.context_policy)
        if (
            request.load_mode is ContextLoadMode.SAMPLE
            and policy is ContextPolicy.SUMMARY_ONLY
        ) or (
            request.load_mode is ContextLoadMode.FULL
            and policy is not ContextPolicy.REF_LOAD_ALLOWED
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="context.load_mode",
            )
        scope = (
            projection.tenant_id,
            projection.run_id,
            projection.graph_id,
            projection.node_id,
            projection.attempt_id,
        )
        if scope != record.scope() or scope[:3] != (
            request.tenant_id,
            request.run_id,
            request.graph_id,
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_SCOPE_MISMATCH,
                field="context.catalog_scope",
            )
        lineage_fields = {
            "ref": projection.ref,
            "artifact_id": projection.artifact_id,
            "artifact_type": projection.artifact_type,
            "content_checksum": projection.content_checksum,
            "byte_size": projection.byte_size,
            "media_type": projection.media_type,
            "artifact_class": projection.artifact_class,
            "retention_class": projection.retention_class,
            "sensitivity": projection.sensitivity,
            "required_for_replay": projection.required_for_replay,
            "required_for_publication": projection.required_for_publication,
            "producer_revision": lineage.producer_revision,
        }
        record_fields = {
            "ref": record.ref,
            "artifact_id": record.artifact_id,
            "artifact_type": record.artifact_type,
            "content_checksum": record.content_checksum,
            "byte_size": record.byte_size,
            "media_type": record.media_type,
            "artifact_class": record.artifact_class.value,
            "retention_class": record.retention_class.value,
            "sensitivity": record.sensitivity.value,
            "required_for_replay": record.required_for_replay,
            "required_for_publication": record.required_for_publication,
            "producer_revision": record.producer_revision,
        }
        if lineage_fields != record_fields or (
            lineage.candidate_checksum != projection.content_checksum
            or lineage.candidate_bytes != projection.byte_size
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_CATALOG_CORRUPT,
                field="context.catalog_identity",
            )
        if (
            claim.entry_id != entry.entry_id
            or physical_record.ref != projection.ref
            or physical_record.tenant_id != projection.tenant_id
            or physical_record.content_checksum != projection.content_checksum
            or physical_record.byte_size != projection.byte_size
            or physical_record.media_type != projection.media_type
            or physical_record.producer_revision != lineage.producer_revision
        ):
            raise result_error(
                GraphArtifactResultErrorCode.ARTIFACT_CATALOG_CORRUPT,
                field="context.catalog_physical_identity",
            )

    def _admitted_budget(
        self,
        lineage: HarnessGraphResultLineage,
        mode: ContextLoadMode,
    ) -> tuple[int, int]:
        if mode is ContextLoadMode.SUMMARY_ONLY:
            return lineage.summary.byte_size, lineage.summary.token_estimate
        if mode is ContextLoadMode.SAMPLE:
            size = min(lineage.candidate_bytes, self._config.sample_max_bytes)
            return size, estimated_tokens(size)
        return lineage.candidate_bytes, lineage.candidate_tokens


class ArtifactContextLoader:
    def __init__(
        self,
        *,
        reader: GraphResultArtifactReadPort,
        config: GraphArtifactPersistenceConfig,
    ) -> None:
        if not isinstance(reader, GraphResultArtifactReadPort):
            raise TypeError("reader must implement GraphResultArtifactReadPort")
        if not isinstance(config, GraphArtifactPersistenceConfig):
            raise TypeError("config must be GraphArtifactPersistenceConfig")
        self._reader = reader
        self._config = config

    def load(self, plan: ApprovedArtifactLoadPlan) -> ArtifactContextLoadResult:
        if not isinstance(plan, ApprovedArtifactLoadPlan):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="load_plan",
            )
        self._config.ensure_readable_policy_version(plan.policy_version)
        loaded: list[ArtifactContextItem] = []
        for item in plan.items:
            if plan.request.load_mode is ContextLoadMode.SUMMARY_ONLY:
                loaded.append(self._summary_item(item))
                continue
            try:
                stored = self._reader.read_graph_result_artifact(
                    item.ref,
                    expected_run_id=item.physical_run_id,
                )
                candidate, candidate_bytes = _verified_candidate(stored, item)
            except GraphArtifactResultError as exc:
                if exc.error_code is GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED:
                    raise
                raise result_error(
                    GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
                    field="context.artifact_read",
                ) from exc
            except Exception as exc:
                raise result_error(
                    GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
                    field="context.artifact_read",
                ) from exc
            loaded.append(
                self._sample_item(item, candidate_bytes)
                if plan.request.load_mode is ContextLoadMode.SAMPLE
                else self._full_item(item, candidate, candidate_bytes)
            )
        result = ArtifactContextLoadResult.create(plan, items=loaded)
        if (
            result.total_loaded_bytes > plan.request.max_bytes
            or result.total_loaded_tokens > plan.request.max_tokens
        ):
            raise result_error(
                GraphArtifactResultErrorCode.CONTEXT_BUDGET_EXCEEDED,
                field="context.loaded_budget",
            )
        return result

    @staticmethod
    def _summary_item(item: ApprovedArtifactLoadItem) -> ArtifactContextItem:
        content_bytes = item.summary.text.encode("utf-8")
        return ArtifactContextItem(
            ref=item.ref,
            content_checksum=item.content_checksum,
            source_byte_size=item.source_byte_size,
            source_token_estimate=item.source_token_estimate,
            media_type=item.media_type,
            artifact_class=item.artifact_class,
            sensitivity=item.sensitivity,
            load_mode=ContextLoadMode.SUMMARY_ONLY,
            content=item.summary.text,
            encoding="summary",
            complete=item.summary.complete,
            loaded_bytes=len(content_bytes),
            loaded_tokens=estimated_tokens(len(content_bytes)),
            loaded_checksum=sha256_checksum(content_bytes),
        )

    def _sample_item(
        self,
        item: ApprovedArtifactLoadItem,
        candidate_bytes: bytes,
    ) -> ArtifactContextItem:
        sample = candidate_bytes[: self._config.sample_max_bytes]
        if item.media_type.startswith("text/") or item.media_type == "application/json" or item.media_type.endswith("+json"):
            content = sample.decode("utf-8", errors="ignore")
            admitted = content.encode("utf-8")
            encoding = "utf8_prefix"
        else:
            content = base64.b64encode(sample).decode("ascii")
            admitted = sample
            encoding = "base64_prefix"
        return ArtifactContextItem(
            ref=item.ref,
            content_checksum=item.content_checksum,
            source_byte_size=item.source_byte_size,
            source_token_estimate=item.source_token_estimate,
            media_type=item.media_type,
            artifact_class=item.artifact_class,
            sensitivity=item.sensitivity,
            load_mode=ContextLoadMode.SAMPLE,
            content=content,
            encoding=encoding,
            complete=False,
            loaded_bytes=len(admitted),
            loaded_tokens=estimated_tokens(len(admitted)),
            loaded_checksum=sha256_checksum(admitted),
        )

    @staticmethod
    def _full_item(
        item: ApprovedArtifactLoadItem,
        candidate: Any,
        candidate_bytes: bytes,
    ) -> ArtifactContextItem:
        if item.media_type == "application/json" or item.media_type.endswith("+json"):
            content = thaw_json(candidate)
            encoding = "json"
        elif item.media_type.startswith("text/"):
            content = candidate
            encoding = "text"
        else:
            content = base64.b64encode(candidate_bytes).decode("ascii")
            encoding = "base64"
        return ArtifactContextItem(
            ref=item.ref,
            content_checksum=item.content_checksum,
            source_byte_size=item.source_byte_size,
            source_token_estimate=item.source_token_estimate,
            media_type=item.media_type,
            artifact_class=item.artifact_class,
            sensitivity=item.sensitivity,
            load_mode=ContextLoadMode.FULL,
            content=content,
            encoding=encoding,
            complete=True,
            loaded_bytes=len(candidate_bytes),
            loaded_tokens=estimated_tokens(len(candidate_bytes)),
            loaded_checksum=sha256_checksum(candidate_bytes),
        )


def _verified_candidate(
    stored: Mapping[str, Any],
    item: ApprovedArtifactLoadItem,
) -> tuple[Any, bytes]:
    try:
        outer = exact_keys(
            stored,
            required=frozenset({"artifact_type", "payload", "media_type", "metadata"}),
            model="GraphResultArtifactWrapper",
        )
        metadata = exact_keys(
            outer["metadata"],
            required=frozenset(
                {
                    "tenant_id",
                    "run_id",
                    "graph_id",
                    "node_id",
                    "attempt_id",
                    "candidate_checksum",
                    "graph_result_ref_only",
                    "identity_checksum",
                }
            ),
            model="GraphResultArtifactMetadata",
        )
        identity_suffix = item.physical_artifact_type.removeprefix(
            "graph-result-"
        )
        if (
            not identity_suffix
            or outer["artifact_type"] != item.physical_artifact_type
            or outer["media_type"] != "application/json"
            or metadata
            != {
                "tenant_id": item.tenant_id,
                "run_id": item.physical_run_id,
                "graph_id": item.physical_graph_id,
                "node_id": item.physical_node_id,
                "attempt_id": item.physical_attempt_id,
                "candidate_checksum": item.content_checksum,
                "graph_result_ref_only": True,
                "identity_checksum": f"sha256:{identity_suffix}",
            }
        ):
            raise ValueError("graph result wrapper identity mismatch")
        payload = exact_keys(
            outer["payload"],
            required=frozenset(
                {
                    "schema",
                    "candidate_checksum",
                    "candidate_bytes",
                    "media_type",
                    "encoding",
                    "value",
                }
            ),
            model="GraphResultPayload",
        )
        if (
            payload["schema"] != RESULT_PAYLOAD_SCHEMA
            or payload["candidate_checksum"] != item.content_checksum
            or payload["candidate_bytes"] != item.source_byte_size
            or payload["media_type"] != item.media_type
        ):
            raise ValueError("graph result payload identity mismatch")
        encoding = payload["encoding"]
        if encoding == "json" and (
            item.media_type == "application/json" or item.media_type.endswith("+json")
        ):
            candidate = payload["value"]
        elif encoding == "text" and item.media_type.startswith("text/"):
            candidate = payload["value"]
        elif encoding == "base64" and not (
            item.media_type.startswith("text/")
            or item.media_type == "application/json"
            or item.media_type.endswith("+json")
        ):
            candidate = base64.b64decode(payload["value"], validate=True)
        else:
            raise ValueError("graph result payload encoding mismatch")
        candidate, candidate_bytes = serialize_candidate(candidate, item.media_type)
        if (
            len(candidate_bytes) != item.source_byte_size
            or sha256_checksum(candidate_bytes) != item.content_checksum
        ):
            raise ValueError("graph result payload checksum mismatch")
        return candidate, candidate_bytes
    except GraphArtifactResultError as exc:
        raise result_error(
            GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
            field="context.artifact_payload",
        ) from exc
    except (TypeError, ValueError, base64.binascii.Error) as exc:
        raise result_error(
            GraphArtifactResultErrorCode.ARTIFACT_READBACK_FAILED,
            field="context.artifact_payload",
        ) from exc


def _context_content_bytes(content: Any, encoding: str) -> bytes:
    thawed = thaw_json(content)
    if encoding == "json":
        return canonical_json_bytes(thawed)
    if encoding in {"summary", "text", "utf8_prefix"}:
        if not isinstance(thawed, str):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field="context_item.content",
            )
        return thawed.encode("utf-8")
    if not isinstance(thawed, str):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="context_item.content",
        )
    try:
        return base64.b64decode(thawed, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field="context_item.content",
        ) from exc


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise result_error(
            GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
            field=field_name,
        )
    result: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise result_error(
                GraphArtifactResultErrorCode.RESULT_SCHEMA_INVALID,
                field=field_name,
            )
        result.append(item)
    return tuple(result)


__all__ = [
    "APPROVED_ARTIFACT_LOAD_PLAN_SCHEMA",
    "ARTIFACT_CONTEXT_LOAD_RESULT_SCHEMA",
    "ApprovedArtifactLoadItem",
    "ApprovedArtifactLoadPlan",
    "ArtifactContextItem",
    "ArtifactContextLoadResult",
    "ArtifactContextLoader",
    "ArtifactContextLoadPlanner",
    "ArtifactContextProviderPort",
]
