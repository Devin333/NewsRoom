# 叶子 PRD 06c：History Isolation 与 Active Migrator Removal

## 目标

将 history fixtures/raw records 移出 production import，删除 active migration pointer、dual-store writer、rollback switch 和 active legacy reader。

## 任务来源与前置

- 根任务：`tasks.md` 8.8-8.9、8.11-8.12。
- 前置：06a、06b；所有 live caller 已由 03-05 迁移。
- 后续：06d 做全局 deletion proof。

## 允许修改

- history fixture/report 目录、migration imports/exports、active reader/migrator removal。
- framework/business/interfaces/infrastructure/scripts 的 production import graph checks。

## 不允许修改

- 不删除明确仍被 offline audit 使用的冻结 fixture/report。
- 不保留 rollback/pointer switch/dual store 以“以后切换”。

## 完成标准

1. history-only record 只能从隔离工具路径读取，不能被 production composition import。
2. active migrator/legacy reader/dual-store writer/rollback code 删除或迁为 typed diagnostic。
3. 五个顶层包的 import graph 证明 history classifier 不可达 worker、resume、replay、side effect。

## 验证与证据

```powershell
python -m scripts.dev compile
python -m pytest tests/architecture tests/scripts -q
rg -n "migration|legacy.*reader|rollback|dual.?store|workflow" framework business interfaces infrastructure scripts --glob '*.py'
```

提交 history isolation inventory、删除列表和 import graph evidence。
