"""Compatibility bridge for legacy core.framework.workers.heartbeat imports."""

from framework.workers.runtime.heartbeat import *  # noqa: F401,F403
from infrastructure.storage.workers.redis_queue import RedisWorkerRegistry  # noqa: F401
