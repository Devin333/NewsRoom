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
        if not records:
            return MemoryWriteResult(
                accepted_count=len(request.records),
                skipped_count=len(errors),
                errors=errors,
            )
        if request.mode.value == "upsert":
            result = _write_upsert(records, store=store)
        else:
            result = store.write_many(records)
        return MemoryWriteResult(
            accepted_count=len(request.records),
            written_count=result.written_count,
            memory_ids=list(result.memory_ids),
            skipped_count=result.skipped_count + len(errors),
            errors=[*errors, *result.errors],
        )


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


def _write_upsert(records: list[MemoryRecord], *, store: MemoryStore) -> MemoryWriteResult:
    written_count = 0
    skipped_count = 0
    memory_ids: list[str] = []
    errors: list[str] = []
    for record in records:
        existing = store.get(record.memory_id)
        if existing is None:
            result = store.write(record)
            written_count += result.written_count
            skipped_count += result.skipped_count
            memory_ids.extend(result.memory_ids)
            errors.extend(result.errors)
            continue
        try:
            store.update(record.memory_id, record.to_dict())
        except NotImplementedError:
            skipped_count += 1
            continue
        written_count += 1
        memory_ids.append(record.memory_id)
    return MemoryWriteResult(
        accepted_count=len(records),
        written_count=written_count,
        memory_ids=memory_ids,
        skipped_count=skipped_count,
        errors=errors,
    )
