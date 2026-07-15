# 阶段 19：Durable Event Runtime 生产化硬化 PRD

> Document status: READY_FOR_IMPLEMENTATION
>
> Implementation status: IN_PROGRESS
>
> Version: v1.0
>
> Priority: P1（生产化阻断）
>
> Scope: `framework/events`、Harness/Workflow durable event 写入与 replay、storage event adapters、run event inspection/export
>
> Source audit: `framework/events` 初审基线 `45e7b4bf`；在 `9fddf4ec` 复核事件核心文件无变化，并将期间 artifact/run-inspection/storage 路径硬化纳入边界与集成约束
>
> OpenSpec change: `durable-event-runtime`
>
> Depends on: 阶段 4 的 Harness trace/checkpoint/replay 语义；不依赖 Kafka、Temporal 或 Dapr
>
> Last updated: 2026-07-14

> 状态说明：`READY_FOR_IMPLEMENTATION` 表示目标、非目标、架构决策、迁移、验收和 OpenSpec 任务已经收敛；`NOT_STARTED` 表示本阶段尚未修改生产代码、执行数据库迁移或完成验收。实施状态只允许按 `NOT_STARTED -> IN_PROGRESS -> IMPLEMENTED` 推进；文档被替代时标记 `SUPERSEDED`。

## 0. 一句话结论

NewsRoom 当前已经有 Event、EventEnvelope、Recorder、InMemoryEventBus、Local/PostgreSQL event store、Harness event log 和 run event 查询等有用资产，但这些资产尚未形成一个可靠运行时：**事实模型不唯一，事件先后顺序不是 durable 保证，subscriber 失败会产生部分投递，原始 JSONL 可能泄漏 secret，replay 会重新触发副作用，schema_version 只是标签，Workflow 仍在运行结束后从 JSONL 二次索引。**

本阶段必须把事件能力收敛为：

```text
一个 canonical durable event
+ 一个 per-stream authoritative sequence
+ 一个 atomic event/outbox transaction
+ 每个 consumer 独立的 inbox/checkpoint/retry/DLQ
+ 默认无副作用的 deterministic replay
+ 与业务身份分离的 OpenTelemetry/W3C trace
```

本阶段不承诺全局有序，也不承诺外部副作用 exactly-once。生产契约明确为：**durable append + at-least-once delivery + idempotent business effect + deterministic replay**。

---

## 1. 背景、模块定位与审查依据

### 1.1 `framework/events` 在 NewsRoom 中的职责

事件能力不是普通日志工具。它支撑：

- Harness 每次 `PLAN -> EXECUTE -> VERIFY` 相位转移的 durable transcript；
- Workflow run、step、edge、checkpoint、artifact 等运行事实；
- Agent、Tool、Memory、worker 等组件的关联诊断；
- run inspection、API、CLI、MCP 和 SSE 事件查询；
- checkpoint 恢复、历史 review、state rebuild 和 deterministic replay；
- 后续 operator 对 retry、DLQ、quarantine 和 redelivery 的受控操作。

按照仓库架构护栏，Harness 是唯一流程控制者。Event Runtime 只能记录事实、可靠投递和提供 replay 输入，不能反向决定 workflow routing、quality pass/fail、memory write、tool authorization 或 publication。

### 1.2 已验证缺陷

| ID | 级别 | 当前缺陷 | live 证据 | 实际后果 |
| --- | --- | --- | --- | --- |
| E1 | P1 | Bus 同步串行且 fail-fast | `framework/events/bus.py:25-38` | 前两个 consumer 已产生副作用、第三个未执行，但调用方收到失败；重试可能重复副作用 |
| E2 | P1 | 原始 workflow `events.jsonl` 无统一脱敏 | `framework/events/recorder.py:192-198`；`framework/workflow/runtime/outcome_finalizer.py:88-89` | payload 中 token/secret 可先明文落盘，后续索引脱敏无法消除原始泄漏 |
| E3 | P2 | `frozen=True` 只有浅冻结 | `framework/events/event.py:26-49` | payload 顶层仍可改，嵌套对象与调用方共享，同一事件内容可随时间漂移 |
| E4 | P1 | Event 与 Envelope 有两个上下文真相源 | `event.py:33-40`；`envelope.py:17-41` | 同一个 event 可同时属于两个 trace/run，消费者读不同层得到不同结论 |
| E5 | P1 | Recorder 维护 `_records` 与 `_envelopes` 双账 | `recorder.py:141-199` | 查询数量、返回类型和最终 JSONL 集合不一致 |
| E6 | P1 | sequence 和 replay 不是系统保证 | `ordering.py:9-29`；`replay.py:11-24` | Bus 不分配 durable sequence；replay 遵循传入顺序并重复执行 subscriber |
| E7 | P2 | schema version 只是一段字符串 | `event.py:68-84` 等 `from_dict()` | 拼错事件名或 `unknown.v999` 仍进入运行时，无 validator/upcaster/quarantine |
| E8 | P1 | Trace redaction 与传播不完整 | `trace.py:15-23,96-112,200-232` | key substring 有误报/漏报；原对象保留 secret；部分 Agent/Tool/Artifact ID 未传播 |
| E9 | P2 | 缺少历史时间时填当前时间 | `event.py:69-83`；framework recorder/TraceEvent 同类路径 | 坏历史记录被伪装成刚发生，破坏排序、窗口过滤和审计 |
| E10 | P1 | Event store 存在，但不是 live Workflow source of truth | `runner.py:149-169,533-570,608-737` | Workflow 结束后才读 JSONL 二次索引；崩溃窗口内事件未进入 storage store |
| E11 | P1 | PostgreSQL sequence 分配存在并发竞态 | `infrastructure/storage/postgres/event_store.py:25-60,110-119` | `COUNT(*) -> INSERT` 的并发 writer 可抢到相同 offset；duplicate id 还可能返回并未插入的预分配 offset |
| E12 | P2 | Harness 默认 durable sink 未收敛 | `framework/harness/ports.py`、`control_plane/harness.py` | Harness typed event/event log 与 Workflow event runtime 继续分裂，phase transition 可能只在内存路径存在 |

### 1.3 已执行反例复现

对当前 live modules 的无副作用临时复现得到：

```text
immutability:
  构造 Event 后修改原始 nested dict，Event.payload 同步变化
  直接 event.payload["added_after_creation"] = True 成功

trace conflict:
  event.trace_id    = trace-A
  envelope.trace_id = trace-B
  两个值均被保留

partial delivery:
  consumer first  成功
  consumer second 抛异常
  consumer third  未执行
  bus.published_count == 1
  调用方收到 EventSubscriberError

duplicate replay:
  同一个 event_id replay 两次
  side-effect subscriber 收到两次
```

实施前必须把这些临时反例全部转为 committed regression tests。聊天中的复现输出不能替代可重复测试。

### 1.4 当前 happy-path 验证基线

目标 event tests 在审查时全部通过：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\framework\events `
  tests\framework\contracts\test_event_trace_contract.py `
  tests\architecture\test_framework_events_boundary.py -q

12 passed
```

这证明现有 happy path 可用，不代表上述对抗性场景已经安全。本 PRD 不允许以“原测试继续通过”作为完成条件。

### 1.5 已有能力不是零，但仍然碎片化

当前仓库已经存在：

- `infrastructure/storage/events/LocalJsonEventStore`；
- `infrastructure/storage/postgres/PostgresEventStore` 和 `workflow_events` 表；
- `event_store_from_env()`；
- Harness event log、transcript、checkpoint 和 replay 模型；
- Workflow run event API/CLI/MCP 查询；
- worker queue 的 ack/retry/DLQ；
- RAG OpenTelemetry 能力。

本阶段不是忽略这些资产重造 Kafka，而是收敛它们的职责。Worker queue 的投递语义只能作为实现先例，不能被当作 `framework/events` 已经具备可靠投递的证据。

---

## 2. 当前真实运行路径与问题边界

### 2.1 当前 Workflow 写入路径

```text
WorkflowRunner / WorkflowExecutor
        |
        v
build_execution_context()
  -> EventRecorder(run_id, event_bus)
  -> TraceContext.root(...)
        |
        v
execution_loop / step_invoker / runtime_event_bridge
  -> recorder.emit(...)
        |
        +--> _records.append(EventRecord)              [E5]
        +--> _envelopes.append(EventEnvelope)          [E4/E5]
        +--> InMemoryEventBus.publish()                [E1]
        |
        v
outcome_finalizer.write_jsonl(events.jsonl)            [E2]
        |
        v
WorkflowRunner._persist_storage_indexes()
  -> 再次读取 events.jsonl
  -> 再次脱敏
  -> runner-local WorkflowEventRecord/store/factory    [E10]
  -> _records/events/{run_id}.jsonl
```

问题不是单独哪个函数写错，而是 source of truth 在运行生命周期中发生变化：

```text
运行中：Recorder 两个 list
运行结束：run/events.jsonl
索引后：另一个 event store
在线查询：又可能重新读 run/events.jsonl
```

### 2.2 当前 Harness 路径

```text
HarnessControlPlane
  -> HarnessEvent
  -> HarnessEventPort.record()
  -> 默认 InMemoryHarnessEventPort
  -> HarnessEventLogEntry / transcript / replay 自有模型
```

阶段 4 已要求每个 Harness phase transition durable。本阶段必须保留阶段 4 的控制语义，但把 typed `HarnessEvent` 适配到统一 durable boundary；不得让旧 Workflow runtime 接管 Harness 状态机，也不得让 Event Runtime 决定 Harness 路由。

### 2.3 当前模型重复

| 当前模型 | 当前用途 | 本阶段处置 |
| --- | --- | --- |
| `framework.events.Event` | 业务/诊断事件草稿 | 迁移为 typed draft/兼容 facade；不再持有重复 durable context |
| `EventEnvelope` | event_id、sequence、correlation | 迁移期 reader；最终由 canonical `StoredEvent` 取代 |
| framework `EventRecord` | Workflow emit/JSONL | 删除；不得继续与 Envelope 双写 |
| storage `EventRecord` | Local/Postgres store | 迁移为 canonical storage projection 或 adapter |
| runner-local `WorkflowEventRecord` | post-run 索引 | 删除 |
| inspection `WorkflowEventRecord` | 对外 read model | 保留为 projection DTO，但不得成为 source of truth |
| `HarnessEvent` | Harness typed transition | 保留 typed domain contract，经 adapter 进入 durable stream |
| `HarnessEventLogEntry` | Harness history/replay | 迁移为 canonical event projection；不能继续拥有独立 memory-only 主路径 |
| Agent/Tool/Memory typed events | 子系统诊断/领域语义 | 可保留 typed classes，在 durable boundary 统一转换 |

原则是：**不粗暴删除领域 typed event；只统一 durable boundary 和事实身份。**

---

## 3. 与已有 PRD、OpenSpec 和行业方案的关系

### 3.1 与阶段 4 的关系

[阶段 4：Trace / Checkpoint / Replay](04-trace-checkpoint-replay.md) 已经固定：

- event/transcript append-only；
- 大 payload 使用 artifact ref；但当前普通 artifact store 不具备敏感数据 ACL/租户授权/加密边界，阶段 19 对 protected content 采用下文 fail-closed 约束；
- checkpoint 有 checksum；
- replay 不重新调用 LLM、真实 retrieval、MCP、memory write 或外部副作用；
- Harness phase transition 必须能复盘。

阶段 19 不改变这些要求。它补齐阶段 4 没有固定的生产契约：统一事件模型、durable append、per-stream sequence、schema evolution、outbox/inbox、subscriber isolation、retry/DLQ、storage backend、trace propagation 与安全导出。

### 3.2 与 `workflow-storage-indexing` 的关系

现有主规格要求“Workflow 写出 `events.jsonl` 后，event store 包含相同事件”。本阶段明确修改为：

```text
旧：events.jsonl -> post-run index -> event store
新：durable event store -> redacted events.jsonl projection
```

对应 delta spec：

`openspec/changes/durable-event-runtime/specs/workflow-storage-indexing/spec.md`

### 3.3 外部标准只作为设计依据

| 参考 | 借鉴内容 | 不把它误认为 |
| --- | --- | --- |
| CloudEvents | event id/source/type/subject/data schema 与 context/data 分离 | durable broker、顺序、retry 或 replay |
| OpenTelemetry + W3C | trace/span、propagation、Resource、InstrumentationScope、Span Links | 业务事实账本、授权或幂等系统 |
| Kafka | append-only stream、partition 内顺序、offset/checkpoint、idempotence | 全局总序或任意外部系统 exactly-once |
| Temporal | durable history、deterministic command replay、activity 幂等和版本化 | activity 物理执行一次 |
| Dapr | ACK/RETRY/DROP、at-least-once、DLQ、outbox | consumer 自动 exactly-once |
| Event Sourcing | 从事件重建状态、snapshot | 普通 event transcript 自动成为全域 Event Sourcing |

对应官方参考清单：

- [CloudEvents specification](https://github.com/cloudevents/spec)
- [W3C Trace Context](https://www.w3.org/TR/trace-context/) 与 [OpenTelemetry specification](https://opentelemetry.io/docs/specs/)
- [Kafka design: message delivery semantics](https://kafka.apache.org/documentation/#semantics)
- [Temporal encyclopedia: event history and replay](https://docs.temporal.io/encyclopedia/event-history/event-history-and-event-replay)
- [Dapr pub/sub resiliency and dead-letter topics](https://docs.dapr.io/developing-applications/building-blocks/pubsub/pubsub-deadletter/)

本阶段第一版使用 SQLite/PostgreSQL，不引入新的 broker。

---

## 4. 产品目标与成功指标

### 4.1 功能目标

1. 建立一个 canonical、deeply immutable、checksum-protected `StoredEvent`。
2. 每个 event 在 live consumer 可见前 durable append。
3. 每个 stream 内 sequence 单调且并发安全；不承诺跨 stream 总序。
4. delivery 明确为 at-least-once，consumer effect 通过 inbox/idempotency 收敛。
5. subscriber 之间隔离，单个失败不回滚已提交事实或阻断其他 consumer。
6. retry 有预算、有退避、有 DLQ、有 operator action 和 audit。
7. replay 默认只运行 pure reducer/command verification，不触发 live side effect。
8. schema 有 registry、validator、upcaster、quarantine 和历史 fixture。
9. 首次 durable write 前完成 security projection。
10. Workflow/Harness 使用同一 durable runtime；API/CLI/MCP 经 application service 查询。
11. `events.jsonl` 保留为兼容、redacted、带 high watermark/checksum 的 projection。
12. trace 使用 OpenTelemetry/W3C，且不参与 event ordering、authorization 或 idempotency。

### 4.2 一致性与可用性承诺

| 项目 | 明确承诺 |
| --- | --- |
| Durable append | commit 成功后，进程重启仍可读取；commit 失败则 subscriber 不可见 |
| Event identity | 相同 id+checksum 幂等；相同 id+不同 checksum 拒绝 |
| Ordering | 只保证一个 `stream_id` 内的 `stream_sequence` 唯一、单调、authoritative |
| Delivery | at-least-once；可能重试和重复调用，业务效果必须幂等 |
| Consumer isolation | 一个 consumer 失败不改变其他 consumer 的 terminal result |
| Replay | state rebuild/verification 无 live side effect；redelivery 必须显式授权 |
| Trace | best-effort observability，可采样；durable event 不采样 |
| Store outage | required append fail closed；不得静默降级到 memory-only |

### 4.3 第一版容量与 SLO

参考负载统一为：canonical event 平均 4 KiB、inline 上限 64 KiB、extensions 最多 32 项且总计不超过 8 KiB；benchmark 必须记录 CPU、内存、磁盘、Python/PostgreSQL 版本和配置。

| 指标 | SQLite local target | PostgreSQL target |
| --- | --- | --- |
| Commit append p95 | ≤ 25 ms，单 writer、持续 25 events/s、10 分钟 | ≤ 50 ms，8 writers、持续 100 events/s、10 分钟 |
| Commit append p99 | ≤ 100 ms | ≤ 200 ms |
| 正确性 | 0 event loss，0 duplicate sequence，0 checksum drift | 0 event loss，0 duplicate sequence，0 sequence race |
| Ordered read | 10,000 条 4 KiB 事件在 30 秒内完成 checksum/schema 验证 | 同左 |
| Crash recovery | 已 commit event 重启后 100% 可读 | 已 commit transaction 100% 可读 |
| Dispatcher recovery | worker death 后在 `2 * lease_duration` 内重新 claim | 同左 |
| Default lease | 30 秒，可配置为 5-300 秒 | 同左 |
| Default retry | 总计 5 次；1s 起步、60s cap、20% jitter | 同左 |
| Default batch/in-flight | batch 100；每 consumer in-flight 100 | 同左 |
| Query pagination | default 100，maximum 1,000 | 同左 |
| Projection staleness | finalized run 为 0；running run 明确返回 high watermark | 同左 |

以上性能门槛不是用来绕过正确性。任何 event loss、duplicate sequence、secret 泄漏、错误 checkpoint 或重复副作用都直接验收失败，即使延迟达标。

### 4.4 Retention 与容量保护

- run-owned event stream 跟随现有 run lifecycle/retention policy；
- 本阶段不独立 compact Harness/Workflow transition event；
- 大型非敏感内容必须按 schema policy 转普通 integrity-protected artifact ref，不能靠无限增大 inline limit；reference-only、`confidential` 或 `restricted` 内容只能进入另行授权、加密、校验并审计的 secure payload store，否则 publish fail closed；
- consumer pending warning threshold 默认 10,000；hard admission threshold 默认 100,000，可按部署配置但必须非零；
- 达到 hard threshold 或 durable capacity 不足时，publish 在 commit 前明确失败，不能接受后静默丢弃 delivery；
- retention 删除必须先满足 run lifecycle、legal hold、tenant 和 replay/checkpoint 依赖，且留下审计结果。

---

## 5. 非目标

本阶段明确不做：

- 不引入 Kafka、Temporal、Dapr、NATS 或云消息服务；
- 不建立跨区域复制、broker federation 或全局总序；
- 不把整个 NewsRoom 改造成 Event Sourcing；
- 不保证 HTTP、email、LLM、Tool、MCP、Artifact publication 或任意外部数据库物理执行一次；
- 不允许 replay 自动重做历史外部副作用；
- 不用 trace/baggage 取代 tenant、run、workflow、event 或 authorization identity；
- 不用 LLM 决定 schema compatibility、delivery retry、DLQ、checkpoint、replay pass/fail 或 redelivery authorization；
- 不新增前端 UI；operator 能力先通过 application service、API/CLI/MCP 提供；
- 不永久保留 `EventRecord/EventEnvelope/runner-local store` 兼容层；
- 不在本阶段做独立 event compaction、跨 region disaster recovery 或第三方 broker adapter。

---

## 6. 系统不变量

以下任意一项被破坏，阶段不得标记完成：

1. 已接受 event 的 canonical bytes、checksum、event_id 和 stream_sequence 永不被修改。
2. subscriber 在 event/outbox transaction commit 前不可见。
3. 同一 stream 中两个 event 不得共享 sequence；sequence 不因删除或 rollback 被复用。
4. 同一 event_id 的不同内容不得被当作 duplicate success。
5. 一个 consumer 的失败不得撤销另一个 consumer 的 ACK。
6. delivery attempt、lease、error 和 checkpoint 不得写回 immutable event。
7. `REBUILD_STATE` 与 `VERIFY_HISTORY` 不得调用 live side-effect adapter。
8. missing time、unknown schema、field conflict 和 corrupt checksum 不得被静默修补为“合法当前事件”。
9. raw secret 不得先落盘后再脱敏。
10. trace 缺失或 sampling 不得导致 durable event 缺失。
11. required store 不可用时不得降级为 memory-only success。
12. Event Runtime 不得决定 Harness routing、quality result、memory write、tool auth 或 publication。
13. framework 只拥有 contract/ports/policy；infrastructure 实现 store；interface 只调用 application service。
14. `events.jsonl` 是 projection，不得再次作为 live store 的写入来源。
15. rollback 不得删除已接受 event、复用 sequence 或重新触发 external effect。
16. `run_id` 必须在派生 stream 或解析任何 store/projection path 前通过 single-segment path-safe validation；失败不得留下 event、delivery 或文件。
17. consumer checkpoint 是 subscription-version + stream 的最高连续 terminal frontier；不得越过仍在 retry/claimed/pending 的较低 sequence。
18. 普通 `ArtifactReference`、本地路径或 checksum-only ref 不得被宣称为 confidential/restricted 安全存储；没有 secure payload store 时必须 fail closed。

---

## 7. 目标架构与职责边界

### 7.1 总体数据流

```text
typed domain/Harness/workflow event
        |
        v
ScopedEventEmitter
        |
        v
canonicalize -> schema validate -> security project -> checksum
        |
        v
EventRuntime.publish()
        |
        +--> atomic stream sequence
        +--> immutable event row
        +--> pending delivery rows
        +--> commit
        |
        +--------------------------+
        |                          |
        v                          v
Durable Dispatcher           Query / Projection
  -> claim lease               -> application reader
  -> consumer                  -> API/CLI/MCP/SSE
  -> ACK/RETRY/DROP             -> redacted events.jsonl
  -> inbox/checkpoint
  -> DLQ

Durable Stream
  -> checkpoint + replay reader
  -> REBUILD_STATE pure reducers
  -> VERIFY_HISTORY command comparison
  -> authorized REDELIVER via delivery ledger

OpenTelemetry/W3C
  -> observes append/delivery/replay
  -> never replaces durable stream
```

### 7.2 层级 ownership

| 层 | 负责 | 禁止 |
| --- | --- | --- |
| `framework/events` | canonical model、ports、schema policy、delivery/replay state machine、trace facade、typed errors | import infrastructure、直接连接 DB、决定业务 workflow |
| `framework/harness` / `framework/workflow` | 产生 typed event、记录 activity refs、按 checkpoint 恢复业务 state | 定义第二套 event store、post-run 二次索引、memory-only durable transition |
| `infrastructure/storage/events` | SQLite/PostgreSQL schema 与 adapters、transaction、leases、checkpoint、DLQ | 定义业务 routing、跳过 framework validation/security |
| `interfaces/services` | authorization、tenant scope、query/replay/DLQ use case | 直接暴露 store/dispatcher、让 router 访问 executor |
| API/CLI/MCP | transport mapping 和兼容 response | 自行访问 event store、绕过 operator policy |
| OpenTelemetry adapter | spans、links、metrics、propagation | 持久化业务事实或充当 replay source |

### 7.3 Harness authority

Event Runtime 只能向 Harness 返回确定性的 append/delivery/replay result。以下事项仍由 Harness 或 application policy 决定：

```text
下一步 route
quality pass/fail
retry/replan/halt（workflow 语义）
memory write authorization
tool authorization
artifact publication authorization
operator approval requirement
```

Delivery retry 只重试“某个 consumer 处理一条已提交事件”，不能被混用为 Harness 的 workflow retry。

---

## 8. Canonical Event、Delivery 与 Replay 数据模型

### 8.1 `StoredEvent`

| 字段 | 必填 | Owner | 语义与约束 |
| --- | --- | --- | --- |
| `envelope_schema` | 是 | runtime | 初始为 `newsroom.event-envelope/v2`，与 payload schema 分离 |
| `event_id` | 是 | runtime/authorized producer | 首次 append 前稳定生成；全局唯一；不同内容不可复用 |
| `event_type` | 是 | schema catalog | 注册的 semantic event name；旧名称可作为 v1 alias |
| `data_schema` | 是 | schema catalog | payload schema identity/version |
| `source` | 是 | producer adapter | 发生事实的 producer namespace，不是 routing destination |
| `subject` | 否 | producer adapter | source 范围内受影响实体 |
| `occurred_at` | 是 | producer/schema | 事实发生时间；UTC；不得用 import time 猜测 |
| `observed_at` | 是 | store | durable store 接受时间；UTC |
| `stream_id` | 是 | application/runtime | ordering/replay scope，例如 `run:<run_id>` |
| `stream_sequence` | 是 | store | 1-based、stream 内唯一、单调、commit 后不可变 |
| `correlation_id` | 否 | application | 关联一组业务动作，不承担 order |
| `causation_id` | 否 | application/runtime | 直接导致当前事实的 event_id |
| `business_context` | 是 | scoped emitter | `run/workflow/step/task/agent/tool_call/request` 等明确字段 |
| `producer` | 是 | composition/runtime | `component/version/instance_id` |
| `trace` | 否 | trace adapter | W3C-compatible context；不承担授权、顺序或幂等 |
| `tenant_id` | 条件必填 | application service | tenant-scoped run 必须有；不可由 payload override |
| `security_classification` | 是 | security policy | `public/internal/confidential/restricted`，默认 `internal` |
| `content_type` | 是 | schema catalog | inline payload 或 referenced content 类型 |
| `payload` | 二选一 | producer/schema | canonical immutable JSON；默认最大 64 KiB |
| `payload_ref` | 二选一 | payload boundary | 大型非敏感内容可用普通 integrity ref；protected content 只能引用经过授权、加密和审计的 secure payload store |
| `extensions` | 否 | registry | 有命名、类型、大小约束；不可覆盖 core field |
| `content_checksum` | 是 | runtime | 覆盖完整 canonical pre-storage acceptance projection；只排除 store/delivery/replay 状态；用于 uncertain commit 和 identity 判定 |
| `record_checksum` | 是 | store/runtime | 分配 `observed_at/stream_sequence` 后，对完整 stored record（不含自身）计算；用于完整性验证 |

### 8.2 `DeliveryRecord`

Delivery 是 consumer 状态，不是事实内容：

```text
delivery_id
event_id
subscription_id / subscription_version
consumer_id
consumer_effect_id
delivery_generation
state: PENDING | CLAIMED | RETRY_WAIT | ACKED | DROPPED | DEAD_LETTER
attempt_count
available_at
lease_owner
lease_generation
lease_expires_at
first_failure_at
last_failure_at
reason_class
redacted_diagnostics
created_at
updated_at
```

唯一约束至少包括：

```text
(event_id, subscription_id, subscription_version, delivery_generation)
```

Inbox terminal uniqueness 至少包括：

```text
(event_id, consumer_effect_id)
```

### 8.3 `ConsumerCheckpoint`

```text
stream_id
subscription_id
subscription_version
highest_contiguous_terminal_sequence
last_event_id
terminal_disposition
updated_at
checksum/version
```

`highest_contiguous_terminal_sequence` 表示从 subscription version 的 start position 到该 sequence 为止，每个匹配 delivery 都已 ACK、policy-approved DROP 或 DEAD_LETTER，且不存在更低的 PENDING/CLAIMED/RETRY_WAIT。它与：

- 0-based legacy JSONL line offset；
- delivery attempt number；
- checkpoint file sequence；

必须使用不同字段名，禁止继续统称 `offset`。

### 8.4 `ReplayReport`

```text
replay_id
mode
source_stream_id
from_sequence / to_sequence / high_watermark
checkpoint_ref
runtime/workflow/reducer/schema/activity_versions
applied_upcasters
quarantine_refs
mismatch_sequence
status
reason_class
result_checksum
started_at / finished_at
operator_context（仅 REDELIVER）
```

ReplayReport 存在单独 audit stream/table，不修改 source event stream。

---

## 9. Schema Catalog 与版本演进

### 9.1 Registry contract

`EventSchemaCatalog` 必须按 `(event_type, data_schema)` 提供：

```text
payload validator
canonical serializer rules
compatible predecessor versions
pure upcaster to next version
sensitive/reference-only/forbidden field policy
inline size override（不得为无限）
retention/classification hint
consumer compatibility metadata
```

### 9.2 事件命名

现有名称如 `workflow_started`、`step_finished` 在迁移期注册为 v1 aliases，避免 flag-day rename。新事件采用 namespaced convention，例如：

```text
io.newsroom.workflow.run.started
io.newsroom.workflow.step.finished
io.newsroom.harness.phase.transitioned
io.newsroom.tool.call.completed
```

compatible payload change 可以保持 event_type 并提升 data schema minor/major；事件语义发生不兼容变化时必须使用新 event_type。

### 9.3 Upcaster 规则

- 每个 upcaster 只处理相邻版本，例如 `v1 -> v2`；
- pure、deterministic、无 I/O、无 real clock、无 LLM/Tool；
- 不修改 stored history；只形成 reader view；
- 每条支持链必须有 historical fixture；
- upcaster 抛错或缺一步即 quarantine；
- replay report 记录使用过的版本链。

### 9.4 Quarantine

以下记录必须 quarantine，而不是猜测：

```text
unknown envelope/data schema
schema validation failure
missing/invalid occurred_at
conflicting duplicated context
same event_id with different checksum
corrupt JSON/checksum
unsupported legacy field mapping
upcaster failure
tenant/security scope ambiguity
```

Quarantine 记录 source location、reason class、schema identity、bounded redacted diagnostic 和 operator disposition，不复制 raw secret。

---

## 10. Durable Append、Store 与 Sequence

### 10.1 权威 publish 顺序

```text
1. 产生 stable event_id
2. typed event -> canonical draft
3. schema validate
4. security project
5. canonicalize + content_checksum
6. begin transaction
7. allocate observed_at + stream_sequence atomically
8. compute record_checksum over the complete stored record
9. insert immutable event
10. insert pending delivery rows
11. commit
12. return StoredEvent
13. dispatcher 才可 claim
```

任何 1-11 步失败：

- subscriber 不可见；
- 不留下 partial event/outbox；
- 不推进 stream sequence；
- 不触发 external side effect；
- 返回 typed error。

### 10.2 Duplicate 语义

| 输入 | 结果 |
| --- | --- |
| 新 event_id | 正常 append 并分配新 sequence |
| 既有 event_id + 相同 `content_checksum` | 返回既有 event、observed_at、sequence 和 record_checksum，不新增 row/outbox |
| 既有 event_id + 不同 `content_checksum` | `EventIdentityCollisionError`，不覆盖历史 |
| transaction commit 结果不确定 | 先按 event_id 查询；不得直接生成新 id 重试 |

`content_checksum` 的 canonical input 必须包含：`envelope_schema/event_id/event_type/data_schema/source/subject/occurred_at/stream_id`、correlation/causation、business context、producer、trace、tenant/classification、content type、security projection 后的 payload 或 `payload_ref + expected_checksum`、extensions。只排除 `observed_at`、`stream_sequence`、两个 checksum 自身以及 delivery/checkpoint/lease/replay/operator state。因此同一 `event_id` 即使 payload 相同，只要 stream、tenant、schema、classification、context 或 ref 不同，也必须判为 collision。

### 10.3 Stream 与 sequence

- Workflow/Harness 默认：`stream_id = run:<run_id>`；
- `run_id` 必须先验证为一个 path-safe segment，再用于 stream derivation、store key 或 `events.jsonl`/manifest 路径；traversal、absolute、drive-relative、UNC/device、ADS 和 reserved-device 输入必须在任何写入前失败；
- Agent session：`agent-session:<session_id>`；
- 其他 aggregate 必须显式命名；
- sequence 从 1 开始；
- PostgreSQL 使用 stream row lock、原子 counter 或等价 transaction-safe strategy；禁止 `COUNT(*)`；
- timestamp、event_id、trace_id 都不是 order；
- 不承诺跨 stream 比较 sequence。

### 10.4 SQLite local backend

第一版本地 durable backend 使用 Python stdlib SQLite：

- WAL mode；
- foreign keys；
- unique constraints；
- bounded busy timeout；
- explicit transaction；
- single-host support；
- documented synchronous/fsync policy；
- integrity check、backup 和 recovery；
- locked、read-only、disk-full、corrupt DB 明确 fail closed。

SQLite 不得被描述为 multi-host HA broker。当前 `LocalJsonEventStore` 仍是无 `NEWS_DATABASE_DSN` 时可写的默认 local store，并被 Workflow post-run indexing 使用；完成本阶段 cutover 后，它才降级为 legacy import/export/read compatibility adapter，不再是 production write source of truth。

### 10.5 PostgreSQL backend

- 新增 additive migration，不修改部署过的 `001_initial.sql`；
- canonical event、stream counter、delivery、inbox、checkpoint、lease、DLQ、quarantine、replay report 有明确表/约束；
- event 与 delivery rows 同 transaction；
- shared UoW 时允许 business state + event/outbox 同 transaction；
- duplicate event_id 返回数据库中既有 sequence，不能返回未插入的 candidate sequence；
- concurrency test 必须使用真实 PostgreSQL transaction，不得只依赖 FakeConnection。

### 10.6 Backend conformance

SQLite/PostgreSQL 使用同一套 conformance suite，至少覆盖：

```text
append success/rollback
same-id idempotence/collision
same-stream concurrent sequence
ordered pagination
security projection parity
outbox claim/lease
inbox uniqueness
checkpoint
retry/DLQ
crash recovery
corruption/availability failure
```

---

## 11. Outbox、Inbox 与业务事务边界

### 11.1 Event/outbox atomicity

Event row 和所有 active consumer 的 pending delivery rows 必须同 transaction commit。不得：

```text
先 commit event，之后逐 consumer 创建 delivery
先调用 subscriber，之后 append event
先写 JSONL，之后异步猜测要不要进 store
```

### 11.2 Business state atomicity

| 场景 | 保证 |
| --- | --- |
| business state 与 event store 使用同一个 PostgreSQL UoW | state + event + outbox all-or-nothing |
| SQLite 本地 workflow state/replay projection | transition event 先 durable，projection 可从 event 恢复 |
| 外部 API/Tool/另一数据库 | at-least-once + idempotency key + reconciliation，不承诺 distributed transaction |

本阶段不引入 two-phase commit。

### 11.3 Inbox 与外部 effect

external-effect subscription 必须声明 stable `consumer_effect_id`，并在 activation/首次投递前通过以下任一方式证明业务效果幂等：

1. 在同一 effect transaction 中插入 `(event_id, consumer_effect_id)` inbox unique row；
2. 使用目标系统支持的 idempotency key；
3. 业务主键天然 overwrite-idempotent，并有测试证明；
4. 无法证明时拒绝激活或投递；operator authorization 不能把 automatic retry、lease recovery、requeue/redelivery 变安全。

Runtime 只保证 event 会至少投递一次；不会把“consumer 回 ACK”解释成“物理只执行一次”。

### 11.4 Harness/Workflow transaction boundary

- Harness transition event commit 后，才推进 recoverable in-memory projection；
- process 在 commit 后/内存更新前崩溃时，recovery 重新应用 committed transition，不再询问 LLM；
- Workflow checkpoint 记录 last durable sequence/event_id；
- resume 从 checkpoint 之后的 sequence 应用 committed events；
- external activity 只在 causal event commit 后被 delivery/runtime 调用。

---

## 12. Consumer、Retry、Lease、DLQ 与 Backpressure

### 12.1 Consumer contract

每个 consumer 必须有 stable `consumer_id`，返回：

```text
ACK(reason?)
RETRY(reason_class, bounded_diagnostic)
DROP(reason_class, bounded_diagnostic)
```

未处理 exception 默认映射到 `RETRY`；typed permanent processing failure 立即进入 DLQ。`DROP` 只允许表示确定性 policy-approved non-error skip，不能绕过 failure diagnostic、retry budget 或 DLQ。Error classifier 是确定性 policy，不使用 LLM。

Consumer 不是临时函数列表，而是 durable、versioned subscription：

```text
subscription_id / version
consumer_id
event_type + data_schema filter
start_policy: EARLIEST | LATEST | AT_SEQUENCE
start_sequence / registration_watermark
retry/lease/concurrency policy
status: ACTIVE | PAUSED | RETIRED
created_at / updated_at
```

- `EARLIEST` 从仍在 retention 内的第一条匹配 event 开始；
- `LATEST` 在 transaction 中固定 registration watermark，只接 watermark 之后的 event；
- `AT_SEQUENCE` 从明确的 inclusive sequence 开始；
- registration/backfill 与 concurrent publish 通过 subscription state + unique delivery constraint 保证边界不漏不重；
- pause/retire 保留 checkpoint、inbox、attempt 和 audit history；
- pause 期间继续 materialize matching delivery row、停止新 claim；resume 从原 contiguous frontier 无缝 drain；
- retire transactionally 固定 watermark，之后不再 materialize；已有 nonterminal rows 必须 drain 或逐条留下 authorized terminal-cancellation disposition；
- 修改 filter/start position 创建新 version，不能改写旧进度。

### 12.2 Delivery state machine

```text
PENDING
  -> CLAIMED
       -> ACKED
       -> DROPPED
       -> RETRY_WAIT -> CLAIMED
       -> DEAD_LETTER

CLAIMED --lease expired--> PENDING/RETRY_WAIT
DEAD_LETTER --authorized requeue--> 新 delivery generation
```

Terminal state：`ACKED`、`DROPPED`、`DEAD_LETTER`。同一 `(subscription_id, version, stream_id)` 正常 claim 必须连续：N 仍为 PENDING/CLAIMED/RETRY_WAIT 时，N+1 不得作为 normal ordered work 被 claim；并发只跨 stream。DLQ 为 N 留下 auditable terminal disposition 后，contiguous frontier 才能越过 N，避免 poison event 永久阻塞。

Authorized DLQ requeue 是独立 late-repair generation：不回退正常 frontier，不阻塞或重排已继续处理的后续 sequence。只有声明 idempotent out-of-order repair 的 consumer 可执行；否则必须创建新 subscription version + deterministic rebuild，或发起独立 compensation workflow。已 ACK effect 的 redelivery 在原 `consumer_effect_id` 下保持 no-op；真正的新补偿效果必须是单独建模、授权和审计的 command。

### 12.3 默认 retry policy

```text
max_attempts = 5（包含第一次）
initial_delay = 1 second
multiplier = 2
max_delay = 60 seconds
jitter = ±20%
```

consumer 可以声明更严格值，不得声明无限 retry。DLQ 必须记录：event/consumer、attempts、first/last failure time、reason class、redacted diagnostic、tenant scope、operator disposition。

### 12.4 Lease 与 fencing

- claim 包含 `lease_owner`、`lease_generation`、`expires_at`；
- worker death 后 lease 到期可恢复；
- 旧 generation 的迟到 ACK 被拒绝；
- claim/retry/terminal transition transaction-safe；
- lease 默认 30 秒，consumer 可按 5-300 秒配置；
- 长任务必须 heartbeat/renew，不能依赖无限 lease。

### 12.5 Consumer isolation

同一事件的每个 consumer 拥有独立 delivery row：

```text
consumer A ACK      -> 保持 ACK
consumer B RETRY    -> 只重试 B
consumer C DROP     -> 独立 terminal disposition
```

观察性 consumer 故障不得让 Workflow 重跑 deterministic work。Workflow 必须同步依赖的确定性操作应是正常 service call，不应伪装成 subscriber。

### 12.6 Backpressure

- 每个 consumer 有 batch、in-flight、concurrency limit；
- 不把所有 pending event 加载进内存；
- 同一 stream 对同一 consumer 按 sequence 处理；不同 stream 可并行；
- 暴露 lag、pending count、oldest pending age；
- storage/capacity 无法接受时 publish fail before commit；
- event 被 durable 接受后不得因 backlog 静默删除。

---

## 13. Deterministic Replay 与 Activity History

### 13.1 三种 replay mode

| Mode | 用途 | 允许执行 | 禁止执行 |
| --- | --- | --- | --- |
| `REBUILD_STATE` | 从 history 重建 projection/state | registered pure reducer | live subscriber、LLM、Tool、HTTP、email、publication、memory write |
| `VERIFY_HISTORY` | 用确定性代码重新生成 commands 并与历史对照 | pure workflow/Harness decision code、recorded activity result | 修改历史、重调 nondeterministic activity |
| `REDELIVER` | operator 对指定 event-consumer pair 重新投递 | 正常 delivery ledger、idempotent consumer | 广播到所有 subscriber、绕过 authorization/inbox |

旧 `replay_to_bus()` 行为不得继续出现在生产路径。Inspection 只读历史，不等于 replay；redelivery 也不等于 state rebuild。

### 13.2 Pure reducer contract

Reducer 必须：

```text
new_state = reducer(old_state, canonical_event_view)
```

并满足：

- 无 I/O；
- 无 LLM/Tool/MCP；
- 无 real clock/random；
- 不修改 event；
- 同 state+event 得到同 result；
- 通过 version registry 解析；
- 有 state checksum fixture。

### 13.3 Activity history

下列操作必须作为 nondeterministic activity 记录：

```text
LLM invocation
Tool invocation
MCP/HTTP request
retrieval/source read
memory recall/write
artifact publication
email/webhook
real clock/random input
external database effect
```

Activity history 至少包括：

```text
activity_id
activity_type / contract_version
idempotency_key
input_ref + checksum
output_ref + checksum
status
attempts
started_at / completed_at
error classification
producer/worker version
```

Replay 只读取 recorded output。缺少完整 activity result 时返回 `IncompleteHistoryError`，不得临时调用 live provider 填空。

### 13.4 Command verification

`VERIFY_HISTORY` 对每个 deterministic decision 重新产生 command，并按 sequence 与 recorded command 比较：

```text
command type
target step/activity
policy/version
input refs/checksums
budget snapshot
gate result
route/retry/replan/halt decision
```

不匹配时立即产生 typed nondeterminism report，不覆盖历史，也不能将后续 run 标记成功。

### 13.5 Checkpoint replay

新 checkpoint 必须保存：

```text
stream_id
last_applied_stream_sequence
last_event_id
state snapshot/ref + checksum
workflow/reducer/policy/schema versions
created_at
```

Replay 从 `after_sequence = last_applied_stream_sequence` 继续。Legacy 0-based JSONL offset 通过 migration mapping 转换，必须有边界 fixture 证明既不漏一条，也不重复一条。

### 13.6 Replay isolation 与 concurrency

- ReplayReport 使用独立 audit store/stream；
- source history byte-for-byte 不变；
- running stream 的 replay 在启动 transaction 中固定 finite high watermark；本阶段没有 follow mode，也不能通过参数把同一 replay 变为无界读取；
- replay 与 live append 并行时，只应用 high watermark 以内事件；
- replay 中途崩溃可从 report checkpoint 续传；
- checksum/schema/upcaster/handler version 任何一步失败都 fail closed。

---

## 14. OpenTelemetry / W3C Trace Context

### 14.1 TraceContext 目标

新生成 context 使用标准字段：

```text
trace_id: 16 bytes / 32 hex / nonzero
span_id: 8 bytes / 16 hex / nonzero
trace_flags
tracestate
is_remote
links[]
```

旧 `workflow:<run_id>` root span 和 32-hex child span 不再用于新 outbound propagation。历史值保留为 legacy correlation data，不重写，不注入 W3C carrier。

### 14.2 Propagation boundary

以下边界统一执行：

```text
inbound carrier
  -> validate/extract
  -> trust policy
  -> create child/consumer span
  -> execute
  -> inject outbound carrier
```

覆盖：

- HTTP inbound/outbound；
- MCP server inbound；
- ToolRuntime outbound MCP/HTTP；
- worker task/message；
- event delivery；
- subagent handoff；
- external storage calls（按 semantic convention）。

MCP server inbound 与 ToolRuntime outbound MCP adapter 仍是两类职责，不因共享 propagation helper 合并。

### 14.3 Resource 与 InstrumentationScope

- `Resource`：NewsRoom service/process/instance/deployment identity；
- `InstrumentationScope`：`framework.events`、workflow bridge、Harness、ToolRuntime 等 library/component 和 version；
- `source` 与 `component` 不再是两个随意、互相替代的字符串；
- run/workflow/step 作为受控 attributes 或 durable business context，不进入 Resource。

### 14.4 Span Links

以下情形使用 links，而不是强行选择单一 `parent_span_id`：

- batch 消费多个 trace；
- fan-in；
- queue 消费晚于 producer span；
- retry/redelivery；
- 一个 activity 由多个 event 共同触发；
- resume 使用新 trace 关联旧运行。

Event `causation_id` 仍记录业务因果；Span Link 只记录观测因果。

### 14.5 Sampling 与安全

- span 可以按 policy sampling；durable event 不采样；
- raw payload、prompt、answer、evidence、memory namespace、secret 不进入 attributes/events；
- tenant/user/run/event/trace id 不作为 metrics label；
- tracestate/baggage 有 allowlist 和大小限制；
- 外部 trace id 不承担授权；trust boundary 可 restart trace；
- OpenTelemetry 未安装或 exporter 不可用时，no-op adapter 不改变 runtime 结果。

### 14.6 Compatibility facade

一版迁移窗口保留：

```text
TraceContext.root()
TraceContext.child()
to_dict()/from_dict()
trace_fields()
```

但 facade 内部必须：

- 新 context 生成 W3C-compatible IDs；
- 传播 `agent_id/tool_call_id/memory_operation_id/artifact_id` 等既有业务字段；
- 不把 current context 作为共享 mutable recorder state；
- 对历史 invalid span id 只读保留，不 outbound inject。

---

## 15. 安全、租户、Redaction 与 Integrity

### 15.1 Security projection 必须最先 durable

```text
raw typed payload
  -> schema classification
  -> allowed/reference-only/sensitive/forbidden policy
  -> projected canonical payload
  -> checksum
  -> durable append
```

不得采用：

```text
raw JSONL 先写
-> storage index 再脱敏
```

Local 和 PostgreSQL backend 接收同一 post-projection canonical record；不能一个 backend 自动脱敏、另一个信任 caller。

### 15.2 Field policy

| 分类 | 行为 |
| --- | --- |
| allowed | 可 inline，仍受 schema/size 约束 |
| sensitive | schema-aware redaction/tokenization/encryption policy；默认不 inline secret |
| reference-only | 必须用另行组合的 tenant-authorized、加密、完整性校验且访问可审计的 secure payload ref；普通 `ArtifactReference`、本地路径或 checksum-only ref 不合格 |
| forbidden | publication fail before append |

Core identity、schema、sequence、producer、trace、tenant、classification、checksum 都是 infrastructure-owned，payload/extensions 不可覆盖。

这里的 `access-controlled` 不是名称或 checksum，而是可验证能力：tenant-scoped authorization、encryption in transit/at rest、integrity verification、audited access。当前 `framework/artifacts` 的普通 `ArtifactReference` 和本地 artifact path 不满足该边界；阶段 18 也不负责补 ACL/加密。因此第一版规则是：

- oversized non-sensitive content 可按 schema 使用普通 integrity-protected artifact ref；
- `reference-only/confidential/restricted` 只有在 composition 注入上述 secure payload store 时才可使用 secure ref；
- secure payload store 未配置或 capability validation 失败时，publication 在 sequence allocation、store、projection、delivery 前 fail closed；
- 不允许把 secret 从 event row 转移到普通 artifact 后宣称“已脱敏”。

### 15.3 Tenant 与访问控制

- tenant-scoped run/event 必须持有 `tenant_id`；
- application service 从 authenticated context 决定 tenant scope；
- API/CLI/MCP 不能信任 caller 仅凭 event_id/trace_id 切换 tenant；
- query/export/replay/DLQ/quarantine/requeue 都执行 tenant filter/authorization；
- `security_classification` 默认 `internal`；
- `confidential/restricted` payload 默认 reference-only；
- retention/legal hold 也按 tenant/classification 执行。

### 15.4 Integrity

- canonical event 有 `content_checksum` 与 `record_checksum`，覆盖范围不可混用；
- payload_ref 有 expected checksum；
- JSONL projection 有 file checksum + source high watermark；
- replay/checkpoint 读取前验证 checksum；
- checksum mismatch 进入 corruption/quarantine diagnostic，不返回正常 event；
- stored history 不因 upcast 被覆盖；
- DLQ/retry error 不保存 raw exception locals/headers/token。

### 15.5 Recursive failure 防护

Event store append 失败时，诊断不能再次通过同一个 Event Runtime 记录“event append failed”，否则会无限递归。

失败策略：

1. 返回 typed failure；
2. 写一个 bounded、redacted、nonrecursive process/local diagnostic；
3. 增加独立 telemetry counter（如果 telemetry 可用）；
4. readiness/health 标记 degraded/unavailable；
5. 不包含 raw event payload；
6. 不宣称 diagnostic durable。

---

## 16. Query、Projection 与 Operator Interface

### 16.1 Application service boundary

新增或收敛 application-owned event services：

```text
EventReaderService
EventProjectionService
EventReplayService
EventDeliveryOperationsService
EventQuarantineService
```

它们依赖 framework ports。Router/CLI/MCP 不直接 import `infrastructure.storage.events`、dispatcher 或 Workflow executor。

### 16.2 Run event 查询兼容

现有 `RunEventsResult` 对外结构继续支持：

```text
run_id
event_count
events
events_path
event_type filter
step_id filter
limit
offset（legacy request alias）
SSE event/progress
```

新增：

```text
next_sequence_cursor
high_watermark
source = durable_store | projection
projection_status = current | running | stale | unavailable
projection_checksum
```

`offset` 在兼容 response 中明确是 pagination position，不得被解释成 canonical event identity。新 client 使用 sequence cursor。

### 16.3 Store unavailable / projection stale

| 状态 | API/service 行为 |
| --- | --- |
| durable store 正常 | 从 store 查询，projection 只提供 path/status |
| running run projection 落后 | 返回 store 结果 + projection `running/stale` 和 high watermark |
| store 暂时不可用但 projection 存在 | 明确返回 unavailable/stale metadata；是否给只读 projection 由 endpoint policy 决定，不伪装 authoritative |
| store 与 projection checksum/watermark 冲突 | fail/diagnostic，禁止合并两套数据 |
| tenant unauthorized | 保持现有 auth error contract，不泄漏 event 是否存在 |

SSE 断线重连使用 durable sequence cursor；不得只依赖进程内 `_published` list。

### 16.4 `events.jsonl` projection

保留 run artifact key/path：

```text
run/<run_id>/events.jsonl
manifest["artifacts"]["events"]
trace_events_ref / trace_ref
event_count
```

但生成方式改为：

```text
durable stream up to high watermark
-> ordered read
-> schema/security projection
-> temp file
-> checksum
-> atomic replace
-> manifest watermark/checksum update
```

projection 绝不回灌 live store。损坏/partial legacy JSONL 只通过 importer 进入 quarantine report。

### 16.5 Operator capabilities

首版提供：

- list/get quarantine；
- list/get/requeue/resolve dead letter；
- consumer lag/checkpoint/status；
- replay start/status/report；
- projection rebuild/status；
- store health；
- explicit redelivery。

每个 mutation 操作要求：authorization、tenant scope、target consumer/event range、operator reason、idempotency readiness、audit result。

---

## 17. Compatibility、Migration 与旧代码删除

### 17.1 必须保留的硬契约

迁移期必须保持：

1. `events.jsonl` artifact key 和相对路径；
2. run manifest 的 event/trace refs 和 event_count；
3. Run Events API/CLI/MCP 的核心 response/filter；
4. checkpoint/recovery 对历史 offset 的可迁移读取；
5. 历史 JSONL 支持 `occurred_at` 或 `timestamp` 等已知字段；
6. `append_event/list_by_run/list_by_step/filter_by_type/stream_from_offset` 旧 store read API 的 adapter；
7. `NEWS_DATABASE_DSN` 选择 PostgreSQL、无 DSN 选择 local backend；
8. 既有 event type 字符串通过 catalog alias 使用；
9. 一版 deprecated `framework.events` public imports 和 callable subscriber shim。

### 17.2 不应长期保留

```text
_records + _envelopes 双列表
EventBus = InMemoryEventBus 作为生产具体类型
legacy callable 收 EventRecord、新 subscriber 收 Envelope 的分裂语义
runner-local WorkflowEventRecord/LocalJsonWorkflowEventStore/factory
post-run JSONL -> store indexing
replay_to_bus() live side-effect path
Event 与 Envelope 双 context truth
Harness memory-only durable main path
```

### 17.3 迁移阶段

| Phase | 写路径 | 读路径 | 目标与退出门槛 |
| --- | --- | --- | --- |
| M0 Inventory | legacy | legacy | model/writer/reader/type/fixture 清单完整；反例 tests 已加入 |
| M1 Contract | legacy | legacy + canonical parser | canonical/schema/security/upcaster 完成；不改 live write |
| M2 Store | legacy | conformance tests | SQLite/Postgres schema/adapter/race 修复通过；migration dry-run 无源数据修改 |
| M3 Shadow | legacy 单写 | legacy + shadow compare | canonical export 与 legacy fixture 数量/内容差异可解释；禁止双 dispatch |
| M4 Cutover | canonical 单写 | canonical + compatible projection | Workflow/Harness live append；同 release 禁用 post-run index |
| M5 Delivery/Replay | canonical | canonical | consumer ledger/replay/trace/interface 验收通过 |
| M6 Contract delete | canonical | canonical + bounded legacy import | repo callers 迁完，兼容 release 到期，删除重复模型/路径 |

迁移期间只能有一个 authoritative write path。Shadow phase 可以比较 projection，不能同时向两套 live subscriber 投递。

### 17.4 Historical backfill

Backfill 流程：

```text
scan source read-only
-> detect format/version
-> canonical parse/upcast/project
-> calculate stable import key/checksum
-> append staging store
-> verify counts/order/checksum
-> generate mapping + quarantine report
-> operator approve cutover
```

source history 不重写、不删除、不 sanitize ID。0-based line offset 与 1-based stream sequence 通过 mapping table 保留。

### 17.5 Expand/contract database rollout

1. additive migration，旧 binary 可继续读旧列/表；
2. deploy new reader/parser；
3. deploy new store/runtime behind explicit flag；
4. backfill/shadow verify；
5. cut writer/read source；
6. observe one compatibility release；
7. 删除 old code；
8. destructive schema cleanup 必须另一个明确 migration/change，不在本阶段静默 drop。

Feature flag 只能控制 cutover/dispatcher，不得关闭 schema validation、security projection、identity collision 或 checksum 校验。

---

## 18. 文件级影响矩阵

以下是实施前必须复核的 live target。具体拆文件可按职责优化，但不得遗漏对应 ownership。

### 18.1 `framework/events`

| 路径 | 变更 |
| --- | --- |
| `framework/events/event.py` | 收敛 typed draft/compat facade；删除 duplicate durable context；deep immutable normalization |
| `framework/events/envelope.py` | 迁移 reader/adapter；冲突 fail closed；最终由 `StoredEvent` 取代 |
| `framework/events/recorder.py` | 删除 framework `EventRecord` 双账；改 scoped durable emitter；JSONL 只做 projection facade |
| `framework/events/bus.py` | 明确 InMemory test adapter；生产 publish 走 durable runtime；不再同步 fail-fast 形成部分投递 |
| `framework/events/publisher.py` | 接 schema/security/canonical runtime；返回 durable acceptance result |
| `framework/events/subscriber.py` | stable consumer id；ACK/RETRY/DROP；callable shim deprecated |
| `framework/events/ordering.py` | 移除生产内存 sequence authority；保留测试/compat 时不得伪装 durable |
| `framework/events/replay.py` | 三种 replay mode；删除生产 replay-to-live-bus |
| `framework/events/trace.py` | OTel/W3C facade、safe propagation、完整业务 ID compatibility |
| `framework/events/filters.py` | sequence cursor、tenant/security-aware application filtering contract |
| `framework/events/errors.py` | identity/schema/quarantine/store/delivery/replay typed errors |
| `framework/events/__init__.py` | 新 ports/models exports；一版 deprecation；最终删除 legacy exports |
| 新 `framework/events/schema/*` | catalog、validators、upcasters、security policy |
| 新 `framework/events/runtime/*` | publish、delivery policy、replay policy、protocols、models |

### 18.2 Storage

| 路径 | 变更 |
| --- | --- |
| `infrastructure/storage/events/models.py` | 迁移为 canonical storage adapter DTO，避免第二套事实模型 |
| `infrastructure/storage/events/local_json.py` | 降为 legacy importer/exporter/read adapter |
| 新 `infrastructure/storage/events/sqlite.py` | local transactional durable store |
| `infrastructure/storage/events/factory.py` | no DSN -> SQLite；DSN -> PostgreSQL；Workflow 真实使用 |
| `infrastructure/storage/postgres/event_store.py` | canonical schema、transaction-safe sequence、delivery/inbox/checkpoint/DLQ/quarantine/replay |
| `infrastructure/storage/postgres/migrations/*` | 新 additive migration；不得改 `001_initial.sql` |
| `infrastructure/storage/security/*` | shared security projection contract，与 framework schema policy 对接 |
| storage backup/health/metrics | SQLite/Postgres health、backup/recovery、lag/corruption signals |

### 18.3 Workflow

| 路径 | 变更 |
| --- | --- |
| `framework/workflow/runtime/execution_context.py` | 注入 scoped emitter/runtime；不持有共享 mutable trace context |
| `execution_loop.py` / `step_invoker.py` / `runtime_event_bridge.py` | typed event -> canonical durable append；业务 causation/activity refs |
| `checkpoint_coordinator.py` | 保存 last durable stream sequence/event id，不用 `len(list_events())` |
| `outcome_finalizer.py` | 从 store 生成 redacted projection；不写 raw recorder list |
| `runner.py` | 删除 post-run `_index_events()`、runner-local model/store/factory；使用 application composition |
| `result.py` / `manifest.py` / `manifest_updater.py` | high watermark、projection checksum/status、event store refs |
| `inspection/inspector.py` | projection reader DTO；在线 source 改 application service |
| `operations/service.py` | replay/projection/checkpoint operation 与 event service 协作 |
| `checkpoint/*` | sequence/version/checksum migration 与 recovery |

### 18.4 Harness

| 路径 | 变更 |
| --- | --- |
| `framework/harness/ports.py` | durable event port/adapter contract，不再只有 memory record |
| `control_plane/event.py` | typed Harness transition，适配 canonical schema |
| `control_plane/event_log.py` | canonical projection/replay view，消除独立主事实路径 |
| `control_plane/harness.py` | transition durable commit before state projection；store unavailable fail closed |
| `control_plane/transcript.py` | 从 canonical history 形成 transcript refs |
| `runtime/durable_state.py` | sequence/checkpoint/reducer coordination |
| `runtime/replay.py` | 接统一 replay modes，不重复执行 worker/LLM/tool |

### 18.5 直接 trace consumers

至少为以下调用点加 compatibility/propagation tests：

```text
framework/agent/loop/events.py
framework/memory/diagnostics/trace.py
framework/memory/runtime/*
framework/tool/inspection/metrics.py
framework/tool/runtime/executor.py
framework/workflow/runtime/manifest_updater.py
HTTP/MCP/worker composition boundaries
```

### 18.6 Application 与 interfaces

```text
interfaces/services/run_inspection_service.py
interfaces/services/run_inspection_projection.py
interfaces/services/mcp_service.py
interfaces/api/routers/runs.py
interfaces/api/app.py
interfaces/cli/commands/runs.py
```

新增/收敛 application service 后，这些 interface 只做 transport mapping，不直接接 store/dispatcher。

### 18.7 Tests

```text
tests/framework/events/*
tests/framework/contracts/test_event_trace_contract.py
tests/framework/harness/**/*event* / *replay* / *checkpoint*
tests/framework/workflow/runtime/*
tests/framework/workflow/checkpoint/*
tests/framework/workflow/inspection/*
tests/infrastructure/storage/test_event_store*.py
tests/infrastructure/storage/postgres/test_postgres_event_store.py
tests/interfaces/services/test_run_inspection_service.py
run event API/CLI/MCP/SSE tests
tests/architecture/*event* / framework boundary tests
new shared store conformance and fault-injection suites
```

实施时不得覆盖当前工作树中并行进行的 artifact path/integrity hardening；涉及 `runner.py`、inspection、storage local paths 等重叠文件时，先审阅 live diff 并按 path-scoped commit 集成。

---

## 19. 测试计划与故障注入矩阵

### 19.1 单元与契约测试

必须覆盖：

- canonical field validation/serialization/checksum；
- recursive immutability；
- duplicate context equal/conflict；
- schema validation/upcast/quarantine；
- occurred_at/observed_at；
- payload size/ref；
- redaction/classification/tenant reserved fields；
- `trace_fields()` 完整传播受支持的 Agent/Tool/Memory/Artifact IDs，schema-aware sensitive policy 不依赖模糊 key substring；
- ACK/RETRY/DROP state machine；
- retry math/jitter bounds；
- pure reducer/version/command comparison；
- W3C ID/propagation/links/no-op OTel；
- legacy import offset mapping。

### 19.2 Store conformance

同一套 tests 对 SQLite 与 PostgreSQL 运行：

- append/read/filter/pagination；
- same id same/different checksum；
- concurrent same-stream sequence；
- transaction rollback；
- outbox/inbox/checkpoint；
- lease fencing；
- retry/DLQ/requeue；
- quarantine/replay report；
- security projection parity；
- capacity/unavailable behavior。

PostgreSQL concurrency gate 必须连接真实测试数据库并开启真实并发 transaction；FakeConnection 只用于低层 SQL shape 单测，不能证明竞态被修复。

### 19.3 故障注入矩阵

| ID | 故障注入点 | 期望结果与不变量 |
| --- | --- | --- |
| F1 | canonicalize 后、begin transaction 前崩溃 | 无 durable row、无 sequence、无 delivery、无 subscriber |
| F2 | event insert 后、outbox insert 前异常 | 整个 transaction rollback；event 不可见 |
| F3 | commit response 丢失/结果不确定 | 按 event_id 查询；same checksum 返回既有 sequence；不生成新 id |
| F4 | 两个 writer 同时向同 stream append | sequence 唯一单调；0 conflict leak；Postgres 不使用 COUNT |
| F5 | same event_id 不同 payload | identity collision；旧记录不变 |
| F6 | 第 N 个 subscriber 失败 | 其他 consumer terminal 状态不变；只重试失败 consumer |
| F6A | consumer registration 与 publish 并发 | EARLIEST/LATEST/AT_SEQUENCE 边界 event 不漏；unique constraint 防止重复 delivery row |
| F6B | subscription v1 到 100，v2 AT_SEQUENCE=50 | v2 使用独立 checkpoint/delivery；不继承或覆盖 v1 progress |
| F6C | PAUSED 期间持续 publish 后 resume | rows 持续 materialize；resume 从原 frontier 不漏不重；RETIRED watermark 后不新增 rows |
| F7 | effect 成功、ACK 前 worker 崩溃 | redelivery 使用同 idempotency key；业务 effect 不重复 |
| F7A | external-effect consumer 无 idempotency proof | activation/first delivery fail；automatic retry/lease/requeue 都不可绕过 |
| F8 | worker lease 到期后迟到 ACK | stale generation ACK 被拒绝 |
| F9 | poison event 达 retry budget | durable DLQ terminal disposition 闭合该 sequence；contiguous frontier 随后可前进；后续 event 可处理 |
| F9A | N retry、N+1 已就绪 | N+1 不 claim；contiguous frontier 不越过 N |
| F9B | frontier 越过 N 后 requeue N | 创建 late-repair generation；frontier 不回退；unsupported consumer 要求 rebuild/compensation |
| F10 | DLQ 写入失败 | delivery 不伪装 terminal success；transaction rollback/health degraded；bounded nonrecursive diagnostic |
| F11 | slow consumer/backlog | batch/in-flight bounded；lag/age metric；其他 consumer 不被阻断 |
| F12 | SQLite locked/read-only/disk full | publish fail before commit；无 memory-only fallback；readiness degraded |
| F13 | SQLite DB corrupt | integrity/typed corruption error；不返回正常 event；执行 documented recovery |
| F14 | PostgreSQL connection 在 transaction 中断 | all-or-nothing；uncertain commit 用 event_id resolution |
| F15 | raw secret payload | 首次 durable write/JSONL/DLQ/log/trace 中均不存在 raw value |
| F15A | protected payload 仅提供普通 ArtifactReference | append 前拒绝；artifact/event/projection 均不落 raw secret |
| F16 | payload nested input mutation | stored payload/checksum 不变 |
| F17 | Event/Envelope trace conflict | fail/quarantine；不得双 trace |
| F18 | unknown schema/upcaster throws | quarantine；normal consumer/replay 不处理 |
| F19 | missing timestamp | 不填 now；quarantine/unresolved-time typed status |
| F20 | corrupt event checksum | query/replay fail before apply；source history 不修改 |
| F21 | checkpoint checksum/stream/version 不匹配 | reject restore；不应用后续 event |
| F22 | legacy offset boundary | mapping fixture 证明不漏、不重放 checkpoint 边界 event |
| F23 | replay LLM/tool/activity | 读取 recorded output；live fake provider call count 为 0 |
| F24 | replay 中途崩溃 | 从 replay checkpoint 续传；source history unchanged |
| F25 | replay 与 live append 并行 | 固定开始时 high watermark；不读取后续新事件 |
| F26 | command order 因代码升级改变 | typed nondeterminism；不覆盖 history，不返回 success |
| F27 | trace sampled/drop/exporter failure | durable event/Workflow result 不变 |
| F27A | trace payload/metadata 含 credential-like key 与完整业务 IDs | schema policy 正确 redaction，不因 substring 误删合法字段；`agent_id/tool_call_id/memory_operation_id/artifact_id` 全部传播；修改 source metadata 不改变 accepted event |
| F28 | projection 写到一半崩溃 | 旧完整 projection 保留；temp 不被宣称 current |
| F29 | projection watermark 与 store 不同 | 返回 stale/conflict status；不混合两套数据 |
| F30 | unauthorized tenant replay/DLQ/query | 不泄漏存在性；无 mutation/audit side effect（除安全审计） |
| F31 | event store failure diagnostic | 不递归调用同一 event store；只产生一次 bounded fallback diagnostic |
| F32 | Harness transition append 失败 | phase/state 不推进；不调用 worker/external activity；无 memory fallback |
| F33 | retry/route_to_repair/approval resume/cancel transition | 每种 transition 先 durable commit；crash recovery 不重新询问 worker/LLM |
| F34 | same event id/payload、不同 tenant/stream/schema/ref | content checksum 不同；identity collision；不返回旧 event |
| F35 | unsafe run_id | stream/path derivation 前拒绝；0 event/delivery/manifest/JSONL write |

### 19.4 Architecture tests

必须证明：

- `framework/events` 不 import `infrastructure`；
- Workflow `runner.py` 不定义 event store implementation/model/factory；
- interfaces 不直接 import infrastructure event store 或 dispatcher；
- Harness 保持 routing authority；
- Event Runtime 不 import business routing/gate；
- business 不依赖 concrete event storage；
- inbound MCP 与 outbound ToolRuntime MCP adapter 只共享 propagation contract，不混淆职责。

### 19.5 Benchmark

固定 workload 至少执行：

```text
SQLite:
  1 writer
  25 events/s
  10 minutes
  4 KiB average event

PostgreSQL:
  8 concurrent writers
  100 events/s aggregate
  same stream + multiple streams 两种场景
  10 minutes
  4 KiB average event

Read/replay:
  10,000 events
  schema + checksum + reducer
```

证据记录：machine、OS、CPU、RAM、disk、Python、psycopg、PostgreSQL、SQLite pragma、payload distribution、p50/p95/p99、error/loss/duplicate counts。

---

## 20. OpenSpec 与实施任务

### 20.1 Change

```text
openspec/changes/durable-event-runtime/
  .openspec.yaml
  proposal.md
  design.md
  tasks.md
  specs/
    durable-event-contract/spec.md
    durable-event-delivery/spec.md
    deterministic-event-replay/spec.md
    event-trace-propagation/spec.md
    workflow-storage-indexing/spec.md
```

### 20.2 Capability mapping

| Capability | 负责 |
| --- | --- |
| `durable-event-contract` | canonical model、immutability、schema、time、security、legacy migration |
| `durable-event-delivery` | append/order/store/outbox/inbox/consumer/retry/DLQ/lease/backpressure |
| `deterministic-event-replay` | replay modes、activity history、checkpoint、version/nondeterminism、Harness durable transitions |
| `event-trace-propagation` | OTel/W3C IDs、propagation、Resource/Scope、Links、sampling/security |
| modified `workflow-storage-indexing` | live durable append；JSONL 改为 projection；online query source cutover |

### 20.3 实施批次与 commit 边界

推荐每批独立验证并提交：

1. `test(events): capture durable runtime adversarial baseline`
2. `feat(events): add canonical event and schema contracts`
3. `feat(storage): add sqlite durable event backend`
4. `feat(storage): harden postgres event sequencing and delivery ledger`
5. `feat(events): add durable publish and consumer delivery runtime`
6. `refactor(workflow): cut event writes to durable runtime`
7. `refactor(harness): persist control-plane transitions durably`
8. `feat(events): add deterministic replay and activity history`
9. `feat(observability): add W3C and OpenTelemetry event propagation`
10. `feat(interfaces): query and operate durable event streams`
11. `refactor(events): remove legacy dual event paths`
12. `docs(events): record migration and acceptance evidence`

测试尽量与实现同 commit。不得混入现有 artifact hardening 或其他 dirty worktree 变更。

---

## 21. Requirements -> Tasks -> Tests 追踪矩阵

| 需求族 | OpenSpec | Tasks | 核心验证 |
| --- | --- | --- | --- |
| Canonical/immutable/identity/time | `durable-event-contract` | 2.1-2.3 | F5/F16/F17/F19/F20/F34 |
| Schema/upcast/quarantine | `durable-event-contract` | 2.4、1.4、9.1 | F18/F19 + historical fixtures |
| Security/tenant/size/ref | `durable-event-contract` | 2.5、8.5 | F15/F15A/F30 + backend parity |
| Atomic append/order/store | `durable-event-delivery` | 3.1-3.7、4.1 | F1-F5、F12-F14 + real concurrency |
| Consumer subscription/inbox/retry/DLQ | `durable-event-delivery` | 4.2-4.7 | F6-F11 + F6A/F6B/F6C/F7A/F9A/F9B |
| Backpressure/health/diagnostic | `durable-event-delivery` | 4.7-4.8 | F11-F13/F31 + SLO |
| Workflow/Harness cutover | modified indexing + replay | 5.1-5.6 | F28/F29/F32/F33/F35 + manifest/checkpoint tests |
| Replay/activity/version | `deterministic-event-replay` | 6.1-6.5 | F20-F26 |
| OTel/W3C | `event-trace-propagation` | 7.1-7.5 | F27/F27A + propagation/security tests |
| Query/projection/operator | modified indexing + delivery/replay | 8.1-8.5 | F28-F30 + API/CLI/MCP/SSE |
| Migration/delete/rollback | all | 1、9 | dry-run/backfill/cutover/rollback drill |

---

## 22. 验收标准

### 22.1 Canonical contract

- [ ] 所有 durable writer 最终进入同一个 canonical boundary。
- [ ] 所有 core context 只有一个 authoritative value；legacy conflict fail/quarantine。
- [ ] caller/consumer mutation 不能改变 stored bytes/checksum。
- [ ] same id same checksum 幂等；same id different checksum typed failure。
- [ ] envelope/data schema 分离，validator/upcaster/quarantine 完整。
- [ ] missing time 不再填 now。
- [ ] payload/extension limit 和 artifact ref policy 生效。
- [ ] content checksum 覆盖明确；跨 stream/tenant/schema/classification/context/ref 的 same-id collision 测试通过。
- [ ] ordinary ArtifactReference 不承载 protected content；无 secure payload store 时 append 前 fail closed。

### 22.2 Durable storage

- [ ] SQLite/PostgreSQL conformance suite 全部通过。
- [ ] PostgreSQL `COUNT(*)` sequence allocation 已删除。
- [ ] real PostgreSQL concurrency test 0 duplicate sequence/loss。
- [ ] duplicate event id 返回既有 committed sequence。
- [ ] SQLite lock/full/read-only/corrupt/crash 语义通过故障测试。
- [ ] Local/PostgreSQL 首次 durable write 使用相同 security projection。
- [ ] required store outage 不 memory fallback。

### 22.3 Delivery

- [ ] event/outbox 同 transaction，subscriber 只看 committed event。
- [ ] ACK/RETRY/DROP、inbox、checkpoint、lease/fencing、DLQ 全部可测试。
- [ ] 一个 consumer 失败不影响其他 consumer terminal state。
- [ ] external-effect subscription 在 activation/首次 delivery 前验证 `consumer_effect_id` 与幂等边界；无法证明时 fail closed。
- [ ] external effect crash-after-success 用同 idempotency key 不重复业务结果。
- [ ] `DROP` 只处理 policy-approved non-error skip；permanent processing failure 直接进入 durable DLQ。
- [ ] retry budget 有限，poison event 进入 DLQ，后续 sequence 不永久阻塞。
- [ ] checkpoint 按 subscription version + stream 隔离，只推进 highest contiguous terminal frontier。
- [ ] pause/resume/retire materialization、watermark 和 drain/cancel 语义通过并发测试。
- [ ] DLQ requeue 是不回退 frontier 的 late repair；unsupported out-of-order consumer 必须 rebuild/compensate。
- [ ] backpressure 有 batch/in-flight/concurrency hard bounds 和 lag metrics。
- [ ] diagnostic failure 不递归写同一故障 store。

### 22.4 Workflow/Harness

- [ ] Workflow execution 中实时 durable append，不等 finalization。
- [ ] `events.jsonl` 从 store 生成，含 watermark/checksum，不回灌 store。
- [ ] runner-local store/model/factory 和 post-run indexing 删除。
- [ ] checkpoint 保存 last durable sequence/event id。
- [ ] unsafe run_id 在 stream/path derivation 前失败且 0 durable/file side effect。
- [ ] 每个 Harness phase transition commit 后才推进 projection。
- [ ] retry、route_to_repair、approval resume/cancel、budget halt 和所有 terminal transition 都先 durable。
- [ ] Harness append failure 时 state/worker/activity 不推进。
- [ ] Event Runtime 没有夺取 Harness routing/quality/tool/memory/publication authority。

### 22.5 Replay

- [ ] state rebuild、history verify、redelivery 三种模式严格分离。
- [ ] rebuild/verify 对 LLM/Tool/MCP/HTTP/memory write/publication 调用计数为 0。
- [ ] pure reducer、command comparison、handler version 和 activity result 有固定契约。
- [ ] replay 使用 stream sequence，不用 timestamp 排序。
- [ ] 每次 replay 在启动 transaction 中固定 finite source high watermark，并发 live append 不改变本次输入范围。
- [ ] checkpoint resume 与 legacy offset boundary 不漏不重。
- [ ] source history 不被 replay 修改。
- [ ] corruption/schema/activity/version mismatch fail closed 并生成 report。

### 22.6 Trace、安全与 interfaces

- [ ] 新 trace/span ID 符合 W3C；跨边界 extract/inject 可验证。
- [ ] async/batch/fan-in/retry 使用 links。
- [ ] `trace_fields()` 完整传播 Agent/Tool/Memory/Artifact IDs；schema policy 的 sensitive handling 无 substring 误报/漏报，accepted context 不受 source metadata 后续修改影响。
- [ ] trace sampling/OTel absence 不影响 durable event。
- [ ] raw secret 不出现在 event、JSONL、DLQ、log、metric、trace。
- [ ] tenant scope 覆盖 query/export/replay/DLQ/quarantine。
- [ ] API/CLI/MCP/SSE 保持核心兼容并返回 sequence/watermark/status。
- [ ] stale/unavailable projection 行为明确，不伪装 authoritative。
- [ ] interfaces 只调用 application service。

### 22.7 Migration/rollback

- [ ] migration dry-run/backfill mapping/quarantine report 完整且 source read-only。
- [ ] cutover 期间只有一个 authoritative writer，无双 dispatch。
- [ ] compatibility facade 有明确一版期限和删除门槛。
- [ ] rollback drill 保留所有 accepted event/sequence，不重复 effect。
- [ ] feature flag 不可关闭 schema/security/identity/integrity gate。

---

## 23. 验证命令

OpenSpec：

```powershell
openspec status --change durable-event-runtime
openspec validate durable-event-runtime --strict
```

核心 targeted tests（实际实施时可按 live tree 增补，不可缩减测试层）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\framework\events -q
.\.venv\Scripts\python.exe -m pytest tests\framework\contracts\test_event_trace_contract.py -q
.\.venv\Scripts\python.exe -m pytest tests\framework\harness -q
.\.venv\Scripts\python.exe -m pytest tests\framework\workflow -q
.\.venv\Scripts\python.exe -m pytest tests\infrastructure\storage\test_event_store.py tests\infrastructure\storage\test_event_store_factory.py -q
.\.venv\Scripts\python.exe -m pytest tests\infrastructure\storage\postgres\test_postgres_event_store.py -q
.\.venv\Scripts\python.exe -m pytest tests\interfaces\services\test_run_inspection_service.py -q
```

必须另外执行：

```text
real SQLite crash/lock/full/corruption suite
real PostgreSQL concurrent transaction integration suite
API/CLI/MCP/SSE run event suite
migration fixtures/backfill dry-run
fixed workload SLO benchmark
rollback drill
```

最终门禁：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
openspec validate --all --strict
git diff --check
```

任何失败必须修复根因；不得 skip、xfail、弱化断言、关闭 security/schema/checksum 或用 FakeConnection 代替必须的真实并发验收。

---

## 24. 发布、回滚与运行指标

### 24.1 发布顺序

```text
baseline tests + inventory
-> canonical/schema/security
-> SQLite/Postgres expand migration + conformance
-> migration dry-run/backfill staging
-> shadow compare（不双 dispatch）
-> Workflow/Harness writer cutover + 禁用 post-run index
-> delivery/runtime
-> replay/trace
-> interface reader/operator cutover
-> one compatibility release
-> legacy code deletion
```

### 24.2 Kill switch

允许的开关：

- 暂停 dispatcher claim 新 delivery；
- 暂停某 consumer；
- 暂停 automatic retry/requeue；
- 切换 read source 回 compatible projection（明确 stale）；
- 在 writer cutover 前关闭 shadow compare。

禁止的开关：

- durable append 成功但不写 event/outbox；
- 关闭 schema/security/checksum/identity validation；
- required transition 降级 memory-only；
- replay 自动调用 live side effect；
- 隐藏 quarantine/DLQ 伪装 success。

### 24.3 回滚策略

**Cutover 前：** 可停用新 runtime，legacy writer 未改变；保留 staging data 和报告。

**Cutover 后：** 不得返回 unpersisted bus。可以回滚 reader/dispatcher/application binary，但：

- 新 canonical event 保持不动；
- sequence 不复用；
- projection 从 high watermark 重建；
- pending delivery 保持并可由兼容 dispatcher 恢复；
- external effect 不重新广播；
- DB expand schema 保留；destructive cleanup 延后；
- schema/security/integrity gate 保持开启。

回滚触发条件：

- legal event 系统性被 schema 误拒；
- accepted event loss/duplicate sequence；
- external effect 重复超出幂等 contract；
- secret 泄漏；
- standard Workflow/Harness 无法 durable transition；
- query/projection 大面积不兼容；
- append latency 连续 15 分钟超过 SLO 2 倍且 backlog 持续上升。

### 24.4 运行指标

至少提供：

```text
event_append_total{backend,result}
event_append_latency_seconds{backend}
event_delivery_pending{consumer}
event_delivery_lag{consumer}
event_delivery_oldest_age_seconds{consumer}
event_delivery_attempt_total{consumer,outcome}
event_dead_letter_total{consumer,reason_class}
event_lease_recovery_total{consumer}
event_schema_validation_total{event_type,result}
event_upcast_total{event_type,from,to,result}
event_quarantine_total{reason}
event_identity_collision_total{source}
event_replay_total{mode,result}
event_replay_mismatch_total{reason}
event_projection_high_watermark{projection}
event_projection_staleness{projection}
event_store_health{backend}
```

Metric labels 不包含 tenant/user/run/event/trace id 或 raw payload。Event store 自身故障指标通过独立 telemetry/fallback diagnostic，不递归写 event runtime。

---

## 25. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 变更跨 event/workflow/harness/storage/interface | 一次性重构难验证 | 按 12 个 commit 批次；每批独立测试和回滚 |
| 与当前 artifact hardening 重叠文件 | 覆盖用户并行改动 | 实施前检查 live diff；path-scoped commit；逐块集成 |
| cutover 双写 | duplicate event/delivery | stable event id；一个 authoritative writer；shadow 只比较不 dispatch |
| legacy offset -> sequence off-by-one | resume 漏/重事件 | 独立命名 + mapping table + boundary fixtures |
| PostgreSQL sequence race | unique conflict/错误 order | transaction-safe stream counter；真实并发 tests；禁用 COUNT |
| SQLite 被误当 HA broker | 多机并发/恢复错误预期 | 明确 single-host；multi-host production 用 PostgreSQL |
| external effect 被重复 | 邮件/写库/发布重复 | activation/首次 delivery 前验证 inbox/idempotency contract；普通 retry、lease recovery、requeue 与 redelivery 均不得绕过 |
| poison event 阻塞 stream | consumer 永久 lag | bounded retry、DLQ terminal position、contiguous frontier、late-repair requeue |
| redaction 破坏 replay 输入 | 无法重建 activity | secure payload store 可用时引用；否则 protected content fail closed，普通 artifact ref 不冒充安全边界 |
| schema 变化使旧 run 不可读 | replay/inspection 中断 | adjacent upcasters、fixtures、version pin、quarantine |
| trace migration 破坏历史 | 无法关联或注入 invalid ID | 历史只读保留，新 ID 标准化，不重写历史 |
| store/projection 不一致 | operator 看到不同事实 | store authoritative；watermark/checksum；stale/conflict explicit |
| diagnostic recursive failure | 无限递归/资源耗尽 | bounded nonrecursive fallback channel |
| compatibility layer 永不删除 | 再次形成双账 | 一版期限；repo caller migration gate；DoD 要求删除 |
| Retention 过早删 event | replay/checkpoint/legal hold 失效 | lifecycle dependency check + tenant/legal hold + audit |
| Event Runtime 越权控制 Harness | 破坏架构护栏 | architecture tests；runtime 只返回结果，不决定 route/gate/auth |

---

## 26. Definition of Done

本阶段只有在以下条件全部满足时才是 `IMPLEMENTED`：

- [ ] `durable-event-runtime` 的 proposal/design/5 个 delta specs/tasks 通过 strict validation。
- [ ] 本 PRD 中 E1-E12 均有 committed regression、实现修复和 evidence。
- [ ] canonical event 是唯一 durable source；typed domain event 只在 boundary 转换。
- [ ] SQLite/PostgreSQL 通过同一 conformance suite，真实 PostgreSQL concurrency 通过。
- [ ] Workflow/Harness transition 在执行中 durable；store outage fail closed。
- [ ] event/outbox atomic；consumer inbox/checkpoint/retry/DLQ/lease/backpressure 通过故障测试。
- [ ] external-effect consumer 没有可验证的幂等边界就不能激活或接收 delivery；`DROP` 不能吞掉 permanent failure。
- [ ] consumer subscription 的 EARLIEST/LATEST/AT_SEQUENCE、version、pause/retire 和注册并发边界通过测试。
- [ ] subscription-version contiguous frontier、DLQ late repair 和 activation-before-idempotency gate 通过并发/崩溃测试。
- [ ] state rebuild/history verify 无 live side effect；activity history/version/nondeterminism 可解释。
- [ ] replay 启动时固定 finite source high watermark；与 live append 并发时结果仍确定且有界。
- [ ] security projection 在首次 durable write 前；raw secret leakage tests 为 0。
- [ ] protected content 在无 secure payload store 时 fail closed；普通 ArtifactReference 未被当作 ACL/加密能力。
- [ ] OTel/W3C propagation 完成，sampling/no-op 不影响 durable event。
- [ ] API/CLI/MCP/SSE 保持兼容并明确 source/watermark/stale/unavailable。
- [ ] backfill dry-run、staging import、cutover 和 rollback drill 全部留有 evidence。
- [ ] SLO benchmark 达标，且 0 loss/duplicate sequence/checksum drift。
- [ ] `events.jsonl` 是 deterministic redacted projection，不再回灌 store。
- [ ] `_records/_envelopes` 双账、framework/storage duplicate record、runner-local store/factory、post-run index、live-bus replay 等旧路径按迁移门槛删除。
- [ ] 架构测试证明 framework/infrastructure/interface/Harness authority 边界成立。
- [ ] targeted tests、compile、smoke、all-strict 和 diff-check 全部通过。
- [ ] 每个实施批次已独立提交，未混入无关 dirty worktree。
- [ ] PRD metadata 更新为 `IMPLEMENTED`，补 commits、migrations、benchmark、rollback 和最终验证结果。

未满足任意一项时，状态只能是 `NOT_STARTED`、`IN_PROGRESS` 或有明确证据的 `BLOCKED`。不得以“Event 类已经改好”“本地测试通过”“主要路径可用”“Kafka 以后再接”或“现有 12 个测试继续通过”为由标记完成。

---

## 27. 可复制给 Codex 的实施提示

```text
请实现 docs/prd/harness-research-runtime/19-durable-event-runtime-hardening.md，使用 OpenSpec change `durable-event-runtime`。

要求：
1. 先读取 AGENTS.md、本 PRD、OpenSpec proposal/design/specs/tasks 和当前 dirty worktree；不得覆盖 artifact hardening 等并行改动。
2. 严格按 tasks.md 依赖顺序实施，不要一次性重写整个 event/workflow/harness/storage/interface 栈。
3. Harness 保持唯一流程控制者；Event Runtime 只负责 canonical fact、durable append、delivery 和 replay input。
4. 第一版使用 SQLite/PostgreSQL，不引入 Kafka/Temporal/Dapr；不承诺全局有序或 external exactly-once。
5. 必须先把 shallow mutation、trace conflict、Recorder 双账、partial delivery、duplicate replay、secret JSONL、missing time 和 Postgres COUNT race 转为 regression tests。
6. PostgreSQL 并发必须用真实 transaction integration test；FakeConnection 不算完成。
7. Replay rebuild/verify 不得调用 live LLM/Tool/MCP/HTTP/memory write/publication。
8. 所有 raw secret 必须在第一次 durable write 前处理。
9. Workflow/Harness cutover 与停止 post-run JSONL indexing 必须在同一个 release boundary 完成，禁止长期双写/双 dispatch。
10. 每个实施批次运行匹配的 tests 并 path-scoped commit；最终运行 compile、smoke、openspec validate --all --strict 和 git diff --check。
11. 全部用户回复、计划、问题和总结使用中文。
12. External-effect subscription 未证明 `(event_id, consumer_effect_id)` 或等价幂等边界时必须拒绝激活/投递；不得用 operator authorization 绕过 retry、lease recovery、requeue 或 redelivery 风险。
13. Reference-only/confidential/restricted content 没有另行授权、加密、完整性校验和访问审计的 secure payload store 时必须在 append 前拒绝；普通 ArtifactReference 不算 secure store。
```
