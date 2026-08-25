# 叶子 PRD 06b：Quarantine、Replay Rejection 与 Zero Side Effect

## 目标

证明不可转换历史只能 typed quarantine，不能 resume、replay execution、worker、tool、LLM、retrieval、memory write 或 publication。

## 任务来源与前置

- 根任务：`tasks.md` 8.5-8.7、8.10。
- 前置：06a、02c/02d、03a/03b。
- 后续：06c、06d。

## 允许修改

- legacy rejection/quarantine application boundary、offline replay verifier、side-effect counters 和 adversarial fixtures/tests。
- typed diagnostics 和 history audit evidence。

## 不允许修改

- 不提供 legacy resume/replay/worker/publication fallback，不把 quarantine 结果放入 production queue/store。
- 不削弱 checksum、sequence、identity 或 side-effect 断言。

## 完成标准

1. identity missing/mismatch、checksum tamper、unknown schema、duplicate input 和 sequence gap 稳定 quarantine。
2. migration/classifier/replay 输入的 live LLM/tool/worker/retrieval/memory/publication count 永远为零。
3. history-only diagnostic 与 live Graph reader 的 import boundary 可机器检查。

## 验证与证据

```powershell
python -m pytest tests/scripts tests/framework/harness tests/infrastructure/storage/events -q
python -m pytest tests/architecture/test_harness_graph_authority.py tests/architecture/test_framework_runtime_contract_cleanup.py -q
```

提交 quarantine reason matrix、zero-call evidence 和 tamper cases。
