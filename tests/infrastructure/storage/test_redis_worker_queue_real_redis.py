from __future__ import annotations

import os
from uuid import uuid4

import pytest

from framework.workers import StaleTaskLeaseError, Task
from framework.harness.control_plane.errors import HarnessValidationError
from framework.harness.graph.versioning import (
    GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
    HARNESS_CONDITION_POLICY_VERSION,
    HARNESS_GRAPH_ONLY_COMPILER_VERSION,
)
from framework.harness.task_plan import (
    GRAPH_ONLY_TASK_INSTANCE_SCHEMA,
    GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA,
    TaskBudget,
    TaskInstance,
    materialize_queue_task,
)
from infrastructure.storage.workers.redis_queue import RedisStreamTaskQueue
from infrastructure.storage.workers.task_plan_queue import (
    RedisTaskPlanQueueReadAdapter,
)


REDIS_URL = os.environ.get("NEWS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(
    not REDIS_URL,
    reason="set NEWS_TEST_REDIS_URL to run real Redis worker lease coverage",
)


def test_real_redis_active_renewal_reclaim_and_late_completion() -> None:
    import redis

    client = redis.from_url(REDIS_URL, decode_responses=True)
    suffix = uuid4().hex
    queue_name = f"news:test:worker:{suffix}"
    queue = RedisStreamTaskQueue(
        client,
        group_name=f"news-test-workers-{suffix}",
        dead_letter_queue_name=f"{queue_name}:dlq",
        lease_ttl_ms=250,
        lease_key_prefix=f"news:test:worker-leases:{suffix}",
    )
    try:
        queue.enqueue(Task(task_type="test", payload={}, queue_name=queue_name, task_id=suffix))
        first = queue.lease_one("worker-a", [queue_name], block_ms=1)
        assert first is not None
        queue.renew(first)
        assert queue.reclaim_stale_one("worker-b", [queue_name], min_idle_ms=0) is None

        import time

        time.sleep(0.3)
        second = queue.reclaim_stale_one("worker-b", [queue_name], min_idle_ms=0)
        assert second is not None
        assert second.attempt == 2
        assert second.fencing_token == 2
        with pytest.raises(StaleTaskLeaseError):
            queue.ack(first)
        assert queue.ack(second) == 1
    finally:
        for key in client.scan_iter(match=f"*{suffix}*"):
            client.delete(key)


def test_real_redis_task_plan_readback_tracks_group_delivery_state() -> None:
    import redis

    client = redis.from_url(REDIS_URL, decode_responses=True)
    suffix = uuid4().hex
    queue_name = f"news:test:task-plan:{suffix}"
    group_name = f"news-test-task-plan-workers-{suffix}"
    queue = RedisStreamTaskQueue(
        client,
        group_name=group_name,
        dead_letter_queue_name=f"{queue_name}:dlq",
        lease_key_prefix=f"news:test:task-plan-leases:{suffix}",
    )
    reader = RedisTaskPlanQueueReadAdapter(client, group_name=group_name)
    checksum = f"sha256:{'0' * 64}"
    instance = TaskInstance(
        run_id=f"run-{suffix}",
        graph_id="test.task-plan.graph",
        graph_version="1",
        graph_ref="test.task-plan.graph@1",
        graph_schema_version=GRAPH_ONLY_NORMALIZED_HARNESS_GRAPH_SCHEMA,
        compiler_version=HARNESS_GRAPH_ONLY_COMPILER_VERSION,
        condition_policy_version=HARNESS_CONDITION_POLICY_VERSION,
        graph_checksum=checksum,
        stage_binding_checksum=checksum,
        stage_identity_schema=GRAPH_ONLY_TASK_PLAN_STAGE_IDENTITY_SCHEMA,
        stage_identity_checksum=checksum,
        stage_id="test-stage",
        plan_id=f"plan-{suffix}",
        plan_version=1,
        plan_checksum=checksum,
        task_id="test-task",
        task_definition_checksum=checksum,
        task_instance_id=f"task-instance-{suffix}",
        attempt=1,
        worker_ref="test.worker@1",
        idempotency_key=f"task-instance-{suffix}",
        fencing_token=f"fence-{suffix}",
        budget_snapshot=TaskBudget(),
        schema_version=GRAPH_ONLY_TASK_INSTANCE_SCHEMA,
    )
    try:
        queue.enqueue(materialize_queue_task(instance, queue_name=queue_name))

        readbacks = reader.read_task_plan_queue(
            queue_name=queue_name,
            task_instance_ids=(instance.task_instance_id,),
        )
        assert len(readbacks) == 1
        assert readbacks[0].projection.task_instance == instance

        leased = queue.lease_one("worker-a", [queue_name], block_ms=1)
        assert leased is not None
        with pytest.raises(HarnessValidationError) as pending_error:
            reader.read_task_plan_queue(
                queue_name=queue_name,
                task_instance_ids=(instance.task_instance_id,),
            )
        assert (
            pending_error.value.code
            == "task_plan_queue_delivery_state_mismatch"
        )

        assert queue.ack(leased) == 1
        with pytest.raises(HarnessValidationError) as acknowledged_error:
            reader.read_task_plan_queue(
                queue_name=queue_name,
                task_instance_ids=(instance.task_instance_id,),
            )
        assert (
            acknowledged_error.value.code
            == "task_plan_queue_delivery_state_mismatch"
        )
    finally:
        for key in client.scan_iter(match=f"*{suffix}*"):
            client.delete(key)
