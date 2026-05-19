from __future__ import annotations

from dataclasses import dataclass, field

from core.framework.memory.models import MemoryKind, MemoryQuery, MemoryRecord, MemoryScope


@dataclass(frozen=True)
class MemoryPolicy:
    allowed_scopes: list[MemoryScope] = field(default_factory=list)
    allowed_kinds: list[MemoryKind] = field(default_factory=list)
    allow_write: bool = True
    allow_recall: bool = True
    require_refs: bool = False
    max_recall_results: int = 10
    max_context_tokens: int = 2000
    allow_global_write: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_scopes", [_scope(scope) for scope in self.allowed_scopes])
        object.__setattr__(self, "allowed_kinds", [_kind(kind) for kind in self.allowed_kinds])
        object.__setattr__(self, "max_recall_results", max(1, int(self.max_recall_results)))
        object.__setattr__(self, "max_context_tokens", max(1, int(self.max_context_tokens)))

    def validate_recall(self, query: MemoryQuery) -> None:
        if not self.allow_recall:
            raise PermissionError("memory recall is disabled by policy")
        if query.scopes and self.allowed_scopes:
            denied = [scope.value for scope in query.scopes if scope not in self.allowed_scopes]
            if denied:
                raise PermissionError(f"memory recall scope is not allowed: {', '.join(denied)}")
        if query.kinds and self.allowed_kinds:
            denied = [kind.value for kind in query.kinds if kind not in self.allowed_kinds]
            if denied:
                raise PermissionError(f"memory recall kind is not allowed: {', '.join(denied)}")

    def validate_write(self, record: MemoryRecord) -> None:
        if not self.allow_write:
            raise PermissionError("memory write is disabled by policy")
        if self.allowed_scopes and record.scope not in self.allowed_scopes:
            raise PermissionError(f"memory write scope is not allowed: {record.scope.value}")
        if self.allowed_kinds and record.kind not in self.allowed_kinds:
            raise PermissionError(f"memory write kind is not allowed: {record.kind.value}")
        if record.scope == MemoryScope.GLOBAL and not self.allow_global_write:
            raise PermissionError("global memory writes are disabled by policy")
        if self.require_refs and not record.refs:
            raise ValueError("memory refs are required by policy")

    def filtered_query(self, query: MemoryQuery) -> MemoryQuery:
        scopes = query.scopes or list(self.allowed_scopes)
        kinds = query.kinds or list(self.allowed_kinds)
        return MemoryQuery(
            query=query.query,
            scopes=scopes,
            kinds=kinds,
            filters=query.filters,
            limit=min(query.limit, self.max_recall_results),
            min_score=query.min_score,
            max_context_tokens=min(
                query.max_context_tokens or self.max_context_tokens,
                self.max_context_tokens,
            ),
        )


def _scope(value) -> MemoryScope:
    if isinstance(value, MemoryScope):
        return value
    return MemoryScope(str(value))


def _kind(value) -> MemoryKind:
    if isinstance(value, MemoryKind):
        return value
    return MemoryKind(str(value))


DEFAULT_AGENT_MEMORY_POLICY = MemoryPolicy(
    allowed_scopes=[
        MemoryScope.AGENT,
        MemoryScope.WORKFLOW,
        MemoryScope.SESSION,
        MemoryScope.GLOBAL,
    ],
    allowed_kinds=[
        MemoryKind.CORE,
        MemoryKind.SEMANTIC,
        MemoryKind.EPISODIC,
        MemoryKind.OBSERVATION,
        MemoryKind.ARTIFACT,
    ],
    allow_write=True,
    allow_recall=True,
    require_refs=False,
    max_recall_results=10,
    max_context_tokens=2000,
    allow_global_write=False,
)

DEFAULT_WORKFLOW_MEMORY_POLICY = MemoryPolicy(
    allowed_scopes=[
        MemoryScope.WORKFLOW,
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
