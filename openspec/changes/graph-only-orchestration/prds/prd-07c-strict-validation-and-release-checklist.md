# 叶子 PRD 07c：Strict Validation 与 Release Checklist

## 目标

执行最终 compile、focused/full tests、smoke、source/export/schema scan，并把所有 release gate 结果登记为可复核 evidence。

## 任务来源与前置

- 根任务：`tasks.md` 10.7-10.8、11.1-11.4。
- 前置：07a、07b、06d；不得在这里跳过失败或降低断言。
- 后续：07d。

## 允许修改

- release checklist、evidence、architecture/source validation tests、根 `tasks.md` 对应勾选。
- 发现根因时可修复对应 owner，但应另开回到叶子任务的 commit，不把 release checklist 当 workaround。

## 不允许修改

- 不以历史测试快照替代本轮结果，不伪造 smoke、production qualification 或 external sign-off。
- 不在失败时勾选任务或标记 change complete。

## 完成标准

1. `compile`、范围匹配 focused tests、`scripts.dev test`、mandatory `scripts.dev smoke` 全部通过。
2. production import/export/schema scan 证明 Workflow、flat state/checkpoint/replay、legacy Artifact publisher、SubAgent v1/v2 和 nullable scope 不再是 active authority。
3. static/dynamic/recovery、replay/no-worker、history quarantine、checksum、no fallback gate evidence 完整。

## 验证命令

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec validate graph-only-orchestration --strict
openspec validate --all --strict
```

提交本轮命令输出摘要、失败根因修复记录和 release checklist，不直接声明归档。
