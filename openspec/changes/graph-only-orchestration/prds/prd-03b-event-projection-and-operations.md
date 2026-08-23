# 叶子 PRD 03b：Event Projection、Run Operation 与 Inspection

## 目标

将 event application/projection/reader、run operation、inspection、cancel、signal、approval/replay composition 统一到 Graph application ports。

## 任务来源与前置

- 根任务：`tasks.md` 4.3-4.5、4.11。
- 前置：02a/02d；必须使用 durable Graph event identity。
- 后续：03c、05a、06b 依赖 event/read model availability semantics。

## 允许修改

- `framework/events/**` projection/read model、`interfaces/services/event_*`、run operation/inspection factory/service。
- Graph event application port、typed unavailable/quarantine response、durable context writer。

## 不允许修改

- interface 不直接访问 event store/executor；不恢复旧 Event/EventEnvelope facade。
- inspection `/steps` 不从 manifest terminal list 猜测实际 node instances。

## 完成标准

1. event stream/context/sequence/checksum 与 GraphRunIdentity exact match。
2. projection unavailable 返回 typed unavailable，不 silently fallback 到静态 manifest。
3. run operation/inspection/cancel/signal/replay 只通过 application service，不能调用 worker。
4. event projection writer/reader 已激活，projection watermark/checksum 可验证。

## 验证与证据

```powershell
python -m pytest tests/framework/events tests/interfaces/services/test_event_projection_service.py tests/interfaces/services/test_event_reader_service.py -q
python -m pytest tests/interfaces/services/test_run_inspection_projection.py tests/architecture/test_graph_event_application_boundary.py -q
```

提交 event application/projection evidence；列出 unavailable、pagination 和 replay-no-worker cases。
