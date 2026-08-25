# 叶子 PRD 02e：SubAgent、Worker、Context 与 Runtime Cleanup

## 目标

把 SubAgent、Worker、Memory、Skill、LLM structured output、Context/RAG 和 budget scope 统一到 Graph identity，清理 active v1/v2、legacy defaults 和 flat runtime exports。

## 任务来源与前置

- 根任务：`tasks.md` 3.11-3.18。
- 前置：02a-02d；03a/03b/04b 会消费本叶子的 context、worker 和 budget contract。

## 允许修改

- `framework/harness/subagents/**`、workers、context、memory/governance/skill/llm observability 和 task-plan consumers。
- SubAgent v3 invocation/transcript/receipt/bundle、Graph ContextEnvelope、budget scope、RAG session schema。

## 不允许修改

- 不保留 live v1/v2 fallback、`workflow_id` authority、`legacy-global-budget` default 或 `context_payload()` compatibility facade。
- 不把 dynamic stage 变成 outer routing owner。

## 完成标准

1. production writer/reader/store 只接受 Graph-only major schema；历史版本仅由隔离工具识别。
2. context snapshot/cache/materializer、worker/result/transcript、skill/LLM facts 共享 exact Graph/stage/execution identity。
3. 无 Graph scope 的 production budget/tracker/admission fail closed；standalone capability 明确标记 standalone。

## 验证与证据

```powershell
python -m pytest tests/framework/harness/subagents tests/framework/harness/context tests/framework/agent tests/framework/shared -q
python -m pytest tests/architecture/test_framework_runtime_contract_cleanup.py tests/architecture/test_skill_runtime_packaging.py -q
```

提交 Graph v3/context/budget cleanup evidence；不要在本叶子删除全部 legacy package。
