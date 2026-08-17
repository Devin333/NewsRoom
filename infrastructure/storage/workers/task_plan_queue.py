from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.task_plan.canonical import identifier, positive_int
from framework.harness.task_plan.queue import (
    TaskPlanQueueReadback,
)
from framework.workers.models.task import Task


_READ_TASK_PLAN_QUEUE_SCRIPT = r"""
local queue_name = KEYS[1]
local group_name = ARGV[1]
local scan_limit = tonumber(ARGV[2])

local groups = redis.pcall('XINFO', 'GROUPS', queue_name)
if type(groups) == 'table' and groups.err then
    if not string.find(groups.err, 'no such key') then
        return {'error', groups.err}
    end
    groups = {}
end

local group_found = false
local last_delivered_id = '0-0'
for _, group in ipairs(groups) do
    local current_name = nil
    local current_last_id = nil
    for index = 1, #group, 2 do
        if group[index] == 'name' then
            current_name = group[index + 1]
        elseif group[index] == 'last-delivered-id' then
            current_last_id = group[index + 1]
        end
    end
    if current_name == group_name then
        group_found = true
        last_delivered_id = current_last_id or '0-0'
        break
    end
end

local pending = {}
local delivered = {}
if group_found then
    pending = redis.call(
        'XPENDING', queue_name, group_name, '-', '+', scan_limit
    )
    if last_delivered_id ~= '0-0' then
        delivered = redis.call(
            'XRANGE', queue_name, '-', last_delivered_id, 'COUNT', scan_limit
        )
    end
end

local raw_undelivered = redis.call(
    'XRANGE', queue_name, last_delivered_id, '+', 'COUNT', scan_limit + 1
)
local undelivered = {}
for _, record in ipairs(raw_undelivered) do
    if record[1] ~= last_delivered_id then
        table.insert(undelivered, record)
    end
end

local pending_records = {}
for _, pending_entry in ipairs(pending) do
    local records = redis.call(
        'XRANGE', queue_name, pending_entry[1], pending_entry[1], 'COUNT', 1
    )
    if #records == 1 then
        table.insert(pending_records, records[1])
    end
end

return {
    'ok',
    group_found and '1' or '0',
    last_delivered_id,
    tostring(#undelivered),
    undelivered,
    tostring(#pending),
    pending_records,
    tostring(#delivered),
    delivered,
}
"""


class RedisTaskPlanQueueReadAdapter:
    """Atomically reads undelivered TaskPlan records without leasing them."""

    def __init__(
        self,
        redis_client: Any,
        *,
        group_name: str = "framework-workers",
        max_scan: int = 1_000,
    ) -> None:
        if not hasattr(redis_client, "eval"):
            raise TypeError("redis_client must provide eval")
        self._redis = redis_client
        self._group_name = identifier(group_name, "group_name")
        self._max_scan = positive_int(max_scan, "max_scan")

    def read_task_plan_queue(
        self,
        *,
        queue_name: str,
        task_instance_ids: tuple[str, ...],
    ) -> tuple[TaskPlanQueueReadback, ...]:
        normalized_queue = identifier(queue_name, "queue_name")
        expected_ids = tuple(
            sorted(identifier(item, "task_instance_ids") for item in task_instance_ids)
        )
        if len(expected_ids) != len(set(expected_ids)):
            raise HarnessValidationError(
                "TaskPlan queue read requested duplicate task instances",
                code="task_plan_queue_readback_conflict",
            )
        if not expected_ids:
            return ()

        raw = self._redis.eval(
            _READ_TASK_PLAN_QUEUE_SCRIPT,
            1,
            normalized_queue,
            self._group_name,
            self._max_scan + 1,
        )
        response = _decode_nested(raw)
        if not isinstance(response, list) or len(response) < 2:
            raise RuntimeError("invalid Redis TaskPlan queue read-back response")
        if response[0] == "error":
            raise RuntimeError(f"Redis TaskPlan queue read-back failed: {response[1]}")
        if len(response) != 9 or response[0] != "ok":
            raise RuntimeError("invalid Redis TaskPlan queue read-back response")

        undelivered_count = _response_count(response[3], "undelivered_count")
        pending_count = _response_count(response[5], "pending_count")
        delivered_count = _response_count(response[7], "delivered_count")
        if (
            undelivered_count > self._max_scan
            or pending_count > self._max_scan
            or delivered_count > self._max_scan
        ):
            raise HarnessValidationError(
                "TaskPlan queue read-back exceeded its bounded scan",
                code="task_plan_queue_readback_scan_incomplete",
                details={
                    "queue_name": normalized_queue,
                    "max_scan": self._max_scan,
                    "undelivered_count": undelivered_count,
                    "pending_count": pending_count,
                    "delivered_count": delivered_count,
                },
            )

        undelivered = _records(response[4], "undelivered_records")
        pending = _records(response[6], "pending_records")
        delivered = _records(response[8], "delivered_records")
        if len(undelivered) != undelivered_count:
            raise RuntimeError("Redis undelivered TaskPlan record count does not match")
        if len(pending) != pending_count:
            raise RuntimeError("Redis pending TaskPlan record count does not match")
        if len(delivered) != delivered_count:
            raise RuntimeError("Redis delivered TaskPlan record count does not match")

        expected = set(expected_ids)
        pending_message_ids: set[str] = set()
        for record in pending:
            message_id, payload = _task_record(record)
            pending_message_ids.add(message_id)
            task_id = _record_task_id(payload, message_id=message_id)
            if task_id in expected:
                raise HarnessValidationError(
                    "READY TaskPlan attempt already has a pending queue lease",
                    code="task_plan_queue_delivery_state_mismatch",
                    details={
                        "queue_name": normalized_queue,
                        "message_id": message_id,
                        "task_instance_id": task_id,
                    },
                )

        for record in delivered:
            message_id, payload = _task_record(record)
            if message_id in pending_message_ids:
                continue
            task_id = _record_task_id(payload, message_id=message_id)
            if task_id in expected:
                raise HarnessValidationError(
                    "READY TaskPlan attempt was already delivered and acknowledged",
                    code="task_plan_queue_delivery_state_mismatch",
                    details={
                        "queue_name": normalized_queue,
                        "message_id": message_id,
                        "task_instance_id": task_id,
                    },
                )

        readbacks: list[TaskPlanQueueReadback] = []
        seen: set[str] = set()
        for record in undelivered:
            message_id, payload = _task_record(record)
            task_id = _record_task_id(payload, message_id=message_id)
            if task_id not in expected:
                continue
            if task_id in seen:
                raise HarnessValidationError(
                    "TaskPlan queue contains duplicate undelivered attempts",
                    code="task_plan_queue_readback_conflict",
                    details={"task_instance_id": task_id},
                )
            try:
                task = Task.from_dict(payload)
                readback = TaskPlanQueueReadback.from_queue_task(message_id, task)
            except (KeyError, TypeError, ValueError) as exc:
                raise HarnessValidationError(
                    "durable TaskPlan queue record is invalid",
                    code="task_plan_queue_transport_mismatch",
                    details={"message_id": message_id},
                ) from exc
            seen.add(task_id)
            readbacks.append(readback)
        return tuple(sorted(readbacks, key=lambda item: item.task_instance_id))


def _decode_nested(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, tuple):
        return [_decode_nested(item) for item in value]
    if isinstance(value, list):
        return [_decode_nested(item) for item in value]
    return value


def _response_count(value: Any, field_name: str) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid Redis TaskPlan {field_name}") from exc
    if count < 0:
        raise RuntimeError(f"invalid Redis TaskPlan {field_name}")
    return count


def _records(value: Any, field_name: str) -> list[list[Any]]:
    if not isinstance(value, list):
        raise RuntimeError(f"invalid Redis TaskPlan {field_name}")
    records: list[list[Any]] = []
    for record in value:
        if not isinstance(record, list) or len(record) != 2:
            raise RuntimeError(f"invalid Redis TaskPlan {field_name}")
        records.append(record)
    return records


def _task_record(record: Sequence[Any]) -> tuple[str, dict[str, Any]]:
    message_id = identifier(record[0], "message_id")
    fields = record[1]
    raw_task: Any = None
    if isinstance(fields, Mapping):
        raw_task = fields.get("task")
    elif isinstance(fields, Sequence) and not isinstance(fields, (str, bytes)):
        if len(fields) % 2 != 0:
            raise RuntimeError("invalid Redis TaskPlan stream fields")
        for index in range(0, len(fields), 2):
            if fields[index] == "task":
                raw_task = fields[index + 1]
                break
    if not isinstance(raw_task, str):
        raise RuntimeError("Redis TaskPlan stream record is missing task payload")
    try:
        payload = json.loads(raw_task)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Redis TaskPlan stream task payload is invalid") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Redis TaskPlan stream task payload must be an object")
    return message_id, payload


def _record_task_id(payload: Mapping[str, Any], *, message_id: str) -> str:
    try:
        return identifier(payload["task_id"], "task_id")
    except (KeyError, TypeError, ValueError) as exc:
        raise HarnessValidationError(
            "durable queue record has no stable task identity",
            code="task_plan_queue_transport_mismatch",
            details={"message_id": message_id},
        ) from exc


__all__ = ["RedisTaskPlanQueueReadAdapter"]
