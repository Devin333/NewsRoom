# 叶子 PRD 07b：Documentation 与 Stale Reference Audit

## 目标

更新架构文档、运行手册、CLI/API/MCP/SDK 文档和 Research composition 文档，清理 active stale references，并明确历史 quarantine 与 Graph-only control boundary。

## 任务来源与前置

- 根任务：`tasks.md` 10.5-10.6。
- 前置：07a、06d；文档必须与 live source/public schema 一致。
- 后续：07c。

## 允许修改

- repository docs、OpenSpec design/proposal/PRD evidence、CLI/API/MCP/Research runbook。
- stale reference audit allowlist 和 documentation tests。

## 不允许修改

- 不用文档声明替代未通过的 compile/smoke/zero-reference gate。
- 历史说明可以保留，但必须明确是 history/quarantine，不得暗示可恢复旧 runtime。

## 完成标准

1. active docs 统一表述 Graph outer orchestration + AgentLoop inner loop。
2. `Workflow*` 名称只命中具体历史说明或 allowlist，不允许整目录 wildcard。
3. API/CLI/MCP/SDK 文档与 Graph major schema、Wait cause、approval decision 一致。

## 验证与证据

```powershell
rg -n "WorkflowRunner|WorkflowExecutor|AgentLoopStepRunner|DataBuffer|resume-workflow|workflow_id" README.md docs openspec --glob '*.md' --glob '*.yaml'
openspec validate --all --strict
```

提交 stale-reference report、allowlist 和 docs review evidence。
