# 叶子 PRD 03e：Live Caller Migration 与 Owner Contract Tests

## 目标

迁移 `scripts/dev.py`、`interfaces/services`、`infrastructure/research` 的 live legacy imports，并用 owner-level tests 证明迁移后行为没有回落到旧 runtime。

## 任务来源与前置

- 根任务：`tasks.md` 4.8-4.9。
- 前置：03a-03d；不能在 owner contract 未稳定时做 caller mass edit。
- 后续：04a、05a 和 06d 使用 zero-import evidence。

## 允许修改

- `scripts/dev.py`、`interfaces/services/**`、`infrastructure/research/**` 的 Graph application/physical port wiring。
- owner-level contract tests、composition tests、import architecture tests。

## 不允许修改

- 不保留旧 import 作为 fallback，不通过 `try/except ImportError` 隐藏 legacy dependency。
- 不把 interface 直接接到 executor/store。

## 完成标准

1. live caller 只依赖 Graph owner、application service 或明确 domain-neutral port。
2. Artifact catalog/quota/usage/GC/cost/alert、event projection、composition 和 caller 都有 owner-level contract test。
3. `business/research` 不依赖 `paper_radar`、legacy interface/infrastructure runtime。

## 验证与证据

```powershell
python -m scripts.dev compile
python -m pytest tests/interfaces/services tests/interfaces/composition tests/infrastructure/research -q
python -m pytest tests/architecture/test_research_boundaries.py tests/architecture/test_framework_runtime_contract_cleanup.py -q
```

提交 caller inventory、import scan 和 owner-level evidence。
