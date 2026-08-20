from __future__ import annotations

import json

import pytest

from framework.workers import StaleTaskLeaseError, Task, TaskError, WorkerExecutionScope
from infrastructure.storage.workers.redis_queue import RedisStreamTaskQueue


QUEUE = "news:queue:test"


def test_active_lease_cannot_be_reclaimed_and_renewal_extends_server_expiry() -> None:
    redis = _LeaseScriptFakeRedis()
    queue = RedisStreamTaskQueue(redis, lease_ttl_ms=1_000)
    queue.enqueue(Task(task_type="test", payload={}, queue_name=QUEUE, task_id="task-1", execution_scope=WorkerExecutionScope.STANDALONE))

    original = queue.lease_one("worker-a", [QUEUE], block_ms=0)
    assert original is not None
    redis.advance(600)

    assert queue.reclaim_stale_one("worker-b", [QUEUE], min_idle_ms=500) is None
    renewed_until = queue.renew(original)
    redis.advance(600)

    assert renewed_until == original.task.lease_expires_at
    assert renewed_until == original.lease_expires_at
    assert queue.reclaim_stale_one("worker-b", [QUEUE], min_idle_ms=500) is None
    assert redis.claim_count == 0


def test_renewal_interval_is_strictly_below_one_third_even_for_small_ttl() -> None:
    queue = RedisStreamTaskQueue(_LeaseScriptFakeRedis(), lease_ttl_ms=3)
    interval = queue.renewal_interval_seconds(object())  # type: ignore[arg-type]

    assert 0 < interval < 0.003 / 3


def test_expired_reclaim_has_monotonic_attempt_and_fencing_generation() -> None:
    redis = _LeaseScriptFakeRedis()
    queue = RedisStreamTaskQueue(redis, lease_ttl_ms=1_000)
    queue.enqueue(Task(task_type="test", payload={}, queue_name=QUEUE, task_id="task-1", execution_scope=WorkerExecutionScope.STANDALONE))

    first = queue.lease_one("worker-a", [QUEUE], block_ms=0)
    assert first is not None
    redis.advance(1_001)
    second = queue.reclaim_stale_one("worker-b", [QUEUE], min_idle_ms=500)
    assert second is not None
    redis.advance(1_001)
    third = queue.reclaim_stale_one("worker-c", [QUEUE], min_idle_ms=500)
    assert third is not None

    assert [first.attempt, second.attempt, third.attempt] == [1, 2, 3]
    assert [first.fencing_token, second.fencing_token, third.fencing_token] == [1, 2, 3]
    assert len({first.lease_id, second.lease_id, third.lease_id}) == 3
    assert first.effect_key == second.effect_key == third.effect_key == "task:task-1"


def test_reclaim_skips_renewed_first_candidate_and_claims_later_expired_entry() -> None:
    redis = _LeaseScriptFakeRedis()
    queue = RedisStreamTaskQueue(redis, lease_ttl_ms=1_000)
    queue.enqueue(Task(task_type="test", payload={}, queue_name=QUEUE, task_id="task-active", execution_scope=WorkerExecutionScope.STANDALONE))
    queue.enqueue(Task(task_type="test", payload={}, queue_name=QUEUE, task_id="task-expired", execution_scope=WorkerExecutionScope.STANDALONE))

    active = queue.lease_one("worker-a", [QUEUE], block_ms=0)
    expired = queue.lease_one("worker-a", [QUEUE], block_ms=0)
    assert active is not None and expired is not None
    redis.advance(900)
    queue.renew(active)
    redis.advance(200)

    reclaimed = queue.reclaim_stale_one(
        "worker-b",
        [QUEUE],
        min_idle_ms=500,
        pending_count=10,
    )

    assert reclaimed is not None
    assert reclaimed.task.task_id == "task-expired"
    assert redis.claim_count == 1


def test_stale_owner_cannot_complete_after_reclaim_and_current_completion_is_idempotent() -> None:
    redis = _LeaseScriptFakeRedis()
    queue = RedisStreamTaskQueue(redis, lease_ttl_ms=1_000)
    queue.enqueue(Task(task_type="test", payload={}, queue_name=QUEUE, task_id="task-1", execution_scope=WorkerExecutionScope.STANDALONE))

    stale = queue.lease_one("worker-a", [QUEUE], block_ms=0)
    assert stale is not None
    redis.advance(1_001)
    current = queue.reclaim_stale_one("worker-b", [QUEUE], min_idle_ms=500)
    assert current is not None

    with pytest.raises(StaleTaskLeaseError):
        queue.ack(stale)
    assert redis.acked == []

    assert queue.ack(current) == 1
    assert queue.ack(current) == 1
    assert redis.acked == [(QUEUE, "framework-workers", current.message_id)]


def test_guarded_retry_transition_is_atomic_and_idempotent() -> None:
    redis = _LeaseScriptFakeRedis()
    queue = RedisStreamTaskQueue(redis, lease_ttl_ms=1_000)
    queue.enqueue(
        Task(
            task_type="test",
            payload={"document_id": "doc-1"},
            queue_name=QUEUE,
            task_id="task-1",
            execution_scope=WorkerExecutionScope.STANDALONE,
        )
    )
    leased = queue.lease_one("worker-a", [QUEUE], block_ms=0)
    assert leased is not None

    first = queue.fail(leased, TaskError("TimeoutError", "provider timed out"))
    repeated = queue.fail(leased, TaskError("TimeoutError", "provider timed out"))

    assert first.message_id == repeated.message_id
    assert len(redis.streams[QUEUE]) == 2
    assert redis.acked == [(QUEUE, "framework-workers", leased.message_id)]


def test_guarded_dlq_transition_strips_entire_business_record_and_is_idempotent() -> None:
    secret = "postgresql://alice:hunter2@database.internal/news"
    redis = _LeaseScriptFakeRedis()
    queue = RedisStreamTaskQueue(redis, lease_ttl_ms=1_000)
    task = Task(
        task_type="test",
        payload={
            "note": secret,
            "nested": {"ordinary": "Bearer deeply-secret"},
            "password": "explicit-secret",
        },
        metadata={"diagnostic": {"text": secret}},
        queue_name=QUEUE,
        task_id="task-1",
        max_attempts=1,
        execution_scope=WorkerExecutionScope.STANDALONE,
    )
    queue.enqueue(task)
    leased = queue.lease_one("worker-a", [QUEUE], block_ms=0)
    assert leased is not None

    first = queue.fail(
        leased,
        TaskError("DatabaseDriverError", f"failed against {secret}", retryable=False),
    )
    repeated = queue.fail(
        leased,
        TaskError("DatabaseDriverError", f"failed against {secret}", retryable=False),
    )

    assert first.message_id == repeated.message_id
    assert len(redis.streams[queue.dead_letter_queue_name]) == 1
    assert redis.acked == [(QUEUE, "framework-workers", leased.message_id)]
    raw_dlq = redis.streams[queue.dead_letter_queue_name][0][1]["task"]
    assert secret not in raw_dlq
    assert "deeply-secret" not in raw_dlq
    assert "explicit-secret" not in raw_dlq
    stored = json.loads(raw_dlq)
    assert stored["payload"] == {}
    assert set(stored["metadata"]) == {
        "business_payload_redacted",
        "business_payload_sha256",
    }
    assert stored["dead_letter_error"]["error_type"] == "WorkerInternalError"
    assert stored["dead_letter_error"]["error_message"] == "task execution failed"
    assert stored["dead_letter_error"]["error_id"].startswith("err_")

    listed = queue.list_dead_letters()
    assert len(listed) == 1
    assert listed[0].task.payload == {}
    assert listed[0].error is not None
    assert listed[0].error.error_id == stored["dead_letter_error"]["error_id"]

    assert queue.requeue_dead_letter("task-1") is False
    assert len(redis.streams[queue.dead_letter_queue_name]) == 1
    assert queue.requeue_dead_letter(
        "task-1",
        replacement_payload={"document_id": "doc-2"},
    ) is True
    requeued = json.loads(redis.streams[QUEUE][-1][1]["task"])
    assert requeued["payload"] == {"document_id": "doc-2"}
    assert secret not in json.dumps(requeued)
    assert requeued["metadata"]["dead_letter_error_id"].startswith("err_")
    assert redis.streams[queue.dead_letter_queue_name] == []


class _LeaseScriptFakeRedis:
    """Deterministic conformance fake for the lease script return contract."""

    def __init__(self) -> None:
        self.now_ms = 1_000_000
        self.streams: dict[str, list[tuple[str, dict[str, str]]]] = {}
        self.pending: dict[tuple[str, str], dict[str, object]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.groups: set[tuple[str, str]] = set()
        self.next_id = 1
        self.acked: list[tuple[str, str, str]] = []
        self.claim_count = 0

    def advance(self, milliseconds: int) -> None:
        self.now_ms += milliseconds

    def xadd(self, queue_name, fields):
        message_id = f"{self.next_id}-0"
        self.next_id += 1
        self.streams.setdefault(queue_name, []).append((message_id, dict(fields)))
        return message_id

    def xgroup_create(self, queue_name, group_name, *, id, mkstream):
        del id
        if mkstream:
            self.streams.setdefault(queue_name, [])
        key = (queue_name, group_name)
        if key in self.groups:
            raise RuntimeError("BUSYGROUP Consumer Group name already exists")
        self.groups.add(key)

    def xreadgroup(self, group_name, worker_id, streams, *, count, block):
        del block
        records = []
        for queue_name in streams:
            available = [
                entry
                for entry in self.streams.get(queue_name, [])
                if (queue_name, entry[0]) not in self.pending
            ][:count]
            if not available:
                continue
            for message_id, _fields in available:
                self.pending[(queue_name, message_id)] = {
                    "owner": worker_id,
                    "delivered_at_ms": self.now_ms,
                    "group": group_name,
                }
            records.append((queue_name, available))
        return records

    def xpending_range(self, queue_name, group_name, *, min, max, count):
        del min, max
        return [
            {
                "message_id": message_id,
                "time_since_delivered": self.now_ms - int(record["delivered_at_ms"]),
            }
            for (stored_queue, message_id), record in self.pending.items()
            if stored_queue == queue_name and record["group"] == group_name
        ][:count]

    def xrange(self, queue_name, *, min, max, count):
        return [
            entry
            for entry in self.streams.get(queue_name, [])
            if (min == "-" or min <= entry[0]) and (max == "+" or entry[0] <= max)
        ][:count]

    def eval(self, script, numkeys, *values):
        keys = [str(value) for value in values[:numkeys]]
        args = [str(value) for value in values[numkeys:]]
        if "newsroom:worker-lease-v1:acquire" in script:
            return self._acquire(keys, args)
        if "newsroom:worker-lease-v1:reclaim" in script:
            return self._reclaim(keys, args)
        if "newsroom:worker-lease-v1:renew" in script:
            return self._renew(keys, args)
        if "newsroom:worker-lease-v1:complete" in script:
            return self._complete(keys, args)
        if "newsroom:worker-lease-v1:transition" in script:
            return self._transition(keys, args)
        raise AssertionError("unexpected script")

    def _acquire(self, keys, args):
        lease_key, counter_key = keys
        version, task_id, queue_name, group_name, message_id, owner, lease_id, ttl, previous = args
        ledger = self.hashes.setdefault(lease_key, {})
        if self._active(ledger):
            return ["busy"]
        if ledger.get("state") and ledger.get("state") != "active":
            return ["terminal"]
        counter = self.hashes.setdefault(counter_key, {})
        counter.setdefault("attempt", previous)
        fencing = int(counter.get("fencing_token", "0")) + 1
        attempt = int(counter["attempt"]) + 1
        counter.update(fencing_token=str(fencing), attempt=str(attempt))
        expires = self.now_ms + int(ttl)
        ledger.update(
            version=version,
            task_id=task_id,
            queue=queue_name,
            group=group_name,
            message_id=message_id,
            owner=owner,
            lease_id=lease_id,
            fencing_token=str(fencing),
            attempt=str(attempt),
            expires_at_ms=str(expires),
            state="active",
        )
        return ["ok", fencing, attempt, expires]

    def _reclaim(self, keys, args):
        queue_name, lease_key, counter_key = keys
        group_name, message_id, task_id, owner, lease_id, ttl, version, previous = args
        ledger = self.hashes.setdefault(lease_key, {})
        if self._active(ledger):
            return ["busy"]
        pending = self.pending.get((queue_name, message_id))
        if pending is None:
            return ["missing"]
        self.claim_count += 1
        pending.update(owner=owner, delivered_at_ms=self.now_ms)
        counter = self.hashes.setdefault(counter_key, {})
        counter.setdefault("attempt", previous)
        fencing = int(counter.get("fencing_token", "0")) + 1
        attempt = int(counter["attempt"]) + 1
        counter.update(fencing_token=str(fencing), attempt=str(attempt))
        expires = self.now_ms + int(ttl)
        ledger.update(
            version=version,
            task_id=task_id,
            queue=queue_name,
            group=group_name,
            message_id=message_id,
            owner=owner,
            lease_id=lease_id,
            fencing_token=str(fencing),
            attempt=str(attempt),
            expires_at_ms=str(expires),
            state="active",
        )
        return ["ok", fencing, attempt, expires]

    def _renew(self, keys, args):
        ledger = self.hashes.get(keys[0], {})
        queue_name, group_name, message_id, owner, lease_id, fencing, ttl = args
        if not self._owns(ledger, queue_name, group_name, message_id, owner, lease_id, fencing):
            return ["stale"]
        expires = self.now_ms + int(ttl)
        ledger["expires_at_ms"] = str(expires)
        return ["ok", expires]

    def _complete(self, keys, args):
        queue_name, lease_key = keys
        expected_queue, group_name, message_id, owner, lease_id, fencing, state = args
        ledger = self.hashes.get(lease_key, {})
        if ledger.get("state") == state and self._same_generation(ledger, owner, lease_id, fencing):
            return ["complete", ledger.get("terminal_message_id", "")]
        if not self._owns(ledger, expected_queue, group_name, message_id, owner, lease_id, fencing):
            return ["stale"]
        pending = self.pending.pop((queue_name, message_id), None)
        assert pending is not None
        self.acked.append((queue_name, group_name, message_id))
        ledger.update(state=state, completed_at_ms=str(self.now_ms))
        return ["ok", ""]

    def _transition(self, keys, args):
        queue_name, lease_key, target_queue = keys
        expected_queue, group_name, message_id, owner, lease_id, fencing, state, payload = args
        ledger = self.hashes.get(lease_key, {})
        if ledger.get("state") == state and self._same_generation(ledger, owner, lease_id, fencing):
            return ["complete", ledger.get("terminal_message_id", "")]
        if not self._owns(ledger, expected_queue, group_name, message_id, owner, lease_id, fencing):
            return ["stale"]
        pending = self.pending.pop((queue_name, message_id), None)
        assert pending is not None
        next_id = self.xadd(target_queue, {"task": payload})
        self.acked.append((queue_name, group_name, message_id))
        ledger.update(
            state=state,
            completed_at_ms=str(self.now_ms),
            terminal_message_id=next_id,
        )
        return ["ok", next_id]

    def xdel(self, queue_name, message_id):
        before = len(self.streams.get(queue_name, []))
        self.streams[queue_name] = [
            entry for entry in self.streams.get(queue_name, []) if entry[0] != message_id
        ]
        return before - len(self.streams[queue_name])

    def _active(self, ledger):
        return ledger.get("state") == "active" and int(ledger.get("expires_at_ms", "0")) > self.now_ms

    def _owns(self, ledger, queue_name, group_name, message_id, owner, lease_id, fencing):
        return (
            self._active(ledger)
            and ledger.get("queue") == queue_name
            and ledger.get("group") == group_name
            and ledger.get("message_id") == message_id
            and self._same_generation(ledger, owner, lease_id, fencing)
        )

    @staticmethod
    def _same_generation(ledger, owner, lease_id, fencing):
        return (
            ledger.get("owner") == owner
            and ledger.get("lease_id") == lease_id
            and ledger.get("fencing_token") == fencing
        )
