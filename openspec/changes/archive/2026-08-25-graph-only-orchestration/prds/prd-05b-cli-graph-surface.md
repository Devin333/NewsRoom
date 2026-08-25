# 叶子 PRD 05b：CLI Graph Surface

## 目标

将 CLI 命令、JSON/human output、help 和 approval decision surface 迁移到 Graph identity，删除 `resume-workflow`、DataBuffer 和旧 approval 文案/参数。

## 任务来源与前置

- 根任务：`tasks.md` 7.3。
- 前置：05a；使用同一 API/application service contract。
- 后续：05c/05d 和 07b 消费 CLI migration inventory。

## 允许修改

- `interfaces/cli/commands/**`、CLI parser/handlers/help/output、approval/run/wait/event/inspection commands。
- CLI contract tests、migration inventory 和 documentation。

## 不允许修改

- CLI 不直接调用 executor/store，不接受 caller-supplied state patch、buffer updates 或 routing metadata。
- 不保留旧命令作为 hidden alias 或 fallback。

## 完成标准

1. CLI JSON/human output 使用 `graph_id/version/ref/checksum`、run/node/wait identity。
2. approval decision 命令只发送 bounded Graph Wait cause/evidence，不能注入 node state。
3. help、unknown command、legacy field rejection 和 exit code 具备 contract tests。

## 验证与证据

```powershell
python -m pytest tests/interfaces/cli tests/interfaces/test_run_event_mcp_pagination.py -q
python -m interfaces.cli.news --help
```

提交 CLI output/help/migration evidence。
