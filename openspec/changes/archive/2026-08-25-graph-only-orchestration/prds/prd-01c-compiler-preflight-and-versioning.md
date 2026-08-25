# 叶子 PRD 01c：Compiler、Preflight 与 Version Pinning

## 目标

让 compiler、reader、validation 和 admission 只接受显式 checksum-valid Graph，删除 legacy compiler/fallback 的 live authority，并建立 unknown-version fail-closed 行为。

## 任务来源与前置

- 根任务：`tasks.md` 2.4-2.7。
- 前置：01b 的 Graph definition/run contract。
- 后续：01d 和 02a 使用本叶子的 preflight result、schema pin 和 diagnostics。

## 允许修改

- `framework/harness/graph/compiler.py`、`validation/**`、`versioning.py`、`reference.py` 和 registry/resolver。
- `HarnessRunSpec` admission/preflight caller、schema catalog 和 fail-closed errors。
- compiler、unknown construct/version、dual declaration、no-worker-before-preflight tests。

## 不允许修改

- 不在本叶子激活 Research physical dispatcher 或外部接口。
- 不用 metadata inference、`graph=None` fallback、`entry_step_id`、`routing_rules` 或 legacy condition conversion 绕过 validation。

## 完成标准

1. `HarnessGraphCompiler` 只接受 explicit Graph definition，输出 pinned normalized Graph 和 checksum。
2. preflight 在 `RUN_CREATED`、checkpoint、artifact、worker、publication mutation 前运行并失败关闭。
3. unknown schema/version/construct、legacy Graph ref、missing binding、checksum mismatch 有稳定 error code。
4. registry 只注册 live Graph schemas；历史 reader 不能从 production composition 到达。

## 验证与证据

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness/graph tests/framework/harness/control_plane/test_graph_state.py -q
python -m pytest tests/scripts/test_graph_only_migration.py tests/architecture/test_harness_graph_authority.py -q
```

提交 compiler/preflight/version evidence，确认 worker call count 在 preflight failure 时为零。
