# 叶子 PRD 03c：Graph Artifact/Event Index Writer 与 Reader

## 目标

激活 Graph artifact/event index 的唯一 writer、reader 和 read-back authority，保证路径、checksum、sequence、idempotency 和 replay 一致。

## 任务来源与前置

- 根任务：`tasks.md` 4.7、4.12。
- 前置：03a、03b、02d。
- 后续：04c、05a、06d 依赖 canonical index。

## 允许修改

- `infrastructure/storage` Graph index store、event/artifact index adapters、Research composition 和 operator/read-back tooling。
- index contract、dry-run、replay、duplicate delivery、pointer authority tests。

## 不允许修改

- 不实现 pointer rollback、dual writer、shadow store 或 Workflow index compatibility。
- 不把 local attempt、budget、retry credit 或 event sequence 当作 resource generation。

## 完成标准

1. Graph index record 包含 run/graph/ref/checksum/node-instance/activity/attempt 所需 identity。
2. writer/read-back/replay 对 sequence gap、checksum mismatch、duplicate delivery、cross-run query fail closed。
3. production composition 只安装 Graph index writer/reader，旧 pointer adapter 无 active caller。

## 验证与证据

```powershell
python -m pytest tests/infrastructure/storage tests/interfaces/composition/test_research_graph_artifacts.py -q
python -m pytest tests/architecture/test_graph_artifact_owner_boundary.py tests/architecture/test_harness_durable_event_boundary.py -q
```

提交 index read-back/replay evidence 和 production caller inventory。
