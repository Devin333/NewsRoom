# Graph-only Orchestration 子 PRD 索引

## 1. 用途

`prd.md` 是本 change 的总规范，本文档把它拆成可以单独执行和单独提交的 7 个实现切片。子 PRD 只负责执行范围和验收边界；产品目标、Graph authority、Artifact 保留约束、历史 quarantine 和无回滚 direct-cutover 规则仍以 [总 PRD](F:/github/NewsRoom/openspec/changes/graph-only-orchestration/prd.md) 为准。

不要把子 PRD 当成 7 个互相独立的架构设计。它们共享同一个 `GraphRunIdentity`、同一个 Harness control plane 和同一个 `tasks.md`。拆分的目的是缩小每次运行、审查和提交的范围，不是允许平行创建第二套 runtime。

## 2. 执行顺序

```text
prd-01 Graph contract / identity
        |
        v
prd-02 Harness control plane / admission
        |
        v
prd-03 Domain-neutral owners / storage
        |
        +-------------------+
        v                   v
prd-04 Research / AgentLoop   prd-05 Public interfaces / approval
        \                   /
         v                 v
      prd-06 History / legacy cleanup
                    |
                    v
      prd-07 Spec sync / release gates
```

推荐使用以下路径单独启动每个任务：

```text
F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prd-01-graph-contract-and-identity.md
F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prd-02-harness-control-plane-and-admission.md
F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prd-03-domain-neutral-owners-and-storage.md
F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prd-04-research-and-agentloop.md
F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prd-05-public-interfaces-and-approval.md
F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prd-06-history-and-legacy-cleanup.md
F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prd-07-spec-sync-and-release-gates.md
```

## 3. 每个子 PRD 的完成规则

1. 先读取总 PRD、`proposal.md`、`design.md`、对应 `specs/**/spec.md` 和本子 PRD。
2. 只修改本子 PRD列出的 owner、caller、tests、evidence 和文档；发现跨片依赖时，先在 `tasks.md` 或 `design.md` 记录，不通过 compatibility facade 绕过边界。
3. 生产代码遵守 `LLM as worker, Harness as control plane`：worker 只能提交 candidate/evidence，routing、gate、budget、authorization、memory write 和 publication 由 Harness 决定。
4. 完成后运行本子 PRD 的 focused checks，更新 `tasks.md` 对应任务和 `evidence/`，再做 path-scoped commit。不要在未完成最终门禁时把总 change 标为 complete。
5. `prd-07` 必须重新运行 `python -m scripts.dev compile`、`python -m scripts.dev smoke`、`openspec validate graph-only-orchestration --strict` 和 `openspec validate --all --strict`，并执行 zero-reference scan。

## 4. 细粒度叶子入口

阶段 PRD 只适合做一个阶段的整体 review；实际实现优先使用 [`prds/README.md`](F:/github/NewsRoom/openspec/changes/graph-only-orchestration/prds/README.md) 中的叶子 PRD。叶子文件按 `01a` 到 `07d` 编号，共 31 个：

| 阶段 | 叶子范围 | 适合一次处理的边界 |
|---|---|---|
| 01 | `01a-01d` | baseline、Graph namespace、compiler/preflight、leaf contract |
| 02 | `02a-02e` | control plane、control nodes、side-effect、recovery、worker/context |
| 03 | `03a-03e` | Artifact、Event/application、index、node-output、caller migration |
| 04 | `04a-04e` | Research composition、dynamic/repair、E2E、AgentLoop activity/state |
| 05 | `05a-05d` | API、CLI、MCP/SDK/OpenAPI、approval validation |
| 06 | `06a-06d` | history reader、quarantine、isolation、legacy deletion |
| 07 | `07a-07d` | canonical spec、docs audit、strict gates、final release |

叶子 PRD 通过 `tasks.md` 任务范围建立追踪，不单独创建 OpenSpec change。这样 `openspec status --change graph-only-orchestration` 仍然反映真实总进度，而每次执行可以把一个叶子作为独立目标，并以独立 commit 交付。

## 5. 状态来源

子 PRD 的状态不单独维护数字。当前进度以 `openspec status --change graph-only-orchestration --json` 和 `tasks.md` checkbox 为准；PRD 中的历史 evidence 不能覆盖当前 live source、测试和 working tree 事实。
