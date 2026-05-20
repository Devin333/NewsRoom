from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4


class MemoryScope(str, Enum):
    SESSION = "session"
    AGENT = "agent"
    WORKFLOW = "workflow"
    GLOBAL = "global"


class MemoryKind(str, Enum):
    CORE = "core"
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    OBSERVATION = "observation"


class MemoryWriteMode(str, Enum):
    APPEND = "append"
    UPSERT = "upsert"


@dataclass(frozen=True)
class MemoryPolicy:
    allowed_scopes: list[MemoryScope | str] = field(default_factory=list)
    allowed_kinds: list[MemoryKind | str] = field(default_factory=list)
    allow_write: bool = True
    allow_recall: bool = True
    require_refs: bool = True
    max_recall_results: int = 10
    max_context_tokens: int = 2000


DEFAULT_AGENT_MEMORY_POLICY = MemoryPolicy(
    allowed_scopes=[MemoryScope.SESSION, MemoryScope.AGENT, MemoryScope.WORKFLOW],
    allowed_kinds=[MemoryKind.CORE, MemoryKind.SEMANTIC, MemoryKind.EPISODIC, MemoryKind.OBSERVATION],
    allow_write=False,
    allow_recall=True,
    max_recall_results=5,
    max_context_tokens=1500,
)
DEFAULT_AGENT_MEMORY_WRITE_POLICY = MemoryPolicy(
    allowed_scopes=[MemoryScope.SESSION, MemoryScope.AGENT, MemoryScope.WORKFLOW],
    allowed_kinds=[MemoryKind.EPISODIC, MemoryKind.OBSERVATION],
    allow_write=True,
    allow_recall=False,
    max_recall_results=1,
    max_context_tokens=1,
)


@dataclass(frozen=True)
class MemoryQuery:
    query: str
    scopes: list[MemoryScope | str] = field(default_factory=list)
    kinds: list[MemoryKind | str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    limit: int = 10
    max_context_tokens: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "scopes": [_enum_value(item) for item in self.scopes],
            "kinds": [_enum_value(item) for item in self.kinds],
            "filters": dict(self.filters),
            "limit": self.limit,
            "max_context_tokens": self.max_context_tokens,
        }


@dataclass(frozen=True)
class MemoryRecord:
    content: str
    kind: MemoryKind | str = MemoryKind.SEMANTIC
    scope: MemoryScope | str = MemoryScope.SESSION
    memory_id: str = field(default_factory=lambda: uuid4().hex)
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    refs: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "kind": _enum_value(self.kind),
            "scope": _enum_value(self.scope),
            "summary": self.summary,
            "content": self.content,
            "metadata": dict(self.metadata),
            "refs": dict(self.refs),
            "tags": list(self.tags),
        }


class AgentMemoryAdapter:
    def before_llm_call(self, *, agent_id: str, run_id: str, input_text: str, runtime: Any, policy: Any = DEFAULT_AGENT_MEMORY_POLICY) -> Any:
        query = MemoryQuery(
            query=input_text,
            scopes=[MemoryScope.SESSION, MemoryScope.AGENT, MemoryScope.WORKFLOW],
            kinds=[MemoryKind.CORE, MemoryKind.SEMANTIC, MemoryKind.EPISODIC],
            filters={"agent_id": agent_id, "run_id": run_id} if run_id else {"agent_id": agent_id},
            limit=int(getattr(policy, "max_recall_results", 5)),
            max_context_tokens=int(getattr(policy, "max_context_tokens", 1500)),
        )
        runtime_policy = _runtime_policy(runtime, policy, write=False)
        try:
            return runtime.recall(query.to_dict(), policy=runtime_policy)
        except TypeError:
            return runtime.recall(query, policy=runtime_policy)

    def after_tool_observation(self, *, agent_id: str, run_id: str, tool_name: str, observation: dict[str, Any], runtime: Any, policy: Any = DEFAULT_AGENT_MEMORY_WRITE_POLICY) -> Any:
        record = MemoryRecord(
            kind=MemoryKind.OBSERVATION,
            scope=MemoryScope.AGENT,
            summary=f"Tool observation from {tool_name}",
            content=str(observation),
            metadata={"agent_id": agent_id, "tool_name": tool_name},
            refs={"run_id": run_id} if run_id else {},
        )
        return runtime.write(
            records=[record.to_dict()],
            actor=agent_id,
            run_id=run_id,
            policy=_runtime_policy(runtime, policy, write=True),
        )

    def after_final_output(self, *, agent_id: str, run_id: str, output: dict[str, Any], runtime: Any, policy: Any = DEFAULT_AGENT_MEMORY_WRITE_POLICY) -> Any:
        record = MemoryRecord(
            kind=MemoryKind.EPISODIC,
            scope=MemoryScope.AGENT,
            summary=f"Final output from {agent_id}",
            content=str(output),
            metadata={"agent_id": agent_id},
            refs={"run_id": run_id} if run_id else {},
        )
        return runtime.write(
            records=[record.to_dict()],
            actor=agent_id,
            run_id=run_id,
            policy=_runtime_policy(runtime, policy, write=True),
        )


def _enum_value(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _runtime_policy(runtime: Any, policy: Any, *, write: bool) -> Any:
    validator_name = "validate_write" if write else "validate_recall"
    if hasattr(policy, validator_name):
        return policy
    runtime_policy = getattr(runtime, "policy", None)
    policy_cls = runtime_policy.__class__ if runtime_policy is not None else None
    if policy_cls is None:
        return policy
    kwargs = {
        "allowed_scopes": ["session", "agent", "workflow"],
        "allowed_kinds": (
            ["episodic", "observation"]
            if write
            else ["core", "semantic", "episodic", "observation"]
        ),
        "allow_write": write,
        "allow_recall": not write,
        "require_refs": True,
        "max_recall_results": int(getattr(policy, "max_recall_results", 5)),
        "max_context_tokens": int(getattr(policy, "max_context_tokens", 1500)),
    }
    if "allow_global_write" in getattr(policy_cls, "__dataclass_fields__", {}):
        kwargs["allow_global_write"] = False
    try:
        return policy_cls(**kwargs)
    except Exception:
        return None


class MemoryRuntime:
    """Protocol-shaped placeholder for type compatibility."""

    def recall(self, query: Any, *, policy: Any | None = None) -> Any:
        raise NotImplementedError

    def write(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError
