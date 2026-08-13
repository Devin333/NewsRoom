# Obsolete Agent Session Runtime Retirement Evidence

本变更已完成实现、替换能力回归、历史 OpenSpec 归档和仓库级验证。实现提交为 `ba8745677c6240b2c5238513512fabdd03a4ae2d`；本文件及任务状态随后单独提交，最终归档提交会把 `legacy-runtime-cleanup` 同步为 canonical spec。

| Requirements | Accountable tasks | Implementation evidence | Test / verification evidence | Archive evidence | Status |
| --- | --- | --- | --- | --- | --- |
| ASR-FR-001 | 2.1..2.3, 3.1 | 删除 `framework/agent/session/**`、`framework/memory/session/**` 和专属测试目录；无 compatibility export、fallback store 或 no-op replacement。 | `tests/architecture/test_obsolete_agent_session_retirement.py` 目录缺失与生产导入边界断言；主回归 `2128 passed`；smoke `2096 passed`。 | 旧 shared-session change 已移入 `openspec/changes/archive/2026-08-13-paper-agent-shared-session-analysis`。 | VERIFIED |
| ASR-FR-002 | 1.1..1.3, 3.1..3.2 | 移除 `AgentSessionContextPolicy`、`AgentSpec.session_context_policy`、AgentLoop session collaborators 和 prompt hook；`AgentSpec.from_dict()` 对旧 key 抛出 `agent_session_context_policy_retired`。 | `tests/framework/agent/models/test_models.py`、architecture guard；`pytest tests/framework/agent tests/architecture -q`（包含于主回归）。 | 旧 change 的 shared-session requirements 未进入 canonical specs。 | VERIFIED |
| ASR-FR-003 | 1.3..1.4, 3.1..3.2 | `_child_inputs()` 不再把 metadata `session_id` 提升为 child input；AgentRunner 仍接收既有 `run_id`、`step_id`、`workflow_checkpoint_id`。 | `tests/framework/agent/subagents/test_subagents.py` 和 `test_trace_propagation.py` 精确断言输入与 runner kwargs；主回归通过。 | 无新的 session compatibility surface。 | VERIFIED |
| ASR-FR-004 | 1.4, 2.2, 3.2..3.3 | 保留能力按原 owner 存在：Harness RAG、Research reading、auth/projects、persisted conversation、cursor/compaction、durable subagent transcript。 | retained suite `121 passed`；主回归 `2128 passed, 23 deselected`；smoke `2096 passed, 23 deselected`。 | 未迁移或复制任何独立 session owner。 | VERIFIED |
| ASR-FR-005 | 4.1 | 使用 `openspec archive paper-agent-shared-session-analysis --skip-specs --yes`，未同步其 delta specs。 | 归档前后 canonical manifest 均为 144 份，聚合 SHA-256 均为 `775d966727f1cabdeca234b94160bd67348142f07363852c4a3d14a46ec64e40`；`git diff -- openspec/specs` 为空。 | 归档目录：`openspec/changes/archive/2026-08-13-paper-agent-shared-session-analysis`。 | VERIFIED |
| ASR-FR-006 | 1.1..1.3, 2.1..2.2, 3.1 | 生产源码静态扫描中旧类、旧包、旧 hook、fallback/no-op token 命中为 0；无隐藏 workspace input。 | architecture deletion/fallback guards、compile、smoke、strict OpenSpec validation 全部通过。 | 旧实现仅保留为归档历史，不作为运行时或 canonical contract。 | VERIFIED |
| Phase B production acceptance | 4.2, 5.1..5.4 | 实现提交 `ba8745677c6240b2c5238513512fabdd03a4ae2d`。 | `pytest ...` 主回归：`2128 passed, 23 deselected, 12 warnings`；`python -m scripts.dev compile` 通过；`python -m scripts.dev smoke`：`2096 passed, 23 deselected, 22 warnings`，source validation `error_count=0, warning_count=0`；`openspec validate remove-obsolete-agent-session-runtime --strict` 和 `openspec validate --all --strict`：`524 passed, 0 failed`。 | 历史 change 已使用 `--skip-specs` 归档；本 change 待正常归档。 | VERIFIED |

## Verification Log

| Check | Result | Notes |
| --- | --- | --- |
| `openspec validate remove-obsolete-agent-session-runtime --strict` | PASS | Change schema and requirements valid. |
| Focused framework / Harness / Research / retained capability / architecture tests | PASS | `2128 passed, 23 deselected, 12 warnings in 326.06s`. |
| Retained session/conversation regressions | PASS | `121 passed, 10 warnings`. |
| Historical archive canonical hash comparison | PASS | Pre/post aggregate identical: `775d966727f1cabdeca234b94160bd67348142f07363852c4a3d14a46ec64e40`. |
| `./.venv/Scripts/python.exe -m scripts.dev compile` | PASS | `compileall` completed without errors. |
| `./.venv/Scripts/python.exe -m scripts.dev smoke` | PASS | `2096 passed, 23 deselected, 22 warnings`; source validation has 0 errors and 0 warnings. |
| `openspec validate --all --strict` | PASS | `524 passed, 0 failed`. |
