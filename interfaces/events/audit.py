from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from interfaces.models.actor import ActorContext
from interfaces.models.audit import AuditRecord, AuditResult


DEFAULT_AUDIT_PATH = ".newsroom/audit/audit.jsonl"


class AuditSink(Protocol):
    def append(self, record: AuditRecord) -> None: ...


class InMemoryAuditSink:
    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        self.records.append(record)


class LocalJsonAuditSink:
    def __init__(self, path: str | Path = DEFAULT_AUDIT_PATH) -> None:
        self.path = Path(path)

    def append(self, record: AuditRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


class AuditEmitter:
    def __init__(self, sink: AuditSink, *, swallow_errors: bool = True) -> None:
        self.sink = sink
        self.swallow_errors = swallow_errors

    def emit(
        self,
        *,
        actor: ActorContext,
        action: str,
        resource_type: str,
        result: AuditResult,
        resource_id: str | None = None,
        permission: str | None = None,
        scope_ref: str | None = None,
        reason_code: str | None = None,
        request_id: str | None = None,
        run_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditRecord | None:
        try:
            record = AuditRecord(
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                result=result,
                permission=permission,
                scope_ref=scope_ref,
                reason_code=reason_code,
                request_id=request_id or actor.request_id,
                run_id=run_id,
                correlation_id=correlation_id or request_id or actor.request_id,
                metadata=_redact_sensitive_keys(metadata or {}),
            )
            self.sink.append(record)
            return record
        except Exception:
            if self.swallow_errors:
                return None
            raise


def audit_emitter_from_env(
    *,
    env: dict[str, str] | None = None,
    path: str | Path | None = None,
) -> AuditEmitter:
    values = env if env is not None else os.environ
    audit_path = path or values.get("NEWS_AUDIT_LOG_PATH") or DEFAULT_AUDIT_PATH
    return AuditEmitter(LocalJsonAuditSink(audit_path))


def _redact_sensitive_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if _is_sensitive_key(key) else _redact_sensitive_keys(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_keys(item) for item in value]
    return value


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(
        fragment in normalized
        for fragment in (
            "api_key",
            "apikey",
            "authorization",
            "cookie",
            "password",
            "secret",
            "token",
        )
    )
