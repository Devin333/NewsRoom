# 子 PRD 05：Public Interfaces 与 Approval

## 目标

将 API、CLI、MCP、SDK、Wait、approval decision、inspection、replay、cancel 和 signal 收敛为 Graph major contract；interface 层只调用 application service，不直接访问 executor、scheduler 或 store。

## 前置

完成 `prd-01`、`prd-02`、`prd-03`；`prd-04` 的 Research caller 可以并行，但 public contract 不得依赖业务内部实现。

## 任务来源

对应 `tasks.md` 的 **7.1-7.8**。

## 范围

- run response/status/inspection/replay/cancel/signal 和 approval decision 的 Graph schema major cutover。
- typed Graph Wait cause、approval application service、durable Wait registration、actor authorization、scope/idempotency 和 commit 后由 Harness 自动 resume。
- API/CLI/MCP/SDK 的 Graph identity、OpenAPI schema、JSON/human output、help、generated contract 和 client method。
- 删除 `buffer_updates`、caller-supplied `node_updates`、`resume_metadata`、`DataBuffer` 和旧 resume-workflow/approval surface。
- interface boundary tests，证明 external surface 不直接构造 scheduler、executor、store 或 legacy runtime。

## 不在范围内

不修改 Graph control-plane 决策，不在接口层实现恢复、路由、状态 patch 或 publication。历史 Workflow 输入只能得到 typed quarantine，不得由接口转换成 live run。

## 完成标准

- 新 major schema 只输出 Graph run/graph/node/wait identity 和 bounded cause，不携带 Workflow alias 或 mutation-shaped resume fields。
- approval decision 必须匹配当前 durable Graph run、Wait registration、evidence、actor、authorization、scope 和 idempotency。
- HTTP、CLI、MCP、SDK contract、OpenAPI 和 boundary tests 全部通过；旧 endpoint、字段、client method 零 active 引用。

## 建议验证

```powershell
python -m scripts.dev compile
python -m pytest tests/interfaces/api tests/interfaces/cli tests/interfaces/mcp tests/interfaces/sdk tests/sdk -q
python -m pytest tests/architecture/test_framework_public_api.py tests/architecture/test_research_boundaries.py -q
```

## 交付物

Graph public schema、approval/wait application service、API/CLI/MCP/SDK contract tests、client migration inventory 和 `tasks.md` 的 7.x 更新。
