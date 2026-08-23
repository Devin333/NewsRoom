# 叶子 PRD 06a：History-only Reader 与 Record Classifier

## 目标

建立只能读取和分类 legacy record 的 history-only tooling，输出 source checksum、record identity 和 stable quarantine reason，不创建可恢复 Graph authority。

## 任务来源与前置

- 根任务：`tasks.md` 8.1-8.4。
- 前置：03b、03c、05a；需要识别 Graph/event/artifact schema。
- 后续：06b/06c。

## 允许修改

- migration-only schema readers、history classifier、dry-run inventory、migration-plan checksum/conflict detection。
- history fixture、offline tool 和纯诊断 tests。

## 不允许修改

- reader 不得写 Graph store、checkpoint、index、memory、artifact、publication，也不得调用 executor/worker。
- 不把 legacy record 转换成 live Graph run。

## 完成标准

1. manifest、events、checkpoints、replay bundles、indexes、cursor refs 和 provenance 都可分类。
2. unknown version、缺 Graph identity、缺 gate evidence、非法 path、checksum mismatch、sequence gap、ambiguous record 有稳定 reason code。
3. dry-run inventory、plan checksum、重复运行和冲突检测 deterministic。

## 验证与证据

```powershell
python -m pytest tests/scripts tests/infrastructure/storage/events tests/architecture -q
```

提交 history reader/classifier schema 和无 mutation evidence。
