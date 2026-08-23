# 叶子 PRD 05d：Approval Validation、Client Migration 与 Context Cleanup

## 目标

完成 approval decision 的 durable identity/evidence/authorization/idempotency 校验，清理旧 client surface，并删除共享 buffer/state patch 字段。

## 任务来源与前置

- 根任务：`tasks.md` 7.5、7.7-7.8。
- 前置：05a-05c、02c；需要 durable Graph Wait registration。
- 后续：06d、07b。

## 允许修改

- approval application service、decision validator、Wait registration/evidence/actor/scope/idempotency。
- client inventory、release/deprecation docs、resume context models and tests。

## 不允许修改

- checkpoint 不由 approval context 校验或修改；恢复/replay owner 仍由 Harness 管理。
- 不保留 `buffer_updates`、caller `node_updates`、`resume_metadata` 或旧 approval endpoint/client method。

## 完成标准

1. approval decision 必须匹配当前 durable run、Graph checksum、node/wait registration、evidence、actor、authorization 和 scope。
2. duplicate decision 幂等；stale/cross-Graph/tampered decision fail closed。
3. cause commit 后只有 Harness 自动 resume，外部 caller 不能提交 routing/state patch。
4. client migration inventory、major cutover date 和旧 surface zero-reference 可审计。

## 验证与证据

```powershell
python -m pytest tests/interfaces/api tests/interfaces/cli tests/interfaces/mcp tests/interfaces/sdk tests/framework/harness -q
rg -n "buffer_updates|node_updates|resume_metadata|resume-workflow|resume_context" interfaces sdk --glob '*.py'
```

提交 approval validation matrix、client inventory 和 context cleanup evidence。
