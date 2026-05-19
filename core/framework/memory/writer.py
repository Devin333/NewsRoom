from __future__ import annotations

from dataclasses import replace

from core.framework.memory.models import MemoryRecord, MemoryWriteRequest, MemoryWriteResult
from core.framework.memory.policy import MemoryPolicy
from core.framework.memory.store import MemoryStore


class MemoryWriter:
    def write(
        self,
        request: MemoryWriteRequest,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
    ) -> MemoryWriteResult:
        records: list[MemoryRecord] = []
        errors: list[str] = []
        for record in request.records:
            candidate = _record_with_request_defaults(
                record,
                actor=request.actor,
                run_id=request.run_id,
            )
            try:
                policy.validate_write(candidate)
            except Exception as exc:
                errors.append(str(exc))
                continue
            records.append(candidate)
        if errors:
            return MemoryWriteResult(
                accepted_count=len(request.records),
                written_count=0,
                skipped_count=len(request.records),
                errors=errors,
            )
        if not records:
            return MemoryWriteResult()
        return store.write_many(records)


def _record_with_request_defaults(
    record: MemoryRecord,
    *,
    actor: str | None,
    run_id: str | None,
) -> MemoryRecord:
    refs = dict(record.refs)
    if run_id:
        refs.setdefault("run_id", run_id)
    return replace(
        record,
        actor=record.actor or actor,
        refs=refs,
    )

