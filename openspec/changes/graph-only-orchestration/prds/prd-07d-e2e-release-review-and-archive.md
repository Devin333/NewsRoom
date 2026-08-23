# 叶子 PRD 07d：E2E Release Review 与 Archive

## 目标

完成最终 Graph static/dynamic/approval/recovery/replay/artifact/history 验收，审查所有职责 slice 的提交和 evidence，并在确实满足完成定义后归档 change。

## 任务来源与前置

- 根任务：`tasks.md` 11.5-11.9。
- 前置：07a-07c、全部 01-06 叶子；所有任务 checkbox 和 evidence 必须可追溯。
- 后续：无；这是最终叶子。

## 允许修改

- final acceptance matrix、release review、archive metadata、根 `tasks.md` 最终勾选。
- 只修复 release review 明确发现的根因；不接受临时 bypass。

## 不允许修改

- 不伪造 managed-environment qualification、rollback drill、pointer switch 或 production sign-off。
- 不在仍有 P0/P1/P2 active gap、失败测试、legacy caller 或未登记 history store 时 archive。

## 完成标准

1. static/dynamic Research、reader repair、approval wait/resume、crash recovery、offline replay、artifact inspection 全部通过。
2. replay 的 worker/tool/LLM/retrieval/memory-write/publication count 符合 zero-side-effect 规则；legacy input 只 quarantine。
3. 每个职责 slice 有独立 commit、focused verification、`tasks.md` checkbox 和 evidence。
4. 无 compatibility facade、fallback executor、legacy writer、hidden feature flag、dual store 或未登记 history store。
5. 只有当 `openspec status` 显示任务全部完成且 strict validation 通过，才执行 archive。

## 验证命令

```powershell
python -m scripts.dev compile
python -m scripts.dev smoke
openspec validate graph-only-orchestration --strict
openspec validate --all --strict
```

提交 final release review；归档动作必须是单独、可审查的最后提交。
