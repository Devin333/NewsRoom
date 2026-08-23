# Graph-only Orchestration 叶子 PRD

## 使用方式

这里的文件是 [prd-split-index.md](../prd-split-index.md) 下面的可执行叶子切片。每个叶子 PRD 对应一组连续的 `tasks.md` 任务和一个明确 owner boundary，适合单独交给 Codex 执行、验证和提交。

叶子 PRD 不是新的架构规范。必须同时遵守上级 [总 PRD](../prd.md)、`proposal.md`、`design.md`、对应 `specs/**/spec.md` 和根级 `tasks.md`。特别是：

- Graph 是唯一 outer orchestration authority；Harness 决定 routing、gate、budget、authorization、memory write 和 publication。
- LLM、Tool、Skill、SubAgent、AgentLoop 和业务 worker 只能产生 candidate/evidence。
- `step_id` 可以作为 Graph definition label，但 durable fact 至少闭合到 `run_id + graph_ref + graph_checksum + node_instance_id`；activity fact 还要有 `activity_id + attempt`。
- Artifact 产品能力必须保留；只能删除 legacy Workflow bridge/writer/reader 和旧执行分类。
- 叶子完成后更新根级 `tasks.md` 和 `evidence/`，使用 path-scoped commit；不要在叶子文档中维护第二个进度数字。

## 依赖层

```text
01a -> 01b -> 01c -> 01d
                  |
                  v
02a -> 02b -> 02c -> 02d -> 02e
                              |
                              v
03a -> 03b -> 03c -> 03d -> 03e
                              |
             +----------------+----------------+
             v                                 v
04a -> 04b -> 04c                    05a -> 05b -> 05c -> 05d
04d -> 04e                                      |
             +----------------+----------------+
                              v
                    06a -> 06b -> 06c -> 06d
                              |
                              v
                    07a -> 07b -> 07c -> 07d
```

`04` 与 `05` 在 `03` 完成后可以并行推进，但 `06` 必须等两者完成；`07` 是最终收口，不应提前修改 canonical requirements 来掩盖实现缺口。

## 叶子清单

| ID | 文件 | 任务范围 | owner |
|---|---|---|---|
| 01a | `prd-01a-baseline-and-freeze.md` | 1.1-1.9 | inventory / freeze |
| 01b | `prd-01b-graph-namespace-and-run-contract.md` | 2.1-2.3 | Graph namespace / run contract |
| 01c | `prd-01c-compiler-preflight-and-versioning.md` | 2.4-2.7 | compiler / preflight / version |
| 01d | `prd-01d-leaf-lifecycle-and-contract-tests.md` | 2.8-2.10 | leaf lifecycle / contract tests |
| 02a | `prd-02a-control-plane-graph-identity.md` | 3.1-3.3 | control plane / durable phase |
| 02b | `prd-02b-control-nodes-and-taskplan.md` | 3.4-3.6 | control nodes / activity binding |
| 02c | `prd-02c-side-effect-and-memory-authority.md` | 3.7 | side-effect / memory authority |
| 02d | `prd-02d-recovery-result-and-replay.md` | 3.8-3.10 | result / recovery / replay |
| 02e | `prd-02e-subagent-worker-context-cleanup.md` | 3.11-3.18 | SubAgent / worker / context cleanup |
| 03a | `prd-03a-artifact-owner-and-inspection.md` | 4.1-4.2, 4.6 | Artifact owner |
| 03b | `prd-03b-event-projection-and-operations.md` | 4.3-4.5, 4.11 | Event / application services |
| 03c | `prd-03c-graph-index-writer-reader.md` | 4.7, 4.12 | Graph index |
| 03d | `prd-03d-node-output-and-physical-dispatcher.md` | 4.10, 4.13 | node-output / dispatcher |
| 03e | `prd-03e-live-caller-migration-and-owner-tests.md` | 4.8-4.9 | caller migration / owner tests |
| 04a | `prd-04a-research-graph-composition.md` | 5.1-5.3, 5.6 | Research composition |
| 04b | `prd-04b-dynamic-taskplan-and-reader-repair.md` | 5.4-5.5 | dynamic TaskPlan / repair |
| 04c | `prd-04c-research-e2e-and-boundaries.md` | 5.7-5.8 | Research acceptance |
| 04d | `prd-04d-agentloop-graph-activity-and-artifacts.md` | 6.1-6.2 | AgentLoop activity / artifacts |
| 04e | `prd-04e-agentloop-state-approval-and-cleanup.md` | 6.3-6.7 | AgentLoop state / cleanup |
| 05a | `prd-05a-api-run-and-approval-contract.md` | 7.1-7.2 | API application contract |
| 05b | `prd-05b-cli-graph-surface.md` | 7.3 | CLI |
| 05c | `prd-05c-mcp-sdk-and-openapi.md` | 7.4, 7.6 | MCP / SDK / OpenAPI |
| 05d | `prd-05d-approval-validation-and-migration.md` | 7.5, 7.7-7.8 | approval validation |
| 06a | `prd-06a-history-reader-and-classifier.md` | 8.1-8.4 | history reader / classifier |
| 06b | `prd-06b-quarantine-and-zero-side-effect.md` | 8.5-8.7, 8.10 | quarantine / safety |
| 06c | `prd-06c-history-isolation-and-migrator-removal.md` | 8.8-8.9, 8.11-8.12 | history isolation |
| 06d | `prd-06d-legacy-runtime-deletion-and-proof.md` | 9.1-9.11 | legacy deletion |
| 07a | `prd-07a-canonical-spec-capability-sync.md` | 10.1-10.4 | canonical specs |
| 07b | `prd-07b-docs-and-stale-reference-audit.md` | 10.5-10.6 | docs / stale audit |
| 07c | `prd-07c-strict-validation-and-release-checklist.md` | 10.7-10.8, 11.1-11.4 | validation |
| 07d | `prd-07d-e2e-release-review-and-archive.md` | 11.5-11.9 | final release |

## 单独运行约定

建议把叶子文件路径作为任务目标，例如：

```text
/goal F:\github\NewsRoom\openspec\changes\graph-only-orchestration\prds\prd-02c-side-effect-and-memory-authority.md
```

执行前先检查前置叶子是否已提交。执行后至少留下：实现 commit、范围匹配的测试命令、`git diff --check` 结果、对应 `tasks.md` 勾选和一份 `evidence/` 记录。若发现需要修改另一个叶子 owner 的代码，应停止扩张范围并记录依赖，而不是跨边界直接改造。
