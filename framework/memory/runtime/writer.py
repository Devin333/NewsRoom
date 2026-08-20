from __future__ import annotations

from dataclasses import replace
from typing import Any

from framework.memory.models import MemoryRecord, MemoryScope, MemoryWriteMode, MemoryWriteRequest, MemoryWriteResult
from framework.memory.models.reference import legacy_refs_from_references
from framework.memory.policy import MemoryPolicy
from framework.memory.stores import MemoryStore
from framework.shared.graph_identity import GraphExecutionIdentity
from framework.shared.time import utc_now


class MemoryWriter:
    def write(
        self,
        request: MemoryWriteRequest,
        *,
        store: MemoryStore,
        policy: MemoryPolicy,
    ) -> MemoryWriteResult:
        _validate_write_mode(request.mode)
        records: list[MemoryRecord] = []
        errors: list[str] = []
        for record in request.records:
            candidate = _record_with_request_defaults(
                record,
                actor=request.actor,
                run_id=request.run_id,
                execution_identity=request.execution_identity,
                namespace=request.namespace,
                tenant_id=request.tenant_id,
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
        if request.mode == MemoryWriteMode.UPSERT:
            result = _write_upsert(records, store=store)
        elif request.mode == MemoryWriteMode.MERGE:
            result = _write_merge(records, store=store)
        elif request.mode == MemoryWriteMode.PROMOTE:
            result = _write_promote(records, store=store)
        elif request.mode == MemoryWriteMode.INVALIDATE:
            result = _write_invalidate(records, store=store)
        else:
            result = store.write_many(records)
        return MemoryWriteResult(
            accepted_count=len(request.records),
            written_count=result.written_count,
            memory_ids=list(result.memory_ids),
            skipped_count=result.skipped_count + len(errors),
            errors=[*errors, *result.errors],
        )


def _validate_write_mode(mode: MemoryWriteMode) -> None:
    if mode in {
        MemoryWriteMode.APPEND,
        MemoryWriteMode.UPSERT,
        MemoryWriteMode.MERGE,
        MemoryWriteMode.PROMOTE,
        MemoryWriteMode.INVALIDATE,
    }:
        return
    raise NotImplementedError(f"memory write mode is not implemented: {mode.value}")


def _record_with_request_defaults(
    record: MemoryRecord,
    *,
    actor: str | None,
    run_id: str | None,
    execution_identity: GraphExecutionIdentity | None,
    namespace: str | None,
    tenant_id: str | None,
) -> MemoryRecord:
    refs = _record_refs(record)
    if execution_identity is not None:
        if run_id is not None and run_id != execution_identity.run_id:
            raise ValueError("run_id must match execution_identity.run_id")
        identity_refs = execution_identity.to_dict()
        existing_identity_refs = {
            key: refs[key] for key in identity_refs if key in refs
        }
        if existing_identity_refs and existing_identity_refs != {
            key: identity_refs[key] for key in existing_identity_refs
        }:
            raise ValueError("memory record Graph lineage does not match execution_identity")
        refs.update(identity_refs)
        run_id = execution_identity.run_id
    elif run_id:
        refs.setdefault("run_id", run_id)
    return replace(
        record,
        actor=record.actor or actor,
        namespace=record.namespace or namespace,
        tenant_id=record.tenant_id or tenant_id,
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


def _write_merge(records: list[MemoryRecord], *, store: MemoryStore) -> MemoryWriteResult:
    merged: dict[str, MemoryRecord] = {}
    for record in records:
        existing = store.get(record.memory_id)
        if existing is None:
            merged[record.memory_id] = record
            continue
        merged[record.memory_id] = replace(
            existing,
            summary=record.summary or existing.summary,
            content=record.content or existing.content,
            metadata={**existing.metadata, **record.metadata},
            refs={**_record_refs(existing), **_record_refs(record)},
            tags=sorted({*existing.tags, *record.tags}),
            confidence=_max_optional(existing.confidence, record.confidence),
            importance=_max_optional(existing.importance, record.importance),
            score=record.score or existing.score,
            actor=record.actor or existing.actor,
            namespace=record.namespace or existing.namespace,
            tenant_id=record.tenant_id or existing.tenant_id,
            updated_at=utc_now(),
        )
    return _write_upsert(list(merged.values()), store=store)


def _write_promote(records: list[MemoryRecord], *, store: MemoryStore) -> MemoryWriteResult:
    promoted = [replace(record, scope=_promoted_scope(record.scope)) for record in records]
    return _write_upsert(promoted, store=store)


def _write_invalidate(records: list[MemoryRecord], *, store: MemoryStore) -> MemoryWriteResult:
    written_count = 0
    skipped_count = 0
    memory_ids: list[str] = []
    errors: list[str] = []
    for record in records:
        existing = store.get(record.memory_id)
        if existing is None:
            skipped_count += 1
            continue
        invalidated = existing.mark_invalidated("invalidated by write mode")
        try:
            store.update(existing.memory_id, invalidated.to_dict())
        except NotImplementedError as exc:
            skipped_count += 1
            errors.append(str(exc))
            continue
        written_count += 1
        memory_ids.append(existing.memory_id)
    return MemoryWriteResult(
        accepted_count=len(records),
        written_count=written_count,
        memory_ids=memory_ids,
        skipped_count=skipped_count,
        errors=errors,
    )


def _promoted_scope(scope: MemoryScope) -> MemoryScope:
    order = [
        MemoryScope.WORKING,
        MemoryScope.SESSION,
        MemoryScope.AGENT,
        MemoryScope.GRAPH,
        MemoryScope.GLOBAL,
    ]
    try:
        index = order.index(scope)
    except ValueError:
        return scope
    if index >= len(order) - 1:
        return scope
    return order[index + 1]


def _max_optional(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _record_refs(record: MemoryRecord) -> dict[str, Any]:
    if isinstance(record.refs, dict):
        return dict(record.refs)
    return legacy_refs_from_references(record.refs)
