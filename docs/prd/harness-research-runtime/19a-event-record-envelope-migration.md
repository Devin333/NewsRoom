# 阶段 19A：Legacy EventRecord 删除与 Recorder 单模型迁移 PRD

> Document status: READY_FOR_IMPLEMENTATION
>
> Implementation status: NOT_STARTED
>
> Version: v1.0
>
> Priority: P1
>
> Parent PRD: `19-durable-event-runtime-hardening.md`
>
> OpenSpec change: `durable-event-runtime`
>
> Scope: `framework/events`、直接使用 `EventRecorder` 的 workflow runtime、run `events.jsonl` projection 及对应测试
>
> Last updated: 2026-07-15

> 状态说明：本文件是阶段 19 的聚焦实施切片，不创建第二个重叠 OpenSpec change。`READY_FOR_IMPLEMENTATION` 表示迁移目标、兼容期限、删除门槛和验收矩阵已经明确；`NOT_STARTED` 表示尚未修改生产代码。实施状态只允许按 `NOT_STARTED -> IN_PROGRESS -> IMPLEMENTED` 推进。

## 0. 一句话结论

NewsRoom 必须删除 framework legacy `EventRecord`，结束 `EventRecorder` 的 `_records/_envelopes` 双账和 EventBus 的混合投递类型；迁移期 `EventRecorder.emit()` 统一返回 `EventEnvelope`、`list_events()` 只返回 `EventEnvelope`，但 production durable source of truth 直接收敛到父 PRD 定义的 canonical `StoredEvent`，不得把 `EventEnvelope` 变成新的永久中间层。

---

## 1. 背景与问题

### 1.1 当前真实运行链

当前 workflow 事件路径是：

```text
build_execution_context()
  -> EventRecorder(run_id, event_bus)
        |
        v
execution_loop / runtime_event_bridge
  -> recorder.emit(...)
        |
        +--> EventRecord
        +--> _records.append(record)
        +--> _envelopes.append(record.to_envelope())
        +--> event_bus.publish(record)
        |
        v
checkpoint / finalizer
  -> len(recorder.list_events())
  -> recorder.write_jsonl(run/events.jsonl)
        |
        v
post-run indexing / inspection
  -> 再读 events.jsonl
  -> 转成其他 event record/read model
```

真实入口和消费者包括：

| 路径 | 当前职责 | 迁移问题 |
| --- | --- | --- |
| `framework/workflow/runtime/execution_context.py` | 创建 `EventRecorder` | production workflow 直接依赖 legacy concrete recorder |
| `framework/workflow/runtime/runtime_event_bridge.py` | 发出 workflow/step/review 等事件 | emit 返回类型仍是 legacy record contract |
| `framework/workflow/runtime/execution_loop.py` | 发出失败、暂停、完成等事件 | 事件只先进入 memory list，未形成 durable acceptance |
| `framework/workflow/runtime/checkpoint_coordinator.py` | 用 `len(list_events())` 生成 offset | list 长度不是 durable sequence |
| `framework/workflow/runtime/outcome_finalizer.py` | 统计事件并写 `events.jsonl` | 文件来自 `_records`，不是 canonical store projection |
| `framework/workflow/operations/service.py` | run 后续操作直接追加 flat operation event | canonical cutover 后会让同一 JSONL 混用两种 schema |
| `framework/events/bus.py` | 同步发布和兼容分发 | callable 可能收到 `EventRecord` 或 `EventEnvelope` |
| `framework/events/recorder.py` | 同时保存 `_records` 和 `_envelopes` | 同一事实有两套内存账本和两种返回类型 |

### 1.2 已确认缺陷

| ID | 级别 | 缺陷 | 后果 |
| --- | --- | --- | --- |
| ER1 | P1 | `EventRecorder.emit()` 返回 `EventRecord`，而标准 event runtime 使用 `EventEnvelope` | 调用方必须理解两套模型 |
| ER2 | P1 | `_records` 与 `_envelopes` 双写 | 两个列表可能数量、内容和顺序不一致 |
| ER3 | P1 | `list_events()` 根据内部状态返回 `EventRecord` 或 `EventEnvelope` | 类型注解和运行时结果不稳定 |
| ER4 | P1 | `write_jsonl()` 只写 `_records` | 直接 `record(envelope)` 的事件不会进入 run JSONL |
| ER5 | P1 | EventBus 对 legacy callable 保留 `EventRecord` 特例 | 同一 callback 的入参类型取决于 publish 原始类型 |
| ER6 | P1 | `events.jsonl` 是 post-run 写出再索引的事实来源 | crash-before-finalize 会丢失已发生但未写出的事件 |
| ER7 | P1 | legacy reader 会在时间缺失时回填当前时间 | 历史事实被静默改写，replay 不确定 |
| ER8 | P2 | framework 与 infrastructure 各有一个同名 `EventRecord` | import、迁移和删除范围容易误判 |
| ER9 | P1 | run operation event 绕过统一 emitter，直接追加 flat JSONL | 新旧 writer 并存，projection 无法保持单一 schema/source of truth |

### 1.3 两个 `EventRecord` 必须区分

本 PRD 直接删除的是：

```text
framework.events.recorder.EventRecord
schema_version = newsroom.event_record.v1
```

下列模型不是同一个类：

```text
infrastructure.storage.events.models.EventRecord
```

storage `EventRecord` 按父 PRD 迁移为 canonical storage adapter/projection DTO；在对应 adapter 完成前不得因同名而被顺手删除。

---

## 2. 与阶段 19 和 OpenSpec 的关系

### 2.1 权威边界

本 PRD 服从：

- `docs/prd/harness-research-runtime/19-durable-event-runtime-hardening.md`；
- `openspec/changes/durable-event-runtime/proposal.md`；
- `openspec/changes/durable-event-runtime/design.md`；
- `durable-event-contract`、`durable-event-delivery`、`workflow-storage-indexing` delta specs；
- `openspec/changes/durable-event-runtime/tasks.md`。

发生冲突时，以父 PRD 和上述 OpenSpec 的 canonical durable contract 为准。

### 2.2 为什么不新建第二个 OpenSpec change

现有 `durable-event-runtime` 已明确要求：

- converge `Event`、`EventEnvelope`、framework/storage `EventRecord`；
- 删除 recorder dual ledger；
- 删除 mixed subscriber payload；
- 将 `events.jsonl` 改为 durable stream 的 redacted projection；
- 在迁移审计通过后删除 legacy model/path。

本文件只把其中与 framework `EventRecord` 相关的工作拆成可独立执行和验收的切片，不重复定义 capability。

### 2.3 最终模型不是永久 `EventEnvelope`

父 PRD 的最终 durable contract 是 `StoredEvent`。本切片中的模型角色为：

| 模型 | 迁移期角色 | 最终角色 |
| --- | --- | --- |
| `Event` | typed draft/input | 可保留 typed draft，不是 durable source of truth |
| `EventEnvelope` | `EventRecorder` 和旧接口的一版兼容返回/读取投影 | bounded adapter/read projection，不是 canonical store record |
| framework `EventRecord` | legacy read fixture only | 删除 |
| `StoredEvent` | 新增 canonical durable acceptance | 唯一 durable source of truth |
| inspection DTO | 对外 read model | 保留 projection，不拥有写入权 |

因此，本 PRD 不允许出现下面的双重迁移陷阱：

```text
production EventRecord -> production EventEnvelope -> production StoredEvent
```

production writer 必须直接接 canonical runtime；只有 deprecated `EventRecorder` facade 可以在一版迁移期把 canonical result 投影为 `EventEnvelope`。

---

## 3. 目标与非目标

### 3.1 Goals

1. `EventRecorder.emit()` 在 bounded compatibility release 中只返回 `EventEnvelope`，不再创建 framework `EventRecord`。
2. `EventRecorder.list_events()` 的运行时和类型注解都固定为 `list[EventEnvelope]`。
3. owned production workflow 改用 scoped durable emitter/runtime，不再以 recorder list 作为事件事实来源。
4. 所有旧 `record.event_type/payload/occurred_at` 调用点完成迁移。
5. `events.jsonl` 保留原 artifact path，但改为 canonical durable stream 的 redacted、ordered projection。
6. 历史 `newsroom.event_record.v1`、`newsroom.event_envelope.v1` 和已知 flat JSONL 可读取、upcast 或 quarantine，源文件保持只读。
7. EventBus 删除 `EventRecord` 输入和 mixed callable payload 分支；同一订阅契约只接收一种类型。
8. 删除 framework `EventRecord` 类、导出、imports、转换方法和只验证旧行为的测试。
9. 保留并重写有业务价值的 trace、filter、ordering、JSONL、workflow、checkpoint 和 inspection 回归。

### 3.2 Non-Goals

- 不单独重做阶段 19 的 outbox/inbox、retry/DLQ、lease、replay 或 OpenTelemetry 全部实现。
- 不把 `EventEnvelope` 宣称为最终 durable store schema。
- 不删除 typed domain event 或 inspection read DTO。
- 不把 infrastructure storage `EventRecord` 与 framework legacy `EventRecord` 混为一谈。
- 不重写、删除或原地修补历史 `events.jsonl`。
- 不保留永久 legacy writer、双写、双 dispatch 或 mixed subscriber payload。
- 不新增 Kafka、Temporal、Dapr、外部 broker 或 UI。

---

## 4. 目标架构

### 4.1 Production 写路径

```text
Workflow / Harness typed event
        |
        v
ScopedEventEmitter / EventRuntimePort
        |
        v
normalize -> schema validate -> security project
        |
        v
atomic durable append
        |
        v
StoredEvent(event_id, stream_id, stream_sequence, ...)
        |
        +--> durable delivery
        +--> query/read projection
        +--> redacted events.jsonl projection
```

### 4.2 一版兼容 facade

```text
legacy owned/external caller
  -> EventRecorder.emit(...)
  -> scoped canonical append
  -> EventEnvelope compatibility projection
  -> return EventEnvelope
```

兼容 facade 不得：

- 写 `_records`；
- 同时写 memory envelope 和 durable event 两份 authoritative state；
- 从 JSONL 反向填充 live store；
- 触发第二次 subscriber dispatch；
- 在 schema/security/store failure 时降级为 memory-only success。

### 4.3 读路径

```text
online query
  -> application event reader
  -> canonical durable store
  -> inspection/API/CLI/MCP projection

offline artifact
  -> projection exporter
  -> run/<run_id>/events.jsonl
```

在线查询不得在 store 不可用时静默把 `events.jsonl` 当成 authoritative current state。

---

## 5. API 与行为需求

### 5.1 `EventRecorder.emit()`

迁移期签名语义：

```python
def emit(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    trace_context: TraceContext | None = None,
    component: str | None = None,
) -> EventEnvelope:
    ...
```

必须满足：

- 返回 envelope 的 `event_id` 与 canonical accepted event identity 一致；
- `event.created_at` 来自真实 occurrence time，不在历史恢复时填当前时间；
- `run_id/workflow_id/step_id/component` 只有一个 authoritative value；
- 顶层和内层 legacy duplicate context 相等时可读取，不一致时 fail/quarantine；
- `payload` 在进入 durable boundary 前通过 canonical normalization 和 security projection；
- store append 失败时不返回成功 envelope；
- compatibility projection 不产生第二个 event identity 或第二次 dispatch。

### 5.2 `list_events()`

兼容 facade 的唯一返回类型：

```python
def list_events(
    filters: EventFilter | None = None,
) -> list[EventEnvelope]:
    ...
```

必须满足：

- 无 filter 和有 filter 时返回相同元素类型；
- 返回列表副本，不暴露内部可变容器；
- 顺序来自 canonical `stream_sequence`，不来自 memory append 或 timestamp；
- production workflow 不使用 `len(list_events())` 生成 checkpoint identity；
- online production read 最终经 application reader/store，而不是 recorder memory list。

### 5.3 调用方字段迁移

| Legacy 读取 | Compatibility envelope 读取 | Production canonical 读取 |
| --- | --- | --- |
| `record.event_type` | `envelope.event.event_type` | `stored_event.event_type` |
| `record.payload` | `envelope.event.payload` | `stored_event.payload`/authorized payload view |
| `record.occurred_at` | `envelope.event.created_at` | `stored_event.occurred_at` |
| `record.run_id` | `envelope.run_id` | `stored_event.business_context.run_id` |
| `record.trace_id` | `envelope.trace_id` | `stored_event.trace.trace_id` |
| `record.event_id` | `envelope.event_id` | `stored_event.event_id` |
| `len(recorder.list_events())` | 不得作为 durable offset | `last_stream_sequence`/reader count |
| `record.to_dict()` | compatibility serializer only | projection exporter |

owned production caller 应优先直接迁移到 canonical API，避免先改成 nested envelope access、随后再次迁移到 `StoredEvent`。

### 5.4 `events.jsonl`

必须保留：

```text
run/<run_id>/events.jsonl
manifest artifact key: events
trace_ref / trace_events_ref
event_count compatible response meaning
```

新写入行为：

- 每行来自 committed canonical stream；
- 使用父 PRD 的 `newsroom.event-envelope/v2` compatible projection；
- 按 `stream_sequence` 升序输出；
- 输出前完成 redaction/security projection；
- manifest 记录 projection high watermark 和 checksum；
- exporter 不把文件再写回 live event store；
- crash-before-finalize 不影响已 committed event 的查询和恢复。
- inspection/API/CLI/MCP/SSE 通过 versioned read projection 继续获得顶层 `event_type`、`payload`、`occurred_at`、`run_id` 等兼容字段，不直接把 nested envelope 当旧 flat response 使用。

历史读取行为：

- 支持已知 `newsroom.event_record.v1` flat record；
- 支持 `newsroom.event_envelope.v1` nested record；
- 支持已知 `occurred_at`/`timestamp` 时间字段；
- 缺少 occurrence time、身份冲突、未知 schema 或同 ID 不同内容时 quarantine；
- 缺少 legacy `event_id` 时只能使用 schema-registered、可重复验证且包含 source provenance 的确定性迁移规则，无法满足时 quarantine；
- 不使用 `datetime.now()` 猜测历史时间；
- 不使用随机 UUID 让同一历史行在重复 import 时变成不同事件；
- 不覆盖历史源文件；
- 保留 legacy 0-based line offset 到 canonical 1-based stream sequence 的显式 mapping。

### 5.5 EventBus 与 subscriber

`InMemoryEventBus` 仅保留为测试/兼容 adapter，接口必须删除 framework `EventRecord`：

```python
def publish(event: Event | EventEnvelope) -> EventEnvelope:
    ...
```

分发要求：

- 标准 subscriber 始终收到 `EventEnvelope`；
- compatibility callable 在其一版期限内也只收到 `EventEnvelope`；
- 删除 `isinstance(event, EventRecord)` 和原 record 特殊投递；
- 不再允许 callback 根据 publisher 输入类型收到不同对象；
- callable shim 到期后删除，production durable consumer 使用 stable consumer contract；
- 删除旧特例不得削弱 subscriber identity、exception cause 和测试 adapter 的可诊断性。

### 5.6 framework `EventRecord` 删除

删除范围包括：

- `framework/events/recorder.py` 中的 `EventRecord`；
- `to_event()`、`to_envelope()`、legacy `from_dict()`；
- `framework/events/__init__.py` 的导出；
- `framework/workflow/__init__.py` 中对 framework `EventRecord` 的 re-export；
- `bus.py` 的 import、union type、conversion 和 mixed delivery branch；
- production/tests 中对 framework `EventRecord` 的构造或类型判断；
- 只为了证明 legacy mixed-type 行为而存在的断言。

不得删除：

- 历史 fixture；
- legacy importer/upcaster；
- 同样业务规则的 replacement tests；
- infrastructure storage adapter 在完成其 canonical 迁移前所需的 read DTO。

---

## 6. 数据映射

| Legacy framework record | Canonical target | 规则 |
| --- | --- | --- |
| `event_id` | `StoredEvent.event_id` | 原样保留；缺失时仅允许 registered deterministic derivation，否则 quarantine，禁止随机生成 |
| `event_type` | `StoredEvent.event_type` | 必须通过 schema catalog |
| `schema_version` | `data_schema` + envelope schema | 经注册 upcaster 映射 |
| `run_id` | `business_context.run_id` + `stream_id=run:<run_id>` | 先执行 path-safe validation |
| `payload` | post-security canonical payload | 不允许先落 raw secret 再脱敏 |
| `occurred_at` | `occurred_at` | 保留原时间；缺失 quarantine |
| file read time | 不映射 | 不得伪造成 occurrence time |
| `workflow_id/step_id` | `business_context` | duplicate context 必须一致 |
| `trace_id/span_id/parent_span_id` | `trace` | legacy invalid W3C ID 只保留历史关联，不向外注入 |
| `component` | `producer.component` | 不放进自由 metadata 猜测 |
| `run_id` correlation default | `correlation_id` | 仅按已登记 legacy mapping；不得覆盖显式合法值 |
| JSONL line offset `N` | migration mapping -> stream sequence | 明确 0-based/1-based，不靠隐式 `+1` 散落在调用方 |

---

## 7. 分阶段迁移

### M0：Inventory 与失败基线

- 列出 framework `EventRecord` 的所有 production imports、writers、readers、tests 和 public exports。
- 冻结代表性 `newsroom.event_record.v1`、envelope v1、storage flat JSON 和 run JSONL fixtures。
- 为 dual ledger、mixed list type、mixed subscriber payload、missing time、offset boundary 建立失败测试。
- 明确 framework/storage/inspection 三类同名或近似 record 的 keep/adapt/delete 归属。

退出门槛：清单完整，所有已知 schema/字段变体都有 fixture 或 quarantine 预期。

### M1：Canonical reader 与 compatibility projection

- 先完成父 change 的 `StoredEvent`、schema catalog、security projector 和 legacy upcaster 基础。
- legacy reader 接受合法已知记录，拒绝或 quarantine 冲突/未知/缺失事实。
- 增加 `StoredEvent -> EventEnvelope` bounded compatibility projection。

退出门槛：历史 fixture 可 deterministic import；源文件 checksum 不变；无 `now()` 回填。

### M2：Recorder 单模型 API

- `EventRecorder.emit()` 返回 `EventEnvelope` compatibility projection。
- `EventRecorder.list_events()` 永远返回 `list[EventEnvelope]`。
- 删除 `_records`；不得形成另一套 authoritative `_envelopes` memory ledger。
- production execution context 改注入 scoped emitter/runtime。

退出门槛：无 mixed list type；所有 emitted identity 与 canonical accepted identity 相同。

### M3：Workflow、checkpoint 与 projection cutover

- workflow/Harness 在执行中 durable append。
- run resume/cancel/rerun 等 operation event 也必须走同一 canonical emitter，不得直接向 projection 文件追加 flat record。
- checkpoint 从 `len(list_events())` 迁移到 durable sequence/event id。
- finalizer 从 store 生成 redacted `events.jsonl` 和 watermark/checksum。
- 同一 release 禁用 post-run JSONL-to-store indexing。

退出门槛：只有一个 authoritative writer；crash-before-finalize 后事件仍可查询；无双 dispatch。

### M4：Bus 与 caller cleanup

- 所有 owned callers 迁移到 canonical API 或 envelope compatibility API。
- EventBus 删除 `EventRecord` input 和 legacy record payload 特例。
- 普通 callable 在 bounded release 中只接收 envelope；新 production consumer 使用 stable contract。

退出门槛：同一 subscriber 对所有允许输入只收到一种类型；production 无 framework `EventRecord` import。

### M5：兼容发布与审计

- 保留历史 read/upcast；不保留 legacy write。
- 运行 shadow read/export compare，但不得双写或双 dispatch。
- 观察一个明确记录的 migration release，验证 query、checkpoint、projection 和 external consumer。

退出门槛：migration report 无未处置 P1 conflict；owned callers 为零；rollback drill 通过。

### M6：删除

- 删除 framework `EventRecord`、mixed branch、dual ledger 和 legacy-only tests。
- 删除到期 callable/EventRecorder shim，或将类名重新定义为无 legacy 行为的正式 scoped facade；不得保留隐藏 compatibility branch。
- 保留 bounded historical importer，直到父 change 的历史数据支持期限结束。

退出门槛：静态搜索、targeted/full tests、strict OpenSpec、compile 和 smoke 全部通过。

---

## 8. Compatibility 期限与删除门槛

### 8.1 期限

compatibility facade 只允许存在 **一个明确记录的 migration release**。期限从 canonical writer cutover 的 release 开始，不从 PRD 合并或测试代码落地开始计算。

### 8.2 删除前必须满足

- [ ] production code 对 `framework.events.EventRecord` 的 imports/constructors/type checks 为零；
- [ ] `EventRecorder._records` 为零；
- [ ] `list_events()` 无 mixed return；
- [ ] EventBus 无 `EventRecord` 参数或特殊分发；
- [ ] checkpoint 已使用 durable sequence/event id；
- [ ] `events.jsonl` 已由 store projection 生成；
- [ ] post-run indexing 已禁用并删除；
- [ ] 历史 fixture import/quarantine 报告通过；
- [ ] API/CLI/MCP/inspection response compatibility 通过；
- [ ] migration release 期间无未知 consumer 仍依赖 flat record；
- [ ] rollback drill 不删除 accepted event、不复用 sequence、不重复外部副作用。

### 8.3 不允许以兼容为理由保留

- runtime `EventRecord` writer；
- `_records/_envelopes` 双账；
- `list[Any]`；
- mixed subscriber payload；
- JSONL 回灌 live store；
- missing time 填当前时间；
- 永久 callable shim；
- 双写或双 dispatch。

---

## 9. 验收标准

### 9.1 Recorder contract

- [ ] `emit()` compatibility result 是 `EventEnvelope`，不是 framework `EventRecord`。
- [ ] `emit()`、store 和 projection 使用同一个 `event_id`。
- [ ] `list_events()` 在空、非空、filter、直接 record 后都只返回 envelope。
- [ ] `record(envelope)` 与 `emit()` 的结果进入同一可观察集合或同一 canonical reader，不再分账。
- [ ] failure 不留下只在一个列表中的半条事件。

### 9.2 Bus contract

- [ ] `publish()` 不接受 framework `EventRecord`。
- [ ] 标准 subscriber 与 bounded callable 对同一发布都接收 envelope。
- [ ] 不存在 `isinstance(event, EventRecord)` 分支。
- [ ] subscriber 异常仍保留 typed wrapper 和 original cause。
- [ ] InMemory Bus 明确仅是 test/compat adapter，不冒充 durable delivery。

### 9.3 Workflow 与 checkpoint

- [ ] workflow/Harness required transition 在推进状态前完成 durable append。
- [ ] checkpoint 保存 durable stream sequence/event id，不使用 recorder list length。
- [ ] parallel step context 不因 shared mutable recorder context 串线。
- [ ] store failure fail closed，不降级 memory-only。

### 9.4 JSONL 与历史迁移

- [ ] 新 `events.jsonl` 按 durable sequence 有序且已 redacted。
- [ ] manifest 含 projection high watermark/checksum。
- [ ] export 不回灌 store。
- [ ] workflow event 与 run operation event 都经同一 canonical writer/projection，不在一个文件中混用 flat 与 nested schema。
- [ ] v1 record/envelope 已知 fixture 可 deterministic read/upcast。
- [ ] missing time、unknown schema、context conflict 和 same-id collision 被 quarantine/typed failure。
- [ ] migration dry-run 不修改源文件。
- [ ] 0-based offset 到 1-based sequence 的首条、末条、空文件和 resume boundary 均不漏不重。

### 9.5 删除完成度

- [ ] framework `EventRecord` 类和 public export 已删除。
- [ ] production imports、constructors、type checks 为零。
- [ ] legacy behavior tests 已替换为新 contract tests，而不是简单删除覆盖。
- [ ] infrastructure storage model 的处置与父 PRD 一致，没有因同名误删。
- [ ] compatibility facade 到期后没有隐藏 feature flag 可以恢复 legacy writer。

---

## 10. 测试矩阵

| 层级 | 必测内容 |
| --- | --- |
| Unit | Event/Envelope/canonical mapping、filter、schema validation、redaction、conflict/quarantine |
| Recorder | emit/list/record 单模型、identity 保持、filter、failure atomicity |
| Bus | 所有 subscriber 只收 envelope、异常链、subscribe/unsubscribe snapshot 行为 |
| Workflow | started/step/review/checkpoint/terminal 事件 durable append |
| Checkpoint | legacy offset mapping、resume boundary、parallel attempt isolation |
| Projection | deterministic JSONL、watermark/checksum、secret-free、source read-only |
| Migration | v1 record/envelope/storage JSON fixtures、unknown/missing/conflict quarantine |
| Interfaces | run events API/CLI/MCP/inspection 核心字段兼容与 sequence pagination |
| Architecture | framework 不 import infrastructure；interfaces 经 application service |

建议 targeted 命令：

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\framework\events `
  tests\framework\contracts\test_event_trace_contract.py `
  tests\framework\workflow\runtime `
  tests\framework\workflow\checkpoint `
  tests\interfaces\services\test_run_inspection_service.py -q
```

最终 gate：

```powershell
openspec validate durable-event-runtime --strict
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
git diff --check
```

如本阶段修改 storage migration 或 interface response contract，还必须运行对应 adapter conformance、PostgreSQL integration 和 API/CLI/MCP targeted suites。

---

## 11. OpenSpec 任务映射

本 PRD 不建立独立 tasks 文件，直接映射现有 `durable-event-runtime/tasks.md`：

| 本 PRD | OpenSpec task |
| --- | --- |
| M0 inventory/fixtures | 1.1、1.3、1.4 |
| M1 canonical reader/projection | 2.1-2.5 |
| M2 recorder 单模型 | 5.1 |
| M3 workflow/checkpoint/JSONL cutover | 5.2、5.3、5.6、8.4 |
| M4 bus/caller cleanup | 4.1-4.5、9.3 |
| M5 migration audit | 9.1-9.3、9.5 |
| M6 删除与最终验证 | 9.4、10.1-10.5 |

实施时应在现有 task 下增加测试细项，而不是复制一套会独立漂移的 checklist。

---

## 12. 预计变更面

### Framework events

```text
framework/events/event.py
framework/events/envelope.py
framework/events/recorder.py
framework/events/bus.py
framework/events/publisher.py
framework/events/subscriber.py
framework/events/__init__.py
```

### Workflow runtime

```text
framework/workflow/runtime/execution_context.py
framework/workflow/runtime/runtime_event_bridge.py
framework/workflow/runtime/execution_loop.py
framework/workflow/runtime/checkpoint_coordinator.py
framework/workflow/runtime/outcome_finalizer.py
framework/workflow/runtime/runner.py
framework/workflow/operations/service.py
framework/workflow/inspection/inspector.py
framework/workflow/checkpoint/*
```

### Storage 与 interfaces

```text
infrastructure/storage/events/*
infrastructure/storage/postgres/event_store.py
interfaces/services/run_inspection_service.py
interfaces/api/*run events surface*
interfaces/cli/*run events surface*
interfaces/mcp/*run events surface*
```

### Tests

```text
tests/framework/events/*
tests/framework/contracts/test_event_trace_contract.py
tests/framework/workflow/runtime/*
tests/framework/workflow/checkpoint/*
tests/infrastructure/storage/test_event_store.py
tests/infrastructure/storage/postgres/test_postgres_event_store.py
tests/interfaces/services/test_run_inspection_service.py
tests/interfaces/api/test_api_run_operations.py
tests/interfaces/api/*run events tests*
tests/interfaces/cli/*run events tests*
tests/interfaces/mcp/*run events tests*
```

---

## 13. Rollout 与 rollback

### 13.1 Cutover 前

- legacy writer 保持唯一 active writer；
- canonical reader/importer 和 staging store 可运行；
- shadow compare 只比较，不 dispatch；
- 发现 conflict 时停止 cutover，不修改源历史。

### 13.2 Cutover release

- canonical durable runtime 成为唯一 writer；
- `EventRecorder` 只作为 bounded projection facade；
- `events.jsonl` 改由 store export；
- post-run indexing 同 release 禁用；
- callable 不再收到 record。

### 13.3 Cutover 后 rollback

不得返回 unpersisted legacy Bus/Recorder writer。允许回滚 reader、dispatcher 或 application binary，但必须：

- 保留所有 accepted canonical events；
- 不删除或复用 stream sequence；
- 从 high watermark 重建 projection；
- 保留 pending delivery/checkpoint；
- 不重新广播已完成 external effect；
- 保持 schema/security/integrity gates 开启。

### 13.4 删除 release

完成一版 compatibility observation 和 migration audit 后，删除 framework `EventRecord` 及到期 shim。删除不是可选 cleanup，而是本 PRD 的 Definition of Done。

---

## 14. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 把 EventEnvelope 当最终 durable model | 随后再次大迁移 | production 直接接 `StoredEvent`；Envelope 只作 bounded projection |
| framework/storage 同名 EventRecord 误删 | storage adapter 和查询损坏 | inventory 使用 fully-qualified name；分开 migration tests |
| caller 只做 `.event_type -> .event.event_type` 机械替换 | 仍依赖 memory recorder | production caller 直接迁移 reader/emitter port |
| cutover 双写或双 dispatch | duplicate event/effect | 单 writer；shadow compare 不 dispatch；stable identity |
| legacy offset off-by-one | resume 漏事件或重复 | mapping table + first/last/empty/boundary fixtures |
| JSONL 格式变化破坏离线工具 | inspection/recovery 失败 | 保留 path/core response；versioned reader/upcaster；projection fixtures |
| 删除旧测试掩盖回归 | 行为失去保护 | 将 legacy 测试改写成 canonical contract tests |
| missing time 被填 now | 历史不可审计 | quarantine；禁止 fallback current time |
| raw payload 先落盘 | secret 永久泄漏 | security projection 必须发生在首次 durable write 前 |

---

## 15. Definition of Done

只有同时满足以下条件，阶段 19A 才能标记 `IMPLEMENTED`：

1. production workflow/Harness 使用 canonical durable emitter，不依赖 legacy record list；
2. bounded `EventRecorder` facade 的 emit/list 类型统一且不双账；
3. `events.jsonl` 来自 canonical store projection，历史记录可 deterministic read/upcast/quarantine；
4. EventBus 不接受或特殊投递 framework `EventRecord`；
5. framework `EventRecord`、public export、production imports 和 legacy-only branches 已删除；
6. compatibility release 和 deletion gate 有实际 evidence，不是仅在文档中声明；
7. targeted tests、strict OpenSpec、compile、smoke 和 migration/rollback evidence 全部通过；
8. 变更按清晰 commit 边界提交，未混入现有无关 dirty-worktree 修改。

最终结构应是：

```text
typed Event input
  -> canonical EventRuntime/StoredEvent
  -> durable store/delivery/replay
  -> compatible EventEnvelope/read projection
  -> redacted events.jsonl

不存在：
  framework EventRecord
  _records + _envelopes
  mixed list return
  mixed subscriber payload
  JSONL -> live store 回灌
```
