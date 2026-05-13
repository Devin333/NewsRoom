# 08-WORKER_SCHEDULER.md

版本：v1.0-target-architecture
适用项目：News Intelligence System
模块：Worker Runtime / Scheduler / Task Queue
定位：目标态架构设计，不是 MVP 简化版
日期：2026-05-11

---

### 0.2 v1.3 Worker 与 Workflow-specific Runner

Worker 不应该直接组装 `WorkflowExecutor`。

推荐调用链：

```text
TaskHandler
  -> DailyIntelligenceRunner / TopicIntelligenceRunner
      -> WorkflowRunner
          -> WorkflowExecutor
```

这样 CLI、API、Worker、测试路径可以共享同一套 profile、artifact、storage、LLM、ToolRuntime 装配规则。


## 0. 文档定位

本文档定义 News Intelligence System 的 **最终目标态 Worker Runtime and Scheduler Layer**。

注意：

- 本文档不是第一版实现说明。
- 本文档不是 MVP 裁剪方案。
- 本文档先定义最终系统应该具备的后台任务、调度、队列、worker、重试、锁、恢复、监控和运行治理能力。
- 后续 MVP、P1、P2、生产化阶段，都应该从这个目标架构中裁剪实现范围。
- 第一版实现只是目标态 Worker/Scheduler 的一个子集，而不是反过来用第一版限制最终设计。

Worker/Scheduler Layer 是 News Intelligence System 的长期运行层。它负责把“手动运行一次 workflow”升级为“系统自动、稳定、可恢复地长期运行”。

它和其他模块的关系是：

```text
Scheduler
  -> creates Task
      -> TaskQueue
          -> WorkerPool
              -> Worker
                  -> Workflow Runtime
                      -> Artifact / Storage / Events / Metrics
```

Workflow Runtime 负责执行 workflow。
Worker/Scheduler 负责决定 workflow 什么时候执行、由谁执行、失败如何处理、如何避免重复执行、如何恢复。

---

## 0.1 v1.1 设计审查结论：Worker/Scheduler 的修订边界

本次审查不删除 scheduler、queue、worker、retry、lock、heartbeat、DLQ、backpressure、approval pause 等目标态能力，而是明确 Worker/Scheduler 是任务执行与长期运行层，不是 workflow 业务层。

需要保留：ScheduleSpec、Task、TaskQueue、Worker、WorkerPool、TaskHandler、retry/DLQ、lock/dedup、heartbeat、misfire/catch-up、backpressure、task events。

需要修正：TaskStatus 与 WorkflowRunStatus 必须分离。

```text
TaskStatus 表示后台任务投递/租约/执行状态：created / queued / leased / running / retrying / succeeded / failed / cancelled / dead_letter / waiting_for_approval / paused。
WorkflowRunStatus 表示一次 workflow 的业务执行结果：created / running / paused / waiting_for_human / retrying / succeeded / failed / blocked / cancelled / budget_exceeded。
```

需要做设计减法：

```text
quality_gate_blocked 不应默认等同 task failed。
如果 worker 成功执行 workflow，但 workflow 被 QualityGate blocked，Task 可以 succeeded，WorkflowRunStatus = blocked。
Task retry 处理基础设施失败；Step/Tool/LLM retry 处理局部失败；必须有全局 retry budget，避免嵌套重试爆炸。
```

跨文档一致性要求：Worker 只调 TaskHandler，TaskHandler 调 Workflow Runtime 或 Application Service；Worker 不直接写 report，不直接做 evidence/quality 决策。

---

## 0.2 v1.2 复查修订：Task 状态不吞并 Workflow/Quality 状态

Worker/Scheduler 的 `TaskStatus` 只表达后台任务生命周期。它不应该把 workflow 内部质量结果、report 发布状态、tool approval 结果都合并成自己的状态机。

```text
quality_gate_blocked:
  Workflow/Quality 结果，Task 可记录为 succeeded 或 failed，取决于提交任务的语义。

tool approval_required:
  ToolRuntime 结果，Task 可以进入 waiting_for_approval。

human review required:
  Workflow pause reason，Task 可以 paused / waiting_for_approval。
```

任务 retry 只处理基础设施和可恢复执行失败，不应自动 retry 质量门控失败。


## 1. 为什么需要 Worker/Scheduler

News Intelligence System 最终不是手动 CLI 工具，而是长期运行的情报生产系统。

它需要支持：

```text
每天定时生成 daily report
每周生成 weekly report
定时检查 source health
定时抓取 topic updates
定时重建 memory index
失败任务自动重试
任务积压监控
多个 worker 并发处理
避免同一个 workflow 重复运行
高风险任务等待人工审批
任务失败进入 dead letter queue
worker 崩溃后任务可恢复
```

如果没有 Worker/Scheduler，系统会停留在：

```text
用户手动运行 CLI
一次 run 完成或失败
没有自动调度
没有队列
没有并发
没有任务恢复
没有长期运行能力
```

这无法支撑长期情报系统。

---

## 2. 参考项目的通俗解释

### 2.1 Hive：像“Agent 工厂里的工人系统”

Hive 的 worker agent 概念是：每个 worker agent 是专门执行某个业务流程的 AI Agent，不是通用聊天助手。

通俗理解：

```text
Queen 负责总控
Worker 负责具体任务
每个 Worker 像一个岗位明确的员工
它们通过事件、状态和运行时协调
```

Hive roadmap 中也强调生产运行时能力：

```text
external event sources
schedulers
webhook
SSE
worker
event bus
checkpoint-based crash recovery
state management
failure recovery
observability
human oversight
```

值得借鉴：

```text
Worker 不只是执行函数，而是有业务角色
事件源可以触发 workflow
worker 运行状态要可观察
checkpoint 和 crash recovery 很重要
worker spawn / stop / resume 要被管理
parent/child event bus 可让上级看到子 worker 状态
```

不应照搬：

```text
Hive 的 worker 更偏 Agent worker
News 的 Worker 需要同时支持 deterministic workflow、source jobs、memory jobs、notification jobs
News 不应让 worker 自己改 workflow graph
```

---

### 2.2 Celery：像“成熟的后台任务工厂”

Celery 是 Python 生态里成熟的分布式任务队列。

通俗理解：

```text
主程序把任务丢进队列
Worker 从队列里拿任务
任务失败可以 retry
不同任务可以进不同队列
可以有多个 worker 并发处理
```

值得借鉴：

```text
task routing
task retry
acks / delivery info
multiple queues
worker concurrency
scheduled tasks
result backend 思路
```

不应照搬：

```text
Celery 很重
配置项多
broker/result backend 复杂
News 不一定需要直接依赖 Celery
可以吸收它的 task queue 模型
```

News 可以借鉴它的概念，而不是立刻引入 Celery 作为核心依赖。

---

### 2.3 APScheduler：像“闹钟 + 日历”

APScheduler 的核心组件是：

```text
Trigger
JobStore
Executor
Scheduler
```

通俗理解：

```text
Trigger = 什么时候响
JobStore = 记住有哪些闹钟
Executor = 闹钟响了谁去做
Scheduler = 总控
```

值得借鉴：

```text
cron trigger
interval trigger
date trigger
persistent job store
misfire handling
job executor
scheduler lifecycle
```

不应照搬：

```text
APScheduler 适合触发时间任务
但不负责复杂 workflow run state
也不负责 evidence/report artifacts
```

News 可以参考它的 Trigger / Job / JobStore / Executor 分层。

---

### 2.4 Redis Streams：像“可追踪的任务流水线”

Redis Streams 是 append-only log，并支持 consumer groups。

通俗理解：

```text
任务不是简单塞进队列然后消失，
而是写进一条日志流。
多个 worker 可以组成一个消费组，
每条消息被某个 worker 处理，
处理完需要 ACK。
如果 worker 崩溃，未 ACK 的任务还能被发现和接管。
```

值得借鉴：

```text
consumer group
pending entries
ack
claim stale tasks
stream as durable-ish queue
horizontal workers
```

不应滥用：

```text
Redis 不是长期事实库
不能把 final report 只存在 Redis
不能把 run history 只存在 Redis
```

News 适合用 Redis Streams 作为 Post-MVP 的任务队列。

---

### 2.5 Temporal：像“可以断点续跑的长期流程系统”

Temporal 的核心思想是 Durable Execution。

通俗理解：

```text
一个流程跑到一半机器崩了，
系统可以根据历史事件 replay，
从正确位置继续跑。
```

Temporal 把业务流程分成：

```text
Workflow
Activity
Worker
Event History
Replay
```

值得借鉴：

```text
durable execution
event history
replay
activity retry
workflow determinism
long-running process
worker crash recovery
```

不应照搬：

```text
Temporal 是完整平台
News 自研 Workflow Runtime 不应第一阶段依赖 Temporal
但可以学习它的 checkpoint / event history / replay 思想
```

---

### 2.6 Prefect / Dagu：像“任务状态和运行历史面板”

Prefect 和 Dagu 都强调：

```text
run status
task status
retry
logs
artifacts
history
observability
```

对 News 值得借鉴：

```text
每个 scheduled job 要有状态
每个 task 要有运行记录
失败要能重跑
日志和 artifacts 要能回看
```

---

## 3. News 最终态 Worker/Scheduler 目标

最终态 Worker/Scheduler 应该支持：

```text
manual task trigger
scheduled task trigger
event trigger
webhook trigger
source health trigger
subscription trigger
task queue
task priority
task routing
task deduplication
distributed lock
worker pool
worker lifecycle
task retry
task timeout
task cancellation
task pause/resume
dead letter queue
task heartbeat
stale task detection
worker crash recovery
run lock
queue metrics
scheduler metrics
backpressure
rate limit
multi-queue
task dependency
human approval pause
checkpoint resume
cron schedule
interval schedule
one-shot schedule
misfire policy
catch-up policy
run history
task artifact
task event
```

---

## 4. Worker/Scheduler 和其他模块的边界

### 4.1 Worker/Scheduler 负责

```text
什么时候触发任务
任务放入哪个队列
哪个 worker 执行任务
任务失败如何重试
任务是否超时
任务是否重复
任务是否需要锁
worker 是否健康
队列是否积压
```

### 4.2 Workflow Runtime 负责

```text
执行 workflow graph
运行 step
写 workflow artifacts
写 workflow events
返回 WorkflowResult
```

### 4.3 Storage Layer 负责

```text
持久化 task record
持久化 run record
保存 checkpoint
保存 worker heartbeat
保存 queue metrics
```

### 4.4 Source Pipeline 负责

```text
source fetch
source parse
source health update
```

Worker 只触发 source health check，不实现 source 逻辑。

### 4.5 API / CLI 负责

```text
提交任务
查看任务状态
取消任务
重试任务
查看 worker 状态
```

---

## 5. 触发器设计

### 5.1 Trigger 类型

```text
manual
cron
interval
date
event
webhook
source_health
subscription
retry
human_resume
```

### 5.2 ScheduleSpec

```python
class ScheduleSpec(BaseModel):
    schedule_id: str
    name: str

    trigger_type: Literal[
        "cron",
        "interval",
        "date",
        "event",
        "webhook",
        "manual"
    ]

    cron: str | None = None
    interval_seconds: int | None = None
    run_at: datetime | None = None

    timezone: str = "Asia/Tokyo"

    task_type: str
    payload_template: dict[str, Any] = Field(default_factory=dict)

    enabled: bool = True

    misfire_policy: Literal["skip", "run_once", "catch_up"] = "run_once"
    max_catchup_runs: int = 1

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 5.3 Scheduler 职责

```text
加载 schedules
计算 due time
处理 missed schedules
生成 Task
写 TaskQueue
记录 scheduler event
```

---

## 6. Task 模型

### 6.1 TaskType

```text
daily_intelligence_run
weekly_intelligence_run
topic_intelligence_run
source_health_check
source_probe
memory_index
memory_reindex
report_publish
notification_send
quality_eval
artifact_retention
```

### 6.2 TaskStatus

```text
created
queued
leased
running
retrying
succeeded
failed
cancelled
dead_letter
waiting_for_approval
paused
```

### 6.3 Task

```python
class Task(BaseModel):
    task_id: str
    task_type: str

    payload: dict[str, Any]

    status: TaskStatus = "created"

    priority: int = 100
    queue_name: str = "default"

    dedup_key: str | None = None
    run_lock_key: str | None = None

    max_retries: int = 3
    retry_count: int = 0
    retry_delay_seconds: list[int] = Field(default_factory=lambda: [30, 120, 300])

    timeout_seconds: int | None = None

    scheduled_for: datetime | None = None
    created_at: datetime
    updated_at: datetime

    started_at: datetime | None = None
    finished_at: datetime | None = None

    worker_id: str | None = None

    error_type: str | None = None
    error_message: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 6.4 TaskResult

```python
class TaskResult(BaseModel):
    task_id: str
    success: bool

    status: TaskStatus

    workflow_run_id: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)

    error_type: str | None = None
    error_message: str | None = None

    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)

    finished_at: datetime
```

---

## 7. Queue 设计

### 7.1 Queue 类型

```text
in_memory
redis_stream
database_queue
external_queue
```

### 7.2 TaskQueue Protocol

```python
class TaskQueue(Protocol):
    async def enqueue(self, task: Task) -> None: ...
    async def lease(self, worker_id: str, queue_names: list[str], timeout_seconds: int) -> Task | None: ...
    async def ack(self, task_id: str, worker_id: str) -> None: ...
    async def nack(self, task_id: str, worker_id: str, error: TaskError) -> None: ...
    async def requeue(self, task_id: str, delay_seconds: int) -> None: ...
    async def move_to_dead_letter(self, task_id: str, reason: str) -> None: ...
```

### 7.3 Redis Streams Queue

Redis Streams 目标态支持：

```text
XADD enqueue
XREADGROUP lease
XACK ack
XPENDING inspect stale tasks
XCLAIM / XAUTOCLAIM reclaim stale tasks
DLQ stream for dead letters
consumer group per queue
consumer name = worker_id
```

### 7.4 Queue 命名

```text
news:queue:daily
news:queue:weekly
news:queue:source-health
news:queue:memory
news:queue:notification
news:queue:maintenance
news:queue:dead-letter
```

---

## 8. Worker 设计

### 8.1 Worker 职责

```text
注册自己
拉取任务
执行 task handler
更新 heartbeat
处理 timeout
处理 retry
写 task result
写 events
释放 lock
```

### 8.2 Worker

```python
class Worker(BaseModel):
    worker_id: str
    worker_type: str

    queue_names: list[str]
    status: Literal["starting", "running", "stopping", "stopped", "unhealthy"]

    started_at: datetime
    last_heartbeat_at: datetime | None = None

    current_task_id: str | None = None
    processed_count: int = 0
    failed_count: int = 0

    metadata: dict[str, Any] = Field(default_factory=dict)
```

### 8.3 WorkerLoop

```text
while running:
  heartbeat
  lease task
  if no task: sleep
  execute handler
  ack on success
  retry/nack on retryable failure
  dead-letter on exhausted failure
```

### 8.4 WorkerPool

```python
class WorkerPool:
    async def start(self, worker_count: int) -> None: ...
    async def stop(self, graceful: bool = True) -> None: ...
    async def scale(self, worker_count: int) -> None: ...
```

---

## 9. Task Handler 设计

### 9.1 TaskHandler Protocol

```python
class TaskHandler(Protocol):
    task_type: str

    async def handle(self, task: Task, context: TaskExecutionContext) -> TaskResult:
        ...
```

### 9.2 Handler 类型

```text
DailyIntelligenceTaskHandler
WeeklyIntelligenceTaskHandler
TopicIntelligenceTaskHandler
SourceHealthCheckTaskHandler
MemoryIndexTaskHandler
ReportPublishTaskHandler
NotificationTaskHandler
QualityEvalTaskHandler
RetentionTaskHandler
```

### 9.3 DailyIntelligenceTaskHandler

```text
Task payload
  -> DailyIntelligenceRunRequest
  -> WorkflowExecutor.run()
  -> WorkflowResult
  -> TaskResult
```

Worker 不直接写 report，它调用 Workflow Runtime。

---

## 10. Retry / Failure / DLQ 设计

### 10.1 Retryable Errors

```text
network_timeout
provider_timeout
rate_limited
redis_connection_error
temporary_database_error
source_fetch_5xx
llm_retryable_status
```

### 10.2 Non-retryable Errors

```text
invalid_config
missing_secret
invalid_source_config
schema_validation_failed
quality_gate_blocked
all_sources_failed
budget_exceeded
```

### 10.3 RetryPolicy

```python
class TaskRetryPolicy(BaseModel):
    max_retries: int = 3
    retry_delay_seconds: list[int] = Field(default_factory=lambda: [30, 120, 300])
    backoff_strategy: Literal["fixed", "exponential", "jitter"] = "jitter"
    retryable_error_types: list[str] = Field(default_factory=list)
    non_retryable_error_types: list[str] = Field(default_factory=list)
```

### 10.4 Dead Letter Queue

任务进入 DLQ 的情况：

```text
retry exhausted
non-retryable failure
poison task
payload validation failed
manual dead-letter
```

DLQ 任务需要可查看、可重新入队、可归档。

---

## 11. Lock / Dedup 设计

### 11.1 为什么需要

避免：

```text
同一时间生成两份 daily report
同一个 topic 被重复调度
source health check 重叠执行
memory reindex 重复跑
```

### 11.2 Lock 类型

```text
run_lock
source_lock
topic_lock
publish_lock
memory_index_lock
```

### 11.3 DistributedLock

```python
class DistributedLock(Protocol):
    async def acquire(self, key: str, ttl_seconds: int, owner_id: str) -> bool: ...
    async def release(self, key: str, owner_id: str) -> None: ...
    async def extend(self, key: str, ttl_seconds: int, owner_id: str) -> bool: ...
```

### 11.4 DedupKey

```text
daily_intelligence:{date}:{language}
topic_intelligence:{topic}:{date}
source_health:{source_id}:{window}
memory_index:{run_id}
```

---

## 12. Heartbeat / Crash Recovery

### 12.1 Worker Heartbeat

```text
worker_id
status
current_task_id
last_heartbeat_at
processed_count
failed_count
```

### 12.2 Stale Worker Detection

```text
if now - last_heartbeat_at > threshold:
  mark worker unhealthy
  inspect current task
  reclaim or retry task
```

### 12.3 Task Lease

Task lease 防止 worker 崩溃后任务永久卡住：

```text
lease task for N seconds
worker heartbeat extends lease
if lease expired:
  another worker can reclaim
```

### 12.4 Workflow Checkpoint

如果 task 正在执行 workflow：

```text
Workflow Runtime writes checkpoint
Worker crash
New worker resumes from checkpoint if supported
Otherwise rerun idempotent task
```

---

## 13. Backpressure / Rate Limit

### 13.1 Backpressure Signals

```text
queue length too high
LLM rate limit too high
source fetch failure spike
database latency high
vector indexing lag
worker CPU/memory high
```

### 13.2 Actions

```text
pause scheduler
reduce worker concurrency
delay low-priority tasks
drop catch-up runs
disable non-critical jobs
send operator alert
```

### 13.3 Rate Limit Scope

```text
provider-level LLM rate limit
domain-level source fetch rate limit
queue-level concurrency
task-type concurrency
agent-level budget
```

---

## 14. Scheduler Misfire / Catch-up

### 14.1 Misfire 场景

```text
scheduler downtime
server sleep
deployment restart
database unavailable
```

### 14.2 Misfire Policy

```text
skip
run_once
catch_up
```

### 14.3 News 建议

```text
daily report:
  run_once

source health:
  skip old missed runs

memory indexing:
  catch_up with max limit

notification:
  skip expired
```

---

## 15. Human Approval / Pause

某些任务需要人工确认：

```text
publish_report
send_notification
large_cost_run
dangerous_tool_execution
manual source addition
```

### 15.1 Approval Flow

```text
task waiting_for_approval
checkpoint created
approval request artifact written
human approves/rejects/modifies
task resumes or fails
```

### 15.2 Approval Task State

```text
waiting_for_approval
approval_granted
approval_rejected
approval_expired
```

---

## 16. Events / Metrics

### 16.1 Worker Events

```text
task_enqueued
task_leased
task_started
task_succeeded
task_failed
task_retry_scheduled
task_dead_lettered
task_cancelled
task_requeued
worker_started
worker_heartbeat
worker_unhealthy
worker_stopped
scheduler_started
schedule_due
schedule_misfired
schedule_enqueued_task
lock_acquired
lock_released
lock_failed
```

### 16.2 WorkerMetrics

```python
class WorkerMetrics(BaseModel):
    tasks_enqueued: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    tasks_retried: int = 0
    tasks_dead_lettered: int = 0

    queue_depth: dict[str, int] = Field(default_factory=dict)
    avg_task_latency_ms: dict[str, float] = Field(default_factory=dict)

    active_workers: int = 0
    unhealthy_workers: int = 0

    lock_failures: int = 0
```

---

## 17. Data Models for Persistence

### 17.1 TaskRecord

```python
class TaskRecord(BaseModel):
    task_id: str
    task_type: str
    queue_name: str
    status: str

    payload_json: dict[str, Any]

    priority: int
    dedup_key: str | None = None
    run_lock_key: str | None = None

    retry_count: int
    max_retries: int

    worker_id: str | None = None

    scheduled_for: datetime | None = None
    leased_until: datetime | None = None

    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    error_type: str | None = None
    error_message: str | None = None

    workflow_run_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)
```

### 17.2 ScheduleRecord

```python
class ScheduleRecord(BaseModel):
    schedule_id: str
    name: str
    trigger_type: str
    trigger_config_json: dict[str, Any]

    task_type: str
    payload_template_json: dict[str, Any]

    enabled: bool
    timezone: str

    last_run_at: datetime | None = None
    next_run_at: datetime | None = None

    misfire_policy: str = "run_once"
    metadata_json: dict[str, Any] = Field(default_factory=dict)
```

### 17.3 WorkerRecord

```python
class WorkerRecord(BaseModel):
    worker_id: str
    worker_type: str
    queue_names: list[str]

    status: str

    started_at: datetime
    last_heartbeat_at: datetime | None = None

    current_task_id: str | None = None

    processed_count: int = 0
    failed_count: int = 0

    metadata_json: dict[str, Any] = Field(default_factory=dict)
```

---

## 18. Security / Safety

### 18.1 Task Payload Redaction

Task payload 不能包含：

```text
API key
Authorization header
Cookie
database password
private token
```

只能包含 secret name / config ref。

### 18.2 Dangerous Task Policy

需要 approval：

```text
publish_report
send_external_notification
run_expensive_workflow
delete_artifacts
manual_database_operation
```

### 18.3 Queue Isolation

高风险任务单独队列：

```text
news:queue:publish
news:queue:maintenance
news:queue:admin
```

避免和普通 daily run 混在一起。

---

## 19. Error Taxonomy

```text
task_payload_invalid
task_handler_not_found
task_timeout
task_cancelled
task_retry_exhausted
task_lock_failed
task_duplicate
queue_connection_failed
queue_ack_failed
worker_heartbeat_lost
scheduler_misfire
schedule_invalid
approval_required
approval_rejected
dead_lettered
workflow_execution_failed
checkpoint_resume_failed
```

每个错误标记：

```text
retryable
operator_action_required
workflow_blocking
dead_letter_candidate
```

---

## 20. 目标态目录结构建议

```text
workers/
  __init__.py

  specs/
    task.py
    schedule.py
    retry_policy.py
    queue_policy.py

  scheduler/
    scheduler.py
    trigger.py
    cron.py
    interval.py
    job_store.py
    misfire.py

  queue/
    base.py
    in_memory.py
    redis_stream.py
    database_queue.py
    dead_letter.py

  runtime/
    worker.py
    worker_pool.py
    lifecycle.py
    heartbeat.py
    lease.py
    cancellation.py

  handlers/
    base.py
    daily_intelligence.py
    weekly_intelligence.py
    topic_intelligence.py
    source_health.py
    memory_index.py
    report_publish.py
    notification.py
    quality_eval.py
    retention.py

  locks/
    distributed_lock.py
    redis_lock.py
    run_lock.py

  approval/
    approval_request.py
    approval_store.py
    approval_handler.py

  stores/
    task_store.py
    schedule_store.py
    worker_store.py

  events/
    event_models.py
    event_emitter.py

  metrics/
    models.py
    collector.py

  errors/
    error_types.py
    exceptions.py
```

---

## 21. 和 Hive 的最终取舍

### 21.1 借鉴 Hive

```text
worker agent 概念
external event sources
scheduler / webhook / SSE 触发思路
EventBus
checkpoint-based crash recovery
state management
worker lifecycle
human oversight
worker spawn / stop / resume
parent can observe child worker events
```

### 21.2 不照搬 Hive

```text
不把所有 worker 都设计成 LLM Agent
不让 worker 自己改 workflow graph
不把 deterministic jobs 包装成 Agent
不把 queue state 只放内存
不让 scheduled task 绕过 Workflow Runtime
不让 publish/notification 自动执行无审批
```

### 21.3 News 自己的目标态

```text
Worker/Scheduler 是长期运行层
Workflow Runtime 是执行层
TaskQueue 是任务分发层
Redis Streams 是 Post-MVP 队列候选
PostgreSQL 保存 task/run 历史
Artifact Store 保存可回放材料
Human approval 处理高风险任务
Run lock 防止重复报告
Dead letter queue 是必须能力
```

---

## 22. 分阶段裁剪原则

本文档定义最终态。后续第一阶段可以只实现子集，但不能破坏最终架构。

裁剪原则：

```text
目标态先定完整边界
第一阶段只取最小运行链路
命名、接口、目录和最终态保持兼容
后续只是补 Redis、scheduler、DLQ、heartbeat、approval
不要推翻 Worker/Scheduler Layer
```

例如第一阶段可以只实现：

```text
Task
TaskResult
TaskHandler
InMemoryTaskQueue
Worker
WorkerPool
DailyIntelligenceTaskHandler
ManualTaskTrigger
```

后续再补：

```text
ScheduleSpec
Scheduler
RedisStreamQueue
DistributedLock
DeadLetterQueue
Heartbeat
Approval
TaskStore
```

---

## 23. 最终态验收标准

Worker/Scheduler Layer 最终完成时，应该满足：

```text
支持 manual trigger
支持 cron schedule
支持 interval schedule
支持 event trigger
支持 task queue
支持 Redis Streams queue
支持 worker pool
支持 task retry
支持 task timeout
支持 dead letter queue
支持 distributed lock
支持 dedup key
支持 heartbeat
支持 stale task reclaim
支持 scheduler misfire policy
支持 approval pause/resume
支持 task cancellation
支持 task store
支持 schedule store
支持 worker store
支持 queue metrics
支持 worker metrics
支持 task events
支持 secure payload redaction
支持 high-risk queue isolation
```

---

## 24. 总结

News Worker/Scheduler 的最终目标不是一个简单 while loop，也不是只用 cron 跑脚本。

它应该是：

```text
面向情报生产的长期任务运行与自动化调度系统
```

它吸收 Hive 的 worker agent、event sources、EventBus、checkpoint recovery 和 human oversight 思路，也参考 Celery 的 task queue / retry / routing、APScheduler 的 trigger / job store / executor / scheduler、Redis Streams 的 consumer group / ack / pending task、Temporal 的 durable execution / replay，以及 Prefect / Dagu 的 run history 和 observability。

但 News 必须强化自己的业务约束：

```text
scheduled intelligence workflows
run lock
source health jobs
memory indexing jobs
quality eval jobs
publish approval
dead letter queue
artifact-backed replay
Workflow Runtime 作为唯一 workflow 执行入口
```

后续 MVP、第一版、第二版都应该从这个最终态目标中裁剪实现，而不是用第一版的简单实现反向定义 Worker/Scheduler 的上限。

---
# 本版保留说明

以上内容为原目标态文档主体内容，已完整保留。下面追加的是 v2.0 设计书级补强，用于把原目标态说明转化为更可开发、可验收、可维护的工程设计书。

---
# v2.0 设计书级补强：Worker / Scheduler 工程化设计

## A. 本模块最终职责

Worker/Scheduler 负责长期运行、任务投递、队列、租约、重试、锁、心跳、死信、调度和恢复。

它不负责：

```text
workflow graph 执行细节
report 写作
evidence/quality 判断
source 解析
API response view model
```

## B. 调用链

```text
Scheduler
  -> TaskQueue.enqueue()
      -> Worker
          -> TaskHandler
              -> DailyIntelligenceRunner / TopicIntelligenceRunner
                  -> WorkflowRunner
                      -> WorkflowExecutor
```

Worker 不直接组装 WorkflowExecutor。

## C. TaskStatus

```text
created
queued
leased
running
retrying
succeeded
failed
cancelled
dead_letter
waiting_for_approval
paused
```

WorkflowRunStatus 不能混进 TaskStatus。

## D. Task 模型

```python
class Task(BaseModel):
    task_id: str
    task_type: str
    status: TaskStatus

    payload: dict[str, Any]
    priority: int = 100

    dedup_key: str | None = None
    lock_key: str | None = None

    run_id: str | None = None
    attempts: int = 0
    max_attempts: int = 3

    scheduled_at: datetime | None = None
    leased_until: datetime | None = None
    created_at: datetime
    updated_at: datetime
```

## E. Retry 边界

```text
Task retry:
  基础设施失败、worker crash、可恢复 IO。

Workflow step retry:
  单 step 的局部失败。

LLM retry:
  provider 429/timeout。

Tool retry:
  工具自身可恢复错误。

Quality blocked:
  不自动 retry task。
```

## F. 实现顺序

```text
P7.1 InMemoryTaskQueue
P7.2 TaskHandler
P7.3 Worker 单进程
P7.4 PostgreSQL TaskStore
P7.5 Redis Streams
P7.6 Scheduler cron/interval
P7.7 DLQ/heartbeat/stale claim
```

## G. 代码组织建议

```text
worker/tasks.py
worker/runner.py
worker/scheduler.py
```

tasks.py 放模型和 Queue 协议。
runner.py 放 Worker/WorkerPool。
scheduler.py 放 ScheduleSpec 和 Scheduler。

## H. 测试矩阵

```text
test_enqueue_and_consume_task
test_task_retry_infrastructure_failure
test_quality_blocked_not_task_failed
test_dedup_key_prevents_duplicate
test_worker_heartbeat
test_stale_task_claim
test_schedule_next_run
test_dead_letter_after_max_attempts
```

## I. 验收清单

```text
[ ] Worker 只调 TaskHandler。
[ ] TaskHandler 调 Runner/Service。
[ ] TaskStatus 与 WorkflowRunStatus 分离。
[ ] retry 有预算。
[ ] daily run 有 dedup/lock。
[ ] worker crash 后任务可恢复。
```

## J. 当前代码进度映射：v2.1-current-code-aligned

截至 2026-05-14，仓库中的 Worker/Scheduler 已经具备后台任务模型、in-memory queue、Redis Stream queue、worker loop、task handler、schedule store、cron evaluator、heartbeat 和 approval store 基础。后续开发应继续基于 `core/framework/workers` 收口，不应让 Worker 直接拼装 `WorkflowExecutor` 或吞并 Workflow/Quality 状态。

| 能力 | 当前状态 | 对应代码 | 说明 |
|---|---|---|---|
| Task model | 已实现 | `core/framework/workers/models.py` | 支持 task_id、task_type、payload、status、priority、dedup、lock、run_id、attempts、lease、trace |
| TaskStatus | 已实现 | `core/framework/workers/models.py` | 已区分 queued/running/retrying/succeeded/failed/cancelled/dead_letter/waiting_for_approval/paused/timeout 等 worker 生命周期 |
| TaskResult | 已实现 | `core/framework/workers/models.py` | 支持 success/failure/error/run_id/output serialization |
| RetryPolicy | 已实现 | `core/framework/workers/models.py` | 支持 max_attempts 和 retry delay 语义 |
| TaskEvent / TaskRecord | 已实现 | `core/framework/workers/models.py` | 任务事件与 record 序列化基础已落地 |
| WorkerRecord / WorkerMetrics | 已实现 | `core/framework/workers/models.py` | worker heartbeat/metrics 结构已落地 |
| InMemoryTaskQueue | 已实现 | `core/framework/workers/in_memory.py` | 支持 enqueue/lease/ack/fail/cancel/DLQ/requeue |
| Redis Streams queue | 已实现 | `core/framework/workers/redis_queue.py` | 保留 consumer group、ack、pending reclaim 行为 |
| WorkerLoop | 已实现 | `core/framework/workers/worker_loop.py` | 单进程 worker loop 基础已落地 |
| TaskHandler | 已实现 | `core/framework/workers/handlers.py` | handler 调用 workflow-specific runner / application service，不直接写业务报告 |
| Scheduler | 已实现 | `core/framework/workers/scheduler.py` | 支持 deterministic cron evaluation、misfire behavior、schedule dispatch |
| Schedule store | 已实现 | `core/framework/workers/schedule_store.py` | 本地 schedule persistence 基础 |
| Heartbeat | 已实现 | `core/framework/workers/heartbeat.py` | worker heartbeat/stale status 基础 |
| Approval store | 已实现 | `core/framework/workers/approval.py` | Tool approval / worker waiting 状态可复用的 approval request store |
| Tests | 较完整 | `tests/core/framework/workers/*` | 覆盖 queue、scheduler、heartbeat、approval、worker loop、models |

总体判断：

```text
Worker/Scheduler 已经达到 P1 中后段：
  Task/Queue/WorkerLoop/Scheduler/Heartbeat/Approval 基础完整；
  当前缺口主要是生产级 idempotency、Redis DLQ/reclaim 深化、approval resume 端到端、queue metrics、misfire/catch-up 策略和状态语义跨模块测试。
```

## K. 已完成、雏形、暂不做

### K.1 已完成能力

```text
TaskStatus 与 WorkflowStatus 分离
Task / TaskResult / RetryPolicy / TaskEvent / TaskRecord
WorkerRecord / WorkerMetrics
InMemoryTaskQueue enqueue / lease / ack / fail / cancel / DLQ / requeue
Redis Streams queue ack / pending behavior
WorkerLoop
TaskHandler
simple cron schedule evaluation
schedule store
heartbeat
approval store
focused worker tests
```

### K.2 雏形可用能力

```text
Redis production queue:
  consumer group、ack、pending 行为已保留；
  DLQ retry、lease extension、backpressure、metrics 还需继续增强。

Approval resume:
  approval store 和 waiting status 已有；
  Worker -> Workflow resume -> Interface approval 的端到端闭环仍需跨模块测试。

Schedule misfire/catch-up:
  simple cron evaluator 已有；
  大规模 catch-up、错过窗口策略、timezone profile 仍需生产化。

Task idempotency:
  dedup_key / lock_key 字段已落地；
  分布式锁、幂等结果复用和 run-level lock 还需继续收口。
```

### K.3 暂不做能力

```text
不让 Worker 直接组装 WorkflowExecutor。
不把 Quality blocked 自动等同 Task failed。
不让 TaskStatus 承载 ReportStatus / WorkflowStatus / ToolStatus。
不在 Worker 内实现 source/evidence/report 业务逻辑。
不引入大型调度框架替代现有 Scheduler，除非当前接口稳定后有明确收益。
```

## L. 后续落地建议

优先级：

```text
P1:
  归档 worker-scheduler-final-target-closure。
  为 TaskStatus / WorkflowStatus / ReportStatus / ToolApproval 增加跨模块状态语义测试。
  保持 Worker -> TaskHandler -> workflow-specific Runner 的调用链。

P2:
  完成 Redis stale reclaim / DLQ retry / queue metrics。
  补 approval resume 端到端测试。
  增加 idempotency key / lock key 行为测试。

P3:
  schedule misfire/catch-up 生产策略。
  worker pool/backpressure。
  long-running health and source maintenance jobs。
```

## M. 本轮验证记录

本轮针对 final target closure 补跑：

```text
pytest tests/core/framework/workers -q
  40 passed, 2 warnings

pytest -q
  1142 passed, 2 warnings

openspec validate worker-scheduler-final-target-closure --strict
openspec validate --all --strict
```
