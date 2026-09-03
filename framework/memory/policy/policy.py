from __future__ import annotations

from dataclasses import dataclass, field

from framework.memory.exceptions import MemoryPolicyDenied, MemoryValidationError
from framework.memory.models import MemoryKind, MemoryQuery, MemoryRecord, MemoryScope


@dataclass(frozen=True)
class MemoryPolicy:
    allowed_scopes: list[MemoryScope] = field(default_factory=list)
    allowed_kinds: list[MemoryKind] = field(default_factory=list)
    allow_write: bool = True
    allow_recall: bool = True
    require_refs: bool = True
    min_confidence_to_write: float = 0.3
    min_confidence_to_recall: float = 0.0
    max_recall_results: int = 10
    max_context_tokens: int = 2000
    allow_global_write: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_scopes", [_scope(scope) for scope in self.allowed_scopes])
        object.__setattr__(self, "allowed_kinds", [_kind(kind) for kind in self.allowed_kinds])
        object.__setattr__(self, "min_confidence_to_write", _score(self.min_confidence_to_write))
        object.__setattr__(self, "min_confidence_to_recall", _score(self.min_confidence_to_recall))
        object.__setattr__(self, "max_recall_results", max(1, int(self.max_recall_results)))
        object.__setattr__(self, "max_context_tokens", max(1, int(self.max_context_tokens)))

    def validate_recall(self, query: MemoryQuery) -> None:
        if not self.allow_recall:
            raise MemoryPolicyDenied("memory recall is disabled by policy")
        if query.scopes and self.allowed_scopes:
            denied = [scope.value for scope in query.scopes if scope not in self.allowed_scopes]
            if denied:
                raise MemoryPolicyDenied(f"memory recall scope is not allowed: {', '.join(denied)}")
        if query.kinds and self.allowed_kinds:
            denied = [kind.value for kind in query.kinds if kind not in self.allowed_kinds]
            if denied:
                raise MemoryPolicyDenied(f"memory recall kind is not allowed: {', '.join(denied)}")
        if query.min_score is not None and query.min_score < self.min_confidence_to_recall:
            raise MemoryPolicyDenied("memory recall min_score is below policy minimum")

    def validate_write(
        self,
        record: MemoryRecord,
        *,
        operation: str = "write",
    ) -> None:
        self.validate_operation(operation, record=record)
        if self.require_refs and not record.refs:
            raise MemoryValidationError("memory refs are required by policy")
        if record.confidence is not None and record.confidence < self.min_confidence_to_write:
            raise MemoryPolicyDenied("memory write confidence is below policy minimum")

    def validate_operation(
        self,
        operation: str,
        *,
        record: MemoryRecord | None = None,
        target_scope: MemoryScope | str | None = None,
        target_kind: MemoryKind | str | None = None,
    ) -> None:
        """Validate a mutating memory operation against its effective target.

        Promotion must validate the post-promotion target rather than the source
        record. This keeps all mutation paths subject to the same scope/kind and
        global-write controls.
        """
        operation_name = getattr(operation, "value", operation)
        operation_name = str(operation_name).lower()
        if operation_name not in {"write", "promote", "invalidate", "forget"}:
            raise ValueError(f"unsupported memory policy operation: {operation_name}")
        if not self.allow_write:
            raise MemoryPolicyDenied(f"memory {operation_name} is disabled by policy")

        effective_scope = (
            _scope(target_scope)
            if target_scope is not None
            else (record.scope if record else None)
        )
        effective_kind = (
            _kind(target_kind)
            if target_kind is not None
            else (record.kind if record else None)
        )
        if effective_scope is None or effective_kind is None:
            raise MemoryValidationError(f"memory {operation_name} requires a target record")
        if self.allowed_scopes and effective_scope not in self.allowed_scopes:
            raise MemoryPolicyDenied(
                f"memory {operation_name} scope is not allowed: {effective_scope.value}"
            )
        if self.allowed_kinds and effective_kind not in self.allowed_kinds:
            raise MemoryPolicyDenied(
                f"memory {operation_name} kind is not allowed: {effective_kind.value}"
            )
        if effective_scope == MemoryScope.GLOBAL and not self.allow_global_write:
            raise MemoryPolicyDenied("global memory writes are disabled by policy")

    def filtered_query(self, query: MemoryQuery) -> MemoryQuery:
        scopes = query.scopes or list(self.allowed_scopes)
        kinds = query.kinds or list(self.allowed_kinds)
        return MemoryQuery(
            query=query.query,
            scopes=scopes,
            kinds=kinds,
            filters=query.filters,
            tags=query.tags,
            namespace=query.namespace,
            tenant_id=query.tenant_id,
            limit=min(query.limit, self.max_recall_results),
            min_score=_effective_min_score(query.min_score, self.min_confidence_to_recall),
            max_context_tokens=min(
                query.max_context_tokens or self.max_context_tokens,
                self.max_context_tokens,
            ),
            time_window=query.time_window,
            include_invalidated=query.include_invalidated,
            include_expired=query.include_expired,
        )


def _scope(value) -> MemoryScope:
    return value if isinstance(value, MemoryScope) else MemoryScope(str(value))


def _kind(value) -> MemoryKind:
    return value if isinstance(value, MemoryKind) else MemoryKind(str(value))


def _score(value) -> float:
    numeric = float(value)
    if numeric < 0.0 or numeric > 1.0:
        raise ValueError("memory policy score thresholds must be between 0 and 1")
    return numeric


def _effective_min_score(query_min_score: float | None, policy_min_score: float) -> float | None:
    if query_min_score is None and policy_min_score <= 0.0:
        return None
    return max(policy_min_score, query_min_score if query_min_score is not None else policy_min_score)


DEFAULT_AGENT_MEMORY_POLICY = MemoryPolicy(
    allowed_scopes=[
        MemoryScope.SESSION,
        MemoryScope.AGENT,
        MemoryScope.GRAPH,
    ],
    allowed_kinds=[
        MemoryKind.CORE,
        MemoryKind.SEMANTIC,
        MemoryKind.EPISODIC,
        MemoryKind.OBSERVATION,
    ],
    allow_write=False,
    allow_recall=True,
    require_refs=True,
    max_recall_results=5,
    max_context_tokens=1500,
    allow_global_write=False,
)

DEFAULT_AGENT_MEMORY_WRITE_POLICY = MemoryPolicy(
    allowed_scopes=[
        MemoryScope.SESSION,
        MemoryScope.AGENT,
        MemoryScope.GRAPH,
    ],
    allowed_kinds=[
        MemoryKind.EPISODIC,
        MemoryKind.OBSERVATION,
    ],
    allow_write=True,
    allow_recall=False,
    require_refs=True,
    max_recall_results=1,
    max_context_tokens=1,
    allow_global_write=False,
)

DEFAULT_GRAPH_MEMORY_POLICY = MemoryPolicy(
    allowed_scopes=[
        MemoryScope.GRAPH,
        MemoryScope.SESSION,
        MemoryScope.GLOBAL,
    ],
    allowed_kinds=[
        MemoryKind.CORE,
        MemoryKind.SEMANTIC,
        MemoryKind.EPISODIC,
        MemoryKind.ARTIFACT,
        MemoryKind.OBSERVATION,
    ],
    allow_write=True,
    allow_recall=True,
    require_refs=True,
    max_recall_results=10,
    max_context_tokens=2000,
    allow_global_write=False,
)

DEFAULT_ADMIN_MEMORY_POLICY = MemoryPolicy(
    allowed_scopes=list(MemoryScope),
    allowed_kinds=list(MemoryKind),
    allow_write=True,
    allow_recall=True,
    require_refs=True,
    max_recall_results=50,
    max_context_tokens=4000,
    allow_global_write=True,
)


MemoryRecallPolicy = MemoryPolicy
MemoryWritePolicy = MemoryPolicy
