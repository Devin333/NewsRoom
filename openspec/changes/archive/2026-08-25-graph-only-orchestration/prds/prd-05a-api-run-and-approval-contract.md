# 叶子 PRD 05a：API Run、Status 与 Approval Application Contract

## 目标

冻结 API major schema，并将 run response/status/inspection/replay/cancel/signal/approval decision 迁移到 Graph application service。

## 任务来源与前置

- 根任务：`tasks.md` 7.1-7.2。
- 前置：03b、04a；approval backend 依赖 02a/02c 的 durable Wait/side-effect。
- 后续：05b-05d 消费 schema。

## 允许修改

- `interfaces/api/**`、`interfaces/services/**` 的 Graph application contract、OpenAPI models、routers and error mapping。
- API run/inspection/approval/wait tests。

## 不允许修改

- API 不直接构造 scheduler/executor/store，不在 route 层实现 resume/routing/state patch。
- 新 schema 不保留 `workflow_id/version/ref` alias。

## 完成标准

1. 所有 run-facing response 只输出 Graph identity、node instance、wait cause 和 bounded status。
2. cause durable commit 后由 Harness 自动 resume；API 只提交 decision 或读取 application result。
3. legacy input、unknown schema、identity mismatch 映射为 typed error/quarantine。

## 验证与证据

```powershell
python -m pytest tests/interfaces/api tests/interfaces/services -q
python -m pytest tests/interfaces/api/test_openapi_graph_runs_contract.py tests/interfaces/api/test_graph_run_inspection_api.py -q
```

提交 OpenAPI major contract、route/application boundary 和 error evidence。
