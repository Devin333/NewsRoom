# 叶子 PRD 05c：MCP、SDK 与 OpenAPI Generated Contract

## 目标

把 MCP tools、Python SDK、OpenAPI schema 和 generated contract 统一到 Graph approval/Wait major surface，并验证 interface boundary。

## 任务来源与前置

- 根任务：`tasks.md` 7.4、7.6。
- 前置：05a、05b；public contract 不应等待 legacy cleanup 才能测试。
- 后续：05d、07b。

## 允许修改

- `interfaces/mcp/**`、`interfaces/sdk/**`、`sdk/python/**`、OpenAPI schema/export/contract tests。
- MCP stdio/server tools、SDK methods、generated payload/error schema。

## 不允许修改

- MCP/SDK 不直接构造 scheduler/executor/store，不拥有 approval routing 或 publication authority。
- 不在 generated schema 中保留 Workflow alias 或 mutation-shaped resume fields。

## 完成标准

1. MCP/SDK/API 对同一 Graph run/wait/approval contract 进行 round-trip。
2. unknown/legacy payload、cross-Graph identity、unauthorized actor 稳定拒绝。
3. boundary test 证明 external surface 只调用 application services。

## 验证与证据

```powershell
python -m pytest tests/interfaces/mcp tests/interfaces/sdk tests/sdk tests/interfaces/api/test_openapi_graph_runs_contract.py -q
python -m pytest tests/architecture/test_framework_public_api.py tests/interfaces/mcp/test_mcp_contracts.py -q
```

提交 MCP/SDK/OpenAPI contract evidence 和 generated schema diff。
