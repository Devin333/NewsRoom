from infrastructure.storage.workers.redis_queue import RedisStreamTaskQueue


def test_redis_queue_status_uses_consumer_group_lag_when_available() -> None:
    queue = RedisStreamTaskQueue(_FakeRedis())

    payload = queue.status(["news:queue:memory"])[0].to_dict()

    assert payload["stream_length"] == 1631
    assert payload["pending_count"] == 21
    assert payload["lag"] == 0
    assert payload["entries_read"] == 1631
    assert payload["last_delivered_id"] == "1780535149927-0"
    assert payload["consumer_count"] == 1


class _FakeRedis:
    def xlen(self, queue_name):
        assert queue_name == "news:queue:memory"
        return 1631

    def xpending(self, queue_name, group_name):
        assert queue_name == "news:queue:memory"
        assert group_name == "framework-workers"
        return {
            "pending": 21,
            "consumers": [
                {
                    "name": "paper-worker-1",
                    "pending": 6,
                }
            ],
        }

    def xinfo_groups(self, queue_name):
        assert queue_name == "news:queue:memory"
        return [
            {
                "name": "framework-workers",
                "lag": 0,
                "entries-read": 1631,
                "last-delivered-id": "1780535149927-0",
            }
        ]
