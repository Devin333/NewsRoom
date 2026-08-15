from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any, Literal, Protocol, runtime_checkable

from framework.events.canonical import checksum_for
from framework.harness.memory import MemoryWriteCandidate, MemoryWriteStatus
from framework.shared.time import format_datetime

from business.research.domain.reader_repair import (
    READER_REPAIR_NAMESPACE,
    ReaderRepairCase,
    ReaderRepairMemoryQuery,
    ReaderRepairSkillCandidateSeed,
    ReaderRepairStrategy,
    stable_research_id,
)


READER_REPAIR_MEMORY_EFFECT_KIND = "memory_write"
READER_REPAIR_MEMORY_HANDLER_ID = "research.reader_repair.memory.commit"
READER_REPAIR_MEMORY_HANDLER_VERSION = "1"
READER_REPAIR_MEMORY_HANDLER_REF = (
    f"{READER_REPAIR_MEMORY_HANDLER_ID}@{READER_REPAIR_MEMORY_HANDLER_VERSION}"
)
READER_REPAIR_MEMORY_SCHEMA_VERSION = "newsroom.research-reader-repair-memory/v1"
READER_REPAIR_MEMORY_STEP_ID = "prepare_memory_write"

_CHECKSUM_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_FORBIDDEN_AUTHORITY_KEYS = frozenset(
    {
        "active_skill_package",
        "production_skill_version",
        "promote_skill",
        "publish",
        "publish_artifact",
    }
)


@dataclass(frozen=True)
class ReaderRepairMemoryVersion:
    memory_ref: str
    object_type: Literal["case", "strategy"]
    object_id: str
    version: int
    operation: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReaderRepairMemoryCandidateProjection:
    """Validated, typed projection of one proposed Reader Repair memory bundle."""

    candidate: MemoryWriteCandidate
    repair_case: ReaderRepairCase
    strategies: tuple[ReaderRepairStrategy, ...]
    skill_candidate_seeds: tuple[ReaderRepairSkillCandidateSeed, ...]
    candidate_checksum: str


@dataclass(frozen=True, slots=True)
class ReaderRepairMemoryCommitRequest:
    """Atomic terminal commit request presented to a durable memory adapter."""

    request_id: str
    run_id: str
    terminal_effect_id: str
    candidate: MemoryWriteCandidate
    candidate_checksum: str
    prepared_outcome_ref: str
    authorization_ref: str
    identity_scope_ref: str
    subject_scope_ref: str
    atomic_group: str
    idempotency_key: str
    schema_version: str = READER_REPAIR_MEMORY_SCHEMA_VERSION
    checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "run_id",
            "terminal_effect_id",
            "atomic_group",
            "idempotency_key",
        ):
            _require_text(getattr(self, field_name), field_name)
        for field_name in (
            "candidate_checksum",
            "prepared_outcome_ref",
            "authorization_ref",
            "identity_scope_ref",
            "subject_scope_ref",
        ):
            _require_checksum(getattr(self, field_name), field_name)
        if self.schema_version != READER_REPAIR_MEMORY_SCHEMA_VERSION:
            raise ValueError("reader repair memory commit request schema is unsupported")
        projection = validate_reader_repair_memory_candidate(self.candidate)
        object.__setattr__(self, "candidate", projection.candidate)
        if self.candidate_checksum != projection.candidate_checksum:
            raise ValueError("reader repair memory candidate checksum does not match")
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("reader repair memory commit request checksum does not match")
        object.__setattr__(self, "checksum", expected)

    @property
    def projection(self) -> ReaderRepairMemoryCandidateProjection:
        projection = validate_reader_repair_memory_candidate(self.candidate)
        if projection.candidate_checksum != self.candidate_checksum:
            raise ValueError("reader repair memory request candidate was mutated")
        return projection

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> ReaderRepairMemoryCommitRequest:
        _require_exact_fields(
            value,
            {
                "schema_version",
                "request_id",
                "run_id",
                "terminal_effect_id",
                "candidate",
                "candidate_checksum",
                "prepared_outcome_ref",
                "authorization_ref",
                "identity_scope_ref",
                "subject_scope_ref",
                "atomic_group",
                "idempotency_key",
                "checksum",
            },
            "reader repair memory commit request",
        )
        raw_candidate = value["candidate"]
        if not isinstance(raw_candidate, Mapping):
            raise TypeError("reader repair memory commit candidate must be an object")
        return cls(
            request_id=value["request_id"],
            run_id=value["run_id"],
            terminal_effect_id=value["terminal_effect_id"],
            candidate=_candidate_from_mapping(raw_candidate),
            candidate_checksum=value["candidate_checksum"],
            prepared_outcome_ref=value["prepared_outcome_ref"],
            authorization_ref=value["authorization_ref"],
            identity_scope_ref=value["identity_scope_ref"],
            subject_scope_ref=value["subject_scope_ref"],
            atomic_group=value["atomic_group"],
            idempotency_key=value["idempotency_key"],
            schema_version=value["schema_version"],
            checksum=value["checksum"],
        )

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "run_id": self.run_id,
            "terminal_effect_id": self.terminal_effect_id,
            "candidate": self.candidate.to_dict(),
            "candidate_checksum": self.candidate_checksum,
            "prepared_outcome_ref": self.prepared_outcome_ref,
            "authorization_ref": self.authorization_ref,
            "identity_scope_ref": self.identity_scope_ref,
            "subject_scope_ref": self.subject_scope_ref,
            "atomic_group": self.atomic_group,
            "idempotency_key": self.idempotency_key,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


@dataclass(frozen=True, slots=True)
class ReaderRepairMemoryCommitReceipt:
    """Idempotent receipt returned after one atomic case/strategy commit."""

    receipt_id: str
    request_ref: str
    run_id: str
    terminal_effect_id: str
    authorization_ref: str
    idempotency_key: str
    namespace: str
    case_ref: str
    case_version: int
    strategy_refs: tuple[str, ...] = ()
    strategy_versions: tuple[int, ...] = ()
    committed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = READER_REPAIR_MEMORY_SCHEMA_VERSION
    checksum: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "run_id",
            "terminal_effect_id",
            "idempotency_key",
            "case_ref",
        ):
            _require_text(getattr(self, field_name), field_name)
        _require_checksum(self.request_ref, "request_ref")
        _require_checksum(self.authorization_ref, "authorization_ref")
        if self.namespace != READER_REPAIR_NAMESPACE:
            raise ValueError("reader repair memory receipt namespace is invalid")
        case_version = _require_positive_int(self.case_version, "case_version")
        object.__setattr__(self, "case_version", case_version)
        strategy_refs = tuple(_require_text(ref, "strategy_ref") for ref in self.strategy_refs)
        if len(strategy_refs) != len(set(strategy_refs)):
            raise ValueError("reader repair memory strategy refs must be unique")
        object.__setattr__(self, "strategy_refs", strategy_refs)
        strategy_versions = tuple(
            _require_positive_int(version, "strategy_version")
            for version in self.strategy_versions
        )
        if len(strategy_versions) != len(strategy_refs):
            raise ValueError("reader repair memory strategy versions do not match refs")
        object.__setattr__(self, "strategy_versions", strategy_versions)
        if not isinstance(self.committed_at, datetime):
            raise TypeError("committed_at must be datetime")
        if self.committed_at.tzinfo is None or self.committed_at.utcoffset() is None:
            raise ValueError("committed_at must be timezone-aware")
        object.__setattr__(self, "committed_at", self.committed_at.astimezone(UTC))
        if self.schema_version != READER_REPAIR_MEMORY_SCHEMA_VERSION:
            raise ValueError("reader repair memory commit receipt schema is unsupported")
        expected = checksum_for(self._checksum_payload())
        if self.checksum is not None and self.checksum != expected:
            raise ValueError("reader repair memory commit receipt checksum does not match")
        object.__setattr__(self, "checksum", expected)

    @property
    def public_refs(self) -> tuple[str, ...]:
        return (self.case_ref, *self.strategy_refs)

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any],
    ) -> ReaderRepairMemoryCommitReceipt:
        _require_exact_fields(
            value,
            {
                "schema_version",
                "receipt_id",
                "request_ref",
                "run_id",
                "terminal_effect_id",
                "authorization_ref",
                "idempotency_key",
                "namespace",
                "case_ref",
                "case_version",
                "strategy_refs",
                "strategy_versions",
                "committed_at",
                "checksum",
            },
            "reader repair memory commit receipt",
        )
        committed_at = value["committed_at"]
        if not isinstance(committed_at, str):
            raise TypeError("reader repair memory receipt committed_at must be a string")
        normalized_time = committed_at.replace("Z", "+00:00")
        return cls(
            receipt_id=value["receipt_id"],
            request_ref=value["request_ref"],
            run_id=value["run_id"],
            terminal_effect_id=value["terminal_effect_id"],
            authorization_ref=value["authorization_ref"],
            idempotency_key=value["idempotency_key"],
            namespace=value["namespace"],
            case_ref=value["case_ref"],
            case_version=value["case_version"],
            strategy_refs=tuple(value["strategy_refs"]),
            strategy_versions=tuple(value["strategy_versions"]),
            committed_at=datetime.fromisoformat(normalized_time),
            schema_version=value["schema_version"],
            checksum=value["checksum"],
        )

    def _checksum_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "request_ref": self.request_ref,
            "run_id": self.run_id,
            "terminal_effect_id": self.terminal_effect_id,
            "authorization_ref": self.authorization_ref,
            "idempotency_key": self.idempotency_key,
            "namespace": self.namespace,
            "case_ref": self.case_ref,
            "case_version": self.case_version,
            "strategy_refs": list(self.strategy_refs),
            "strategy_versions": list(self.strategy_versions),
            "committed_at": format_datetime(self.committed_at),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._checksum_payload(), "checksum": self.checksum}


@runtime_checkable
class ReaderRepairMemoryPort(Protocol):
    def write_case(self, repair_case: ReaderRepairCase, *, namespace: str) -> str:
        ...

    def recall_cases(self, query: ReaderRepairMemoryQuery) -> tuple[ReaderRepairCase, ...]:
        ...

    def write_strategy(self, strategy: ReaderRepairStrategy, *, namespace: str) -> str:
        ...

    def recall_strategies(self, issue_type: str, *, namespace: str) -> list[ReaderRepairStrategy]:
        ...

    def list_cases(self, *, namespace: str) -> tuple[ReaderRepairCase, ...]:
        ...

    def list_case_versions(
        self,
        repair_case_id: str,
        *,
        namespace: str,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        ...

    def rollback_case(
        self,
        repair_case_id: str,
        *,
        namespace: str,
        version: int,
    ) -> str:
        ...

    def list_strategy_versions(
        self,
        strategy_id: str,
        *,
        namespace: str,
    ) -> tuple[ReaderRepairMemoryVersion, ...]:
        ...

    def rollback_strategy(
        self,
        strategy_id: str,
        *,
        namespace: str,
        version: int,
    ) -> str:
        ...

    def propose_write(self, candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
        ...


@runtime_checkable
class ReaderRepairMemoryCommitPort(Protocol):
    """Atomic, idempotent terminal writer for Reader Repair memory bundles.

    Implementations must commit the case and every projected strategy in one
    transaction. Repeating an idempotency key must return the same immutable
    receipt without creating new versions.
    """

    def commit(
        self,
        request: ReaderRepairMemoryCommitRequest,
    ) -> ReaderRepairMemoryCommitReceipt:
        ...


def validate_reader_repair_memory_candidate(
    candidate: MemoryWriteCandidate,
) -> ReaderRepairMemoryCandidateProjection:
    if not isinstance(candidate, MemoryWriteCandidate):
        raise TypeError("candidate must be MemoryWriteCandidate")
    candidate = _copy_candidate(candidate)
    if candidate.namespace != READER_REPAIR_NAMESPACE:
        raise ValueError("reader repair memory candidate namespace is invalid")
    if candidate.status is not MemoryWriteStatus.PROPOSED:
        raise ValueError("reader repair memory candidate must remain proposed")
    if set(candidate.content) != {"repair_case", "strategy_candidate_bundle"}:
        raise ValueError("reader repair memory candidate content fields are invalid")
    repair_case = ReaderRepairCase.model_validate(candidate.content["repair_case"])
    bundle = candidate.content["strategy_candidate_bundle"]
    if not isinstance(bundle, Mapping) or set(bundle) != {
        "input_bindings",
        "strategies",
        "skill_candidate_seeds",
    }:
        raise ValueError("reader repair strategy candidate bundle fields are invalid")
    strategies = tuple(
        ReaderRepairStrategy.model_validate(item)
        for item in _mapping_sequence(bundle["strategies"], "strategies")
    )
    seeds = tuple(
        ReaderRepairSkillCandidateSeed.model_validate(item)
        for item in _mapping_sequence(
            bundle["skill_candidate_seeds"],
            "skill_candidate_seeds",
        )
    )
    _validate_candidate_bindings(candidate, repair_case, bundle)
    _validate_strategy_bundle(repair_case, strategies, seeds)
    forbidden = _nested_keys((candidate.content, candidate.metadata)).intersection(
        _FORBIDDEN_AUTHORITY_KEYS
    )
    if forbidden:
        raise ValueError(
            "reader repair memory candidate contains authority fields: "
            f"{sorted(forbidden)}"
        )
    candidate_checksum = checksum_for(candidate.to_dict())
    return ReaderRepairMemoryCandidateProjection(
        candidate=candidate,
        repair_case=repair_case,
        strategies=strategies,
        skill_candidate_seeds=seeds,
        candidate_checksum=candidate_checksum,
    )


def reader_repair_case_memory_ref(
    repair_case: ReaderRepairCase,
    *,
    version: int,
) -> str:
    exact_version = _require_positive_int(version, "version")
    return (
        f"memory://{READER_REPAIR_NAMESPACE}/case/"
        f"{repair_case.repair_case_id}/versions/{exact_version}"
    )


def reader_repair_strategy_memory_ref(
    strategy: ReaderRepairStrategy,
    *,
    version: int,
) -> str:
    exact_version = _require_positive_int(version, "version")
    return (
        f"memory://{READER_REPAIR_NAMESPACE}/strategy/"
        f"{strategy.strategy_id}/versions/{exact_version}"
    )


def _validate_candidate_bindings(
    candidate: MemoryWriteCandidate,
    repair_case: ReaderRepairCase,
    strategy_bundle: Mapping[str, Any],
) -> None:
    expected_candidate_id = stable_research_id(
        "repair_memory_write",
        repair_case.repair_case_id,
    )
    if candidate.candidate_id != expected_candidate_id:
        raise ValueError("reader repair memory candidate id is invalid")
    if tuple(candidate.source_refs) != tuple(repair_case.source_refs):
        raise ValueError("reader repair memory candidate source refs do not match")
    if candidate.metadata.get("active_skill_mutation") is not False:
        raise ValueError("reader repair memory candidate cannot mutate active skills")
    if repair_case.metadata.get("active_skill_mutation") is not False:
        raise ValueError("reader repair case cannot mutate active skills")
    expected_bindings = {
        "reader_repair_case": checksum_for(repair_case.to_dict()),
        "strategy_candidate_bundle": checksum_for(dict(strategy_bundle)),
    }
    if candidate.metadata.get("input_bindings") != expected_bindings:
        raise ValueError("reader repair memory candidate input bindings do not match")
    bundle_bindings = strategy_bundle.get("input_bindings")
    if not isinstance(bundle_bindings, Mapping) or set(bundle_bindings) != {
        "reader_repair_context_pack",
        "reader_repair_case",
    }:
        raise ValueError("reader repair strategy input bindings are invalid")
    if bundle_bindings.get("reader_repair_case") != checksum_for(
        repair_case.to_dict()
    ):
        raise ValueError("reader repair strategy case binding does not match")
    for field_name, value in bundle_bindings.items():
        _require_checksum(value, str(field_name))


def _validate_strategy_bundle(
    repair_case: ReaderRepairCase,
    strategies: tuple[ReaderRepairStrategy, ...],
    seeds: tuple[ReaderRepairSkillCandidateSeed, ...],
) -> None:
    strategy_by_id = {strategy.strategy_id: strategy for strategy in strategies}
    if len(strategy_by_id) != len(strategies):
        raise ValueError("reader repair strategy ids must be unique")
    for strategy in strategies:
        if repair_case.repair_case_id not in strategy.source_case_refs:
            raise ValueError("reader repair strategy must reference the committed case")
        if strategy.status not in {"promoted_memory", "skill_candidate_ready"}:
            raise ValueError("reader repair strategy is not eligible for memory")
    seen_seed_ids: set[str] = set()
    for seed in seeds:
        if seed.seed_id in seen_seed_ids:
            raise ValueError("reader repair skill candidate seed ids must be unique")
        seen_seed_ids.add(seed.seed_id)
        strategy = strategy_by_id.get(seed.strategy.strategy_id)
        if strategy is None or seed.strategy != strategy:
            raise ValueError("reader repair skill seed is not bound to a strategy")
        expected_experience_refs = {
            f"repair-case://{case_id}" for case_id in strategy.source_case_refs
        }
        if set(seed.experience_refs) != expected_experience_refs:
            raise ValueError("reader repair skill seed experience refs do not match")
        if not seed.metadata.get("requires_harness_skill_evolution"):
            raise ValueError("reader repair skill seed requires Harness evolution")


def _copy_candidate(candidate: MemoryWriteCandidate) -> MemoryWriteCandidate:
    payload = candidate.to_dict()
    copied = MemoryWriteCandidate(
        candidate_id=payload["candidate_id"],
        namespace=payload["namespace"],
        content=dict(payload["content"]),
        source_refs=tuple(payload["source_refs"]),
        status=payload["status"],
        metadata=dict(payload["metadata"]),
    )
    object.__setattr__(copied, "content", _deep_immutable(copied.content))
    object.__setattr__(copied, "metadata", _deep_immutable(copied.metadata))
    return copied


def _candidate_from_mapping(value: Mapping[str, Any]) -> MemoryWriteCandidate:
    _require_exact_fields(
        value,
        {
            "candidate_id",
            "namespace",
            "content",
            "source_refs",
            "status",
            "metadata",
        },
        "reader repair memory candidate",
    )
    return MemoryWriteCandidate(
        candidate_id=value["candidate_id"],
        namespace=value["namespace"],
        content=dict(value["content"]),
        source_refs=tuple(value["source_refs"]),
        status=value["status"],
        metadata=dict(value["metadata"]),
    )


def _deep_immutable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _deep_immutable(item) for key, item in value.items()}
        )
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return tuple(_deep_immutable(item) for item in value)
    return value


def _mapping_sequence(value: Any, field_name: str) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise TypeError(f"{field_name} must be an array")
    if not all(isinstance(item, Mapping) for item in value):
        raise TypeError(f"{field_name} must contain objects")
    return tuple(value)


def _nested_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, Mapping):
            for key, item in current.items():
                keys.add(str(key).casefold())
                pending.append(item)
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes):
            pending.extend(current)
    return keys


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value


def _require_checksum(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CHECKSUM_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be sha256:<64 lowercase hex>")
    return value


def _require_positive_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str],
    model_name: str,
) -> None:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError(f"{model_name} fields are invalid")


__all__ = [
    "READER_REPAIR_MEMORY_EFFECT_KIND",
    "READER_REPAIR_MEMORY_HANDLER_ID",
    "READER_REPAIR_MEMORY_HANDLER_REF",
    "READER_REPAIR_MEMORY_HANDLER_VERSION",
    "READER_REPAIR_MEMORY_SCHEMA_VERSION",
    "READER_REPAIR_MEMORY_STEP_ID",
    "ReaderRepairMemoryCandidateProjection",
    "ReaderRepairMemoryCommitPort",
    "ReaderRepairMemoryCommitReceipt",
    "ReaderRepairMemoryCommitRequest",
    "ReaderRepairMemoryPort",
    "ReaderRepairMemoryVersion",
    "reader_repair_case_memory_ref",
    "reader_repair_strategy_memory_ref",
    "validate_reader_repair_memory_candidate",
]
