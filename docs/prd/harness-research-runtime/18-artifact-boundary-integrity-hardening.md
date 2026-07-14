# 阶段 18：Artifact 安全边界与完整性硬化 PRD

> Document status: FINAL
>
> Implementation status: IMPLEMENTED
>
> Version: v1.1
>
> Priority: P1
>
> Scope: `framework/artifacts` 及直接读写同一 artifact root 的 workflow / interface 路径
>
> Source audit: `framework/artifacts` code review（2026-07-10，2026-07-14 复核）
>
> OpenSpec changes: `archive/2026-07-14-artifact-runtime-boundary-hardening`、`archive/2026-07-14-artifact-integrity-verification-hardening`
>
> Last updated: 2026-07-14

> 状态说明：`FINAL` 表示需求、实现和验收记录均已收敛；`IMPLEMENTED` 表示两个 OpenSpec change 已实现、验证、归档并同步到主规格。文档被替代时标记 `SUPERSEDED`。

## 0. 一句话结论

`framework/artifacts` 当前存在一条可写出 artifact root 的 P1 路径逃逸，以及四条会破坏引用可信度、完整性结论或篡改检测的 P2 缺陷。本阶段必须把 artifact 的路径、身份、metadata 和 checksum 全部收回到确定性基础设施控制下：**非法输入写入前失败，调用方不能覆盖可信字段，未经检查不能宣称有效，被篡改内容不能被正常解析，缺失引用字段不能被伪装成合法字符串。**

本 PRD 不以“现有测试通过”为完成依据。2026-07-14 复核时，`tests/framework/artifacts` 的 14 个测试全部通过，但五个问题仍可全部复现，因此必须新增对抗性测试和真实 workflow 集成回归。

---

## 1. 背景与审查依据

### 1.1 模块定位

`framework/artifacts` 是 NewsRoom 的底层 artifact 能力，当前同时承担：

- 通用 artifact 模型、引用和 manifest；
- `ArtifactManager` 的 run-scoped 文件写入；
- `LocalArtifactStore` 与 `FilesystemArtifactStore` 的本地持久化；
- workflow artifact 发布、校验和恢复；
- inventory、integrity inspection 和 replay bundle 构造。

它不是孤立工具包。真实 workflow 路径会从 `framework/workflow/runtime/execution_context.py` 调用 `ArtifactManager.start_run(actual_run_id)`，artifact step 会通过 `LocalArtifactPublisher` 写入运行目录，后续 manifest、index、checkpoint、inspection、replay 又依赖这些文件和引用。因此路径边界或 checksum 语义错误会直接影响可审计性、恢复能力和运行隔离。

### 1.2 已验证缺陷

| ID | 级别 | 缺陷 | 当前证据 | 业务后果 |
| --- | --- | --- | --- | --- |
| A1 | P1 | `run_id` 未统一校验，可逃逸 artifact root | `ArtifactManager.run_dir()` 直接 `root / run_id`；`LocalArtifactPublisher.publish_artifact()` 直接 `root / run_id / relative_uri` | 任意文件写入、run 间越权、污染或覆盖工作区文件 |
| A2 | P2 | 调用方 metadata 可覆盖可信 `run_id` 等字段 | publisher 在可信字段后展开 `metadata_payload`；artifact runner 的 `artifact_metadata` 也能覆盖系统字段 | 文件实际位置与引用身份不一致，刚发布就无法 verify/recover |
| A3 | P2 | 未配置 store 时 integrity inspector 返回成功 | 无 store 时返回 `valid=True` 且 `checked_count=N` | quality gate、诊断或调用方把“未检查”误判为“已验证” |
| A4 | P2 | 默认 `LocalArtifactStore.get()` 不校验持久化 checksum | 读取 object 后直接构造 `Artifact`；默认 `ArtifactManager` 使用该 store | 文件被篡改后仍作为正常内容返回，破坏 replay 和审计可信度 |
| A5 | P2 | 缺失 `uri/path` 被反序列化为字符串 `"None"` | `str(payload.get("uri") or payload.get("path"))` | 坏引用穿过必填校验，错误延迟到不相关的文件访问阶段 |

### 1.3 复现基线

截至 2026-07-14，临时目录复现得到以下行为：

```text
ArtifactManager.start_run("../escaped")
=> 在 artifact root 外创建目录

LocalArtifactPublisher.publish_artifact(run_id="../published", ...)
=> succeeded=True，文件写在 artifact root 外

publish_artifact(run_id="actual-run", metadata={"run_id": "other-run"}, ...)
=> 返回 ref.metadata.run_id == "other-run"，verify(ref) == False

ArtifactIntegrityInspector().inspect(non_empty_manifest)
=> valid=True，checked_count=1，但未读取任何 artifact

篡改 LocalArtifactStore object 后 ArtifactManager.resolve(ref)
=> 正常返回被篡改的 bytes

ArtifactReference.from_dict({"artifact_id": "a1"})
=> uri == "None"，ArtifactValidator 返回无错误
```

现有验证基线：

```text
.\.venv\Scripts\python.exe -m pytest tests\framework\artifacts -q
14 passed

.\.venv\Scripts\python.exe -m compileall -q framework\artifacts
passed
```

这说明缺陷来自契约和覆盖缺口，不是当前 happy-path 用例能发现的回归。

上述五项输出来自 2026-07-14 在 `TemporaryDirectory` 中对 live modules 执行的只读临时脚本；该脚本未作为仓库 artifact 保留。实施 Change 1/2 时，必须先把每项复现转写为 committed regression test，使修复前稳定失败、修复后稳定通过；本段历史输出不能替代可重复测试。

### 1.4 现有 OpenSpec 关系

相关旧 change 均为 completed，但尚未全部归档进 `openspec/specs/`：

- `artifact-store-index` 已引入 `ArtifactRef`、`FilesystemArtifactStore`、checksum 和 unsafe path 拒绝，但明确排除了迁移现有 workflow artifact 写入；其规范也没有覆盖 read-time checksum mismatch、非法 `run_id`、缺失 URI 和保留 metadata 字段。
- `artifact-inspection-interface` 只约束 manifest-listed interface 读取，并明确延后 checksum verification。
- `workflow-storage-indexing` 在索引时计算 checksum，但明确不替换 `ArtifactManager` 写入，也不约束读取时校验。
- `tool-builtin-artifact-tools` 已提供拒绝 absolute/`..` 的安全先例，但只约束 artifact tool 的相对路径，不约束作为目录段的 `run_id`。

实施前必须先把待修改 capability 的 completed change 归档到主规格，再创建本阶段的新 change；不得直接在旧 completed change 中追加任务并伪装成原变更的一部分。

---

## 2. 当前运行路径与信任边界

### 2.1 当前写入路径

```text
external / workflow caller
        |
        | run_id, artifact metadata, content
        v
WorkflowRunner / WorkflowExecutor
        |
        +--> ArtifactManager.start_run(run_id)
        |         |
        |         +--> root / run_id                 [A1]
        |
        +--> ArtifactStepRunner
                  |
                  +--> LocalArtifactPublisher.publish_artifact(...)
                            |
                            +--> root / run_id / relative_uri  [A1]
                            +--> trusted metadata + caller metadata [A2]
```

### 2.2 当前读取与验证路径

```text
ArtifactReference / manifest
        |
        +--> LocalArtifactStore.get()
        |         +--> read metadata
        |         +--> read bytes
        |         +--> return Artifact without checksum verification [A4]
        |
        +--> ArtifactIntegrityInspector.inspect()
                  +--> no store => valid=True [A3]

untrusted serialized ref
        +--> ArtifactReference.from_dict()
                  +--> missing uri/path => str(None) == "None" [A5]
```

### 2.3 信任边界定义

下列值全部视为不可信输入，即使它们来自仓库内部对象：

- 显式传入或从 API、CLI、MCP、manifest、checkpoint 恢复的 `run_id`；
- `artifact_id`、`step_id`、`relative_path`、`uri`、`path`；
- step metadata 中的 `artifact_metadata`；
- 从 JSON metadata 文件和 manifest 反序列化的 checksum、大小、内容类型和路径；
- `WorkflowArtifactRef.metadata` 中携带的旧 `run_id`。

只有基础设施在完成验证后生成的 canonical path、计算出的 checksum、实际 byte size、publisher identity 和函数参数中的有效 `run_id` 才是可信值。调用方不得通过 metadata 把不可信值提升为可信事实。

---

## 3. 产品目标

### G1. 关闭 artifact root 路径逃逸

所有通过 `framework/artifacts` 或直接读写同一 artifact root 的入口，都必须在产生文件系统副作用前拒绝非法 `run_id`、非法路径段和 root 外目标。

### G2. 建立可信引用身份

`run_id`、`publisher_id`、artifact path、checksum、size 等系统字段必须由 publisher/store 决定。调用方 metadata 只能携带扩展信息，不能覆盖系统身份。

### G3. 完整性检查 fail-closed

只有真正读取并完成预期校验的 artifact 才能计入 `checked_count`。没有 store、读取失败、checksum mismatch 或 metadata 损坏都不能产生 `valid=True`。

### G4. 默认读取路径检测篡改

`ArtifactManager.resolve()`、`ArtifactResolver.resolve()` 和直接 `LocalArtifactStore.get()` 必须在返回内容前验证持久化 checksum；checksum mismatch 必须使用一致、可识别的公开异常。

### G5. 反序列化时拒绝坏引用

缺失、null、空白或冲突的 `uri/path` 必须在通用模型边界立即失败，不得产生字符串 `"None"`。当引用进入本地文件 store、publisher 或 artifact root 访问路径时，再执行 relative path 与 root containment 校验；通用 `ArtifactReference` 不得因此失去表达 remote/object-store URI 的能力。

### G6. 保持合法现有运行兼容

合法 `run_id`、合法 nested artifact path、自定义非保留 metadata、JSON/text/binary 内容、manifest/index/replay/checkpoint 正常路径不得回退。

---

## 4. 非目标

本阶段明确不做：

- 不统一或删除现有 `ArtifactReference`、`ArtifactRef`、`WorkflowArtifactRef` 三套引用模型；
- 不合并 `LocalArtifactStore` 与 `FilesystemArtifactStore`；
- 不合并 `framework.artifacts.inspection.ArtifactIntegrityInspector` 与 `framework.workflow.inspection.inspector.ArtifactIntegrityInspector`；
- 不迁移到 S3、MinIO、数据库 BLOB 或其他远程 object storage；
- 不新增 artifact ACL、租户授权、加密、签名或 key management；
- 不改变 checksum 算法，仍使用 `framework.shared.hashing.hash_bytes()` 的 SHA-256 十六进制字符串；
- 不自动 sanitize、截断、hash 或重命名非法 `run_id`；
- 不在本阶段解决相同 `artifact_id` 的并发写竞争、跨进程锁或真正跨文件事务；
- 不将历史缺 checksum 的 artifact 批量回填；
- 不把所有仓库内任意 `root / run_id` 代码一并重构，只处理 artifact root 的直接入口和已确认旁路。

引用模型、store 和 inspector 的长期收敛单独进入后续 `artifact-storage-contract-convergence` change，不得阻塞本阶段五个缺陷关闭。

---

## 5. 设计原则与系统不变量

### 5.1 Fail before side effect

标识、路径、reserved metadata 必须先验证，再创建目录、写临时文件、覆盖文件、更新 manifest 或记录事件。失败时 artifact root 内外都不得出现部分产物。

### 5.2 Reject, do not sanitize

`run_id` 和 artifact identity 参与 replay、lineage、checkpoint、index 和 API identity。静默把 `../run` 改成 `_run` 会制造身份碰撞并掩盖调用方错误，因此非法输入必须失败。

### 5.3 Defense in depth

只检查 `".." in Path.parts` 不足以覆盖 Windows drive、UNC、反斜杠和未来符号链接变化。边界必须同时包含：

1. 平台无关的输入形态校验；
2. 路径段/相对路径语义校验；
3. canonical target 对 canonical root 的 descendant containment 校验。

### 5.4 Trusted fields are infrastructure-owned

调用方 metadata 不得覆盖系统字段。发生冲突时必须显式失败，不能使用“最后一次覆盖”、静默忽略或自动改名。

### 5.5 Integrity means verified

`valid=True` 的唯一含义是：manifest 中要求检查的 artifact 全部完成读取，所有必需 checksum 均已验证，且没有 missing/corrupt 项。空 manifest 是唯一允许在没有 store 时返回 `valid=True, checked_count=0` 的情况，因为它没有待检查对象。

### 5.6 One checksum algorithm and one mismatch error

所有本地 artifact store 使用相同 SHA-256 计算函数和同一个 `ArtifactChecksumMismatchError`。调用方不应根据 store 类型处理不同异常。

### 5.7 Preserve public imports where possible

异常或 helper 可移动到职责更清晰的内部文件，但 `from framework.artifacts import ArtifactChecksumMismatchError` 等现有公开导入必须继续工作。

### 5.8 No LLM in validation

路径、metadata、checksum 和引用验证全部是确定性逻辑，不经过 agent、LLM 或可变 prompt。

### 5.9 Security boundary is not a configurable gate

`ArtifactManager.gate_enabled=False` 只能关闭现有治理 gate 的组合评估，不能关闭 identity、relative path 或 root containment 校验。路径安全必须位于任何可配置 gate 之外并始终执行。

---

## 6. 目标架构

```text
                    untrusted inputs
      run_id / ids / paths / metadata / serialized refs
                              |
                              v
             framework.artifacts.paths + model validation
             - segment validation
             - relative path validation
             - canonical descendant resolution
             - reserved metadata rejection
                              |
               +--------------+--------------+
               |                             |
               v                             v
       ArtifactManager / publisher     reference deserialization
               |                             |
               v                             v
       canonical file target          canonical reference object
               |
               v
          local store write
          bytes + metadata(checksum)
               |
               v
          local store read
          recompute checksum
               |
        +------+------+
        |             |
        v             v
    verified       typed failure
    Artifact       missing / metadata corrupt / checksum mismatch
```

---

## 7. 详细需求 A1：统一路径与标识安全边界

### 7.1 问题定位

当前关键入口：

- `framework/artifacts/runtime/manager.py`
  - `start_run()` 调用 `run_dir()` 后直接建目录；
  - `run_dir()` 返回 `self.root / run_id`；
  - `_target()` 只校验 artifact `name`，不校验 `run_id`。
- `framework/artifacts/runtime/publisher.py`
  - `publish_artifact()` 直接构造 `self.root / run_id / relative_uri`；
  - `_artifact_path()` 只做部分 relative check，且依赖 metadata 中的 `run_id`。

同一 artifact root 还有以下直接路径拼接旁路，若不收口就不能宣称边界闭合：

- `framework/workflow/runtime/manifest.py::JsonManifestStore._manifest_path()`；
- `framework/workflow/runtime/executor.py::_load_checkpoint_manifest()`；
- `framework/workflow/runtime/artifact_publishers.py::_populate_artifact_metadata()`；
- `framework/workflow/runtime/runner.py::_index_artifacts()`；
- `framework/workflow/checkpoint/recovery.py` 的 checkpoint artifact recovery；
- `framework/workflow/operations/service.py` 的 run directory 与 manifest helper；
- `framework/tool/builtin/artifact.py` 的 load/search helper；
- `interfaces/services/artifact_service.py`；
- `interfaces/services/run_inspection_service.py`；
- `interfaces/services/run_operation_service.py`；
- `interfaces/services/storage_service.py::diagnose_artifact_index()`；
- `interfaces/api/routers/runs.py`；
- `interfaces/api/routers/mcp.py`；
- `interfaces/cli/commands/artifacts.py`；
- `interfaces/cli/commands/runs.py`；
- `interfaces/services/mcp_service.py`。

实施前必须再运行一次限定搜索，生成 artifact-root path inventory，至少覆盖 `framework/workflow`、`framework/tool`、`interfaces/services` 和 `interfaces/api` 中的 `artifact_root / run_id`、`root / run_id`、`run_dir / relative_path`。发现的新直接文件访问入口必须加入 Change 1 的 tasks 和测试；只修上述已知清单不足以关闭 A1。

### 7.2 决策

在 `framework/artifacts/paths.py` 建立唯一的 artifact path boundary helper，runtime、stores、workflow 和直接 artifact interface 可以向下依赖它；`framework/artifacts` 不得反向 import workflow 或 interface。

现有 `framework/workflow/inspection/inspector.py::resolve_run_dir()` 与 `resolve_artifact_path()` 已实现 canonical containment。实施时应迁移它们委托新的 artifact helper，并在 workflow 层只保留 `WorkflowRunInspectionError` 的异常映射；不得复制出第五套路径算法。

本阶段锁定以下公开契约。OpenSpec proposal/design/tasks 和实现均必须使用这些名称；若未来需要改名，必须通过独立兼容性 change 处理，不能在实施本 PRD 时自行替换：

```python
class ArtifactPathError(ValueError):
    """Raised before an artifact path can escape or become ambiguous."""


def validate_artifact_path_segment(value: str, *, field: str) -> str:
    """Return the original validated single segment; never sanitize it."""


def validate_relative_artifact_path(value: str, *, field: str) -> str:
    """Return a normalized POSIX relative path inside a run directory."""


def resolve_artifact_descendant(
    root: str | Path,
    *relative_parts: str | Path,
    field: str,
) -> Path:
    """Resolve a canonical descendant and reject targets outside root."""
```

### 7.3 路径段规则

`run_id`、`artifact_id`、`step_id` 等被当作单一目录或文件标识的字段必须满足：

- 类型为 `str`；
- 去除首尾空白后非空，但函数不得静默返回 strip 后的新 identity；带首尾空白直接拒绝；
- 不是 `.` 或 `..`；
- 不包含 `/` 或 `\`；
- 不是 POSIX absolute path；
- 不是 Windows drive absolute/drive-relative path，如 `C:\x`、`C:x`；
- 不是 UNC/device path，如 `\\server\share`、`\\?\C:\x`；
- 不包含 NUL 或 ASCII 控制字符；
- 不包含 Windows reserved characters `< > : " | ? *`；`:` 必须拒绝以关闭 NTFS alternate data stream（ADS）；
- 不以空格或 `.` 结尾，避免 Win32 canonical name alias；
- 大小写不敏感地拒绝 DOS device names `CON`、`PRN`、`AUX`、`NUL`、`COM1`-`COM9`、`LPT1`-`LPT9`，包括带 extension 的形式；
- 作为 `Path`/`PureWindowsPath`/`PurePosixPath` 解释时仅有一个有效 segment。

本阶段不强制引入新的长度或字符白名单。2026-07-14 的本机兼容性快照显示 `.newsroom/runs` 有 208 个目录，均符合保守的 `[A-Za-z0-9._-]` 形态；该快照不是部署事实。实施和发布前必须在每个目标 artifact root 重新运行只读 scanner，安全边界优先，字符策略后续单独演进。

通用 segment helper 必须允许 `_records` 这类内部合法 segment；workflow `run_id` 是否需要拒绝 `_records`、`.metadata`、`objects` 等内部命名空间，必须由单独的 run-id namespace policy 决定，不能通过破坏底层通用 helper 实现。本阶段的硬性 DoD 是路径安全；命名空间占用只有在 OpenSpec 明确列出保留名和兼容扫描后才纳入。

### 7.4 相对 artifact path 规则

允许合法 nested path，例如 `steps/s1/output.json`；必须拒绝：

- 空值、空白和 `.`；
- absolute、drive-relative、UNC/device path；
- 任意 `..` segment；
- 通过反斜杠隐藏的 traversal；
- 任一 segment 包含 ADS `:`、Windows reserved character、尾随空格/点或 DOS device name；
- normalization 后变为空或 root 本身；
- canonical resolve 后不能相对到 canonical root 的目标。

相对路径统一保存为 POSIX `/` 形式；identity segment 不做大小写或字符改写。

若路径中已存在 symlink 或 Windows junction，canonical resolve 后的实际目标仍必须位于 canonical root 内；指向 root 外的链接不得成为合法写入或读取通道。

### 7.5 Root containment

所有实际文件访问必须通过 canonical containment：

```python
canonical_root = Path(root).resolve(strict=False)
candidate = canonical_root.joinpath(*validated_parts).resolve(strict=False)
candidate.relative_to(canonical_root)  # failure => ArtifactPathError
```

不得用字符串前缀比较，例如 `str(candidate).startswith(str(root))`，因为 `C:\root-evil` 会误过 `C:\root` 前缀。

### 7.6 Public entry-point 要求

以下入口必须在第一次文件系统访问前验证：

- `ArtifactManager.start_run()`、`run_dir()`、`create/read/update/append/finalize_run_manifest()`；
- `ArtifactManager.write_json()`、`write_text()`、`write_bytes()` 和 `_target()`；
- `LocalArtifactPublisher.publish_artifact()`、`exists()`、`verify()`、`recover()`、`status()`；
- `LocalArtifactStore.path_for()`、metadata path、put/get/delete/list 的相关标识；
- `FilesystemArtifactStore.write/read/exists/checksum/delete/list()`；
- 上述 workflow、operation、artifact service、inspection service 的直接 root 拼接旁路。

### 7.7 错误语义

- 直接 manager/store/helper 调用：抛 `ArtifactPathError`；
- `LocalArtifactPublisher.publish_artifact()`：保持 result API，捕捉后返回 `ArtifactPublishResult(succeeded=False, artifact_ref=None, error=<sanitized message>)`；
- workflow 显式非法 `run_id`：在 run directory、event、manifest、checkpoint 创建前失败；
- API/interface：映射为现有 400 类 invalid identifier 响应，不得映射成 404 或 500；
- 错误消息可包含字段名和拒绝原因，但不得回显 root 的秘密绝对路径或文件内容。

### 7.8 A1 验收场景

| 输入 | 入口 | 预期 | 副作用 |
| --- | --- | --- | --- |
| `run-1` | manager / publisher / workflow | 成功 | 仅写入 `{root}/run-1/...` |
| UUID hex、`a.b`、`_records` | segment helper | 成功 | 无 |
| `""`、空白、`.`、`..` | 所有 run-id 入口 | `ArtifactPathError` 或 failed result | 不创建任何目录/文件 |
| `../x`、`..\x`、`a/b`、`a\b` | 所有 run-id 入口 | 拒绝 | root 外无文件 |
| `/x`、`C:\x`、`C:x`、`\\server\share` | 所有 run-id 入口 | 拒绝 | root 外无文件 |
| `report.txt:payload`、`name.`、`name `、`CON`、`NUL.txt`、`COM1` | segment / relative path | 拒绝 | 无文件或 ADS |
| `steps/s1/output.json` | relative path | 成功 | 写入 run 内 nested path |
| `steps\..\..\secret.txt` | relative path | 拒绝 | 无文件 |
| root 内 symlink/junction 指向 root 外 | manager / publisher / store | 拒绝 | root 外无文件 |
| 任意上述非法输入，且 `gate_enabled=False` | manager | 仍拒绝 | 无文件 |

---

## 8. 详细需求 A2：保护可信 metadata 与引用身份

### 8.1 问题定位

`LocalArtifactPublisher` 当前使用：

```python
metadata={
    "publisher_id": self.publisher_id,
    "run_id": run_id,
    **metadata_payload,
}
```

因此调用方可以覆盖 `run_id` 和 `publisher_id`。此外 `ArtifactStepRunner` 构造 metadata 时，`artifact_metadata` 放在 `artifact_id`、`relative_path`、`content_type` 之后，也允许调用方覆盖系统字段。

### 8.2 决策

定义明确的 reserved metadata key 集合，并在任何写入前拒绝冲突。不得静默使用系统值覆盖用户值，因为静默忽略会隐藏 workflow 配置错误。

固定保留集合：

```python
PUBLISHER_RESERVED_METADATA_KEYS = frozenset({
    "publisher_id",
    "run_id",
})

ARTIFACT_STEP_RESERVED_METADATA_KEYS = frozenset({
    "artifact_id",
    "artifact_type",
    "artifact_key",
    "key",
    "relative_path",
    "uri",
    "path",
    "content_type",
    "media_type",
    "publisher_id",
    "run_id",
    "redacted",
    "checksum",
    "content_hash",
    "size_bytes",
    "status",
    "created_at",
    "created_by_step_id",
})
```

`PUBLISHER_RESERVED_METADATA_KEYS` 只约束 generic publisher caller 不得伪造 publisher/run identity；`ArtifactStepRunner` 会合法地把顶层 `artifact_id`、`relative_path`、`content_type` 等控制字段交给 publisher。更宽的 `ARTIFACT_STEP_RESERVED_METADATA_KEYS` 只用于校验调用方提供的嵌套 `artifact_metadata`，防止它伪装 identity、location、content description、integrity、lifecycle 或 redaction 字段。保留键按精确字符串比较；大小写不同的自定义键不会覆盖系统字段，但仍须经过既有脱敏规则。

### 8.3 Publisher 行为

`LocalArtifactPublisher.publish_artifact()` 必须：

1. 复制 caller metadata；
2. 校验 reserved key 冲突；
3. 校验 `artifact_id` 与 `relative_path` 等已支持的控制字段；
4. 计算 canonical path；
5. 写入内容；
6. 使用函数参数中的 `run_id` 和真实 publisher id 构造 ref；
7. 对 ref metadata 执行既有敏感字段脱敏。

任何冲突在步骤 2 失败并返回 `succeeded=False`，且不得创建文件。

### 8.4 ArtifactStepRunner 行为

`artifact_metadata` 只允许自定义业务扩展字段。`artifact_id`、`relative_path`、`content_type`、`artifact_type` 和 `redacted` 必须继续从 step 顶层 metadata 的显式系统字段读取；`publisher_id`、`run_id`、`uri/path`、checksum/size/status/created fields 必须由 publisher 的真实执行结果生成。

若 `artifact_metadata` 包含保留键：

- step outcome 为 `FAILED`；
- error code/message 可诊断为 reserved metadata conflict；
- buffer 不写 artifact ref；
- manifest、step artifacts 和文件系统不登记该 artifact。

### 8.5 兼容性

- 不在本阶段给 `WorkflowArtifactRef` 增加一等 `run_id` 字段，避免不必要 schema bump；
- 新写 ref 的 `metadata["run_id"]` 必须由 publisher 生成；
- 读取旧 ref 时仍允许从 metadata 获取 `run_id`，但必须经过 A1 segment 校验；
- 正常自定义 metadata 保持原样，并继续递归脱敏敏感 key；
- 对历史上包含冲突字段但尚未读取的 ref，不做离线重写。只有新发布请求执行冲突拒绝。

### 8.6 A2 验收场景

对 `publisher_id`、`run_id` 以及 artifact step 的全部 reserved key 逐一参数化测试：

- `succeeded=False` 或 step `FAILED`；
- `artifact_ref is None`；
- root 内外无新文件；
- 自定义 `source_id`、`trace_note` 等非保留 metadata 正常保留；
- `api_key` 等敏感 metadata 仍输出 `***REDACTED***`；
- 正常 publish 后 `exists()`、`verify()`、`recover()` 均使用同一可信 run identity。

---

## 9. 详细需求 A3：完整性检查不得产生假阳性

### 9.1 问题定位

`framework.artifacts.inspection.ArtifactIntegrityInspector.inspect()` 在没有 constructor store、也没有 call-time store 时直接返回：

```python
ArtifactIntegrityReport(
    valid=True,
    checked_count=len(manifest.artifacts),
)
```

这同时伪造了“通过”和“已检查数量”。注意：`framework.workflow.inspection.inspector.ArtifactIntegrityInspector` 是另一套 manifest 文件检查器，不得因同名而误改或互换。

### 9.2 决策

本阶段采用 fail-fast，而不是扩展三态 schema：非空 manifest 没有 store 时抛出公开的 `ArtifactStoreRequiredError(RuntimeError)`；空 manifest 没有待检查对象，允许返回 `valid=True, checked_count=0`。这样非空报告的成功结果都代表真实执行过检查，也避免把 `valid=False` 的配置错误误报成 artifact 内容损坏。

```python
class ArtifactStoreRequiredError(RuntimeError):
    """Raised when integrity verification is requested without a store."""
```

### 9.3 Report 语义

保持现有 report 基本字段以降低迁移成本，但收紧语义：

- `checked_count`：本次实际调用 store 并得到可分类结果的引用数；
- missing artifact：计为一次已检查并产生 `reason="missing"`；
- checksum mismatch：计为一次已检查并产生 `reason="checksum_mismatch"`；
- `ArtifactNotFoundError`、`ArtifactChecksumMismatchError`、`ArtifactStoreMetadataError` 分别转换为 `missing`、`checksum_mismatch`、`metadata_corrupt` issue 并继续；其他 store 异常原样传播，中止 inspection；
- `valid=True`：仅当 manifest 全部引用均被检查，且 issues 为空；
- 空 manifest：无论是否提供 store，都返回 `valid=True, checked_count=0`；
- 非空 manifest + 无 store：抛 `ArtifactStoreRequiredError`。

### 9.4 Inspector 与 store 异常协作

当 `LocalArtifactStore.get()` 抛 `ArtifactNotFoundError`、`ArtifactChecksumMismatchError` 或 `ArtifactStoreMetadataError` 时，inspector 必须分别转换为 `missing`、`checksum_mismatch`、`metadata_corrupt` issue 并继续检查剩余引用，从而返回完整报告。除此之外的异常必须原样传播；不得把未知 I/O/programming error 降格为普通 issue，也不得吞掉后报告成功。

### 9.5 A3 验收场景

- 非空 manifest 且 constructor 与 call-time 都无 store：抛 `ArtifactStoreRequiredError`；
- 空 manifest 且无 store：通过，`checked_count=0`；
- call-time store 优先级高于 constructor store 的既有行为不变；
- 空 manifest + store：通过，`checked_count=0`；
- N 个正常引用：通过，`checked_count=N`；
- missing、mismatch、metadata corrupt 混合：失败，保留每项 issue，`checked_count` 与实际尝试一致；
- 不允许任何“非空 manifest、零次 store read、valid=True”的路径。

---

## 10. 详细需求 A4：默认读取执行 checksum 校验

### 10.1 问题定位

`LocalArtifactStore.put()` 会在 metadata JSON 中保存 checksum，但 `get()` 读取 metadata 和 object 后没有比较 checksum。`ArtifactManager` 默认构造 `LocalArtifactStore(self.root)`，所以默认 `resolve()` 路径会静默返回被篡改内容。

`FilesystemArtifactStore.read()` 已有正确先例：重新计算 checksum，不匹配时抛 `ArtifactChecksumMismatchError`。

### 10.2 统一异常所有权

将 store 共享异常放入 `framework/artifacts/stores/errors.py`：

```python
class ArtifactNotFoundError(FileNotFoundError): ...
class ArtifactChecksumMismatchError(ValueError): ...
class ArtifactStoreMetadataError(ValueError): ...
```

`LocalArtifactStore` 与 `FilesystemArtifactStore` 共同依赖该文件，避免 local store 反向 import filesystem implementation。以下公开 import 保持可用：

```python
from framework.artifacts import ArtifactChecksumMismatchError
from framework.artifacts.stores import ArtifactChecksumMismatchError
```

### 10.3 `LocalArtifactStore.get()` 读取顺序

```text
validate artifact_id
-> resolve object path and metadata path inside root
-> determine missing/partial state
-> parse metadata JSON
-> validate metadata identity and required fields
-> read object bytes exactly once
-> recompute SHA-256
-> compare expected checksum
-> construct and return Artifact
```

要求：

- object 和 metadata 都不存在：保持 `None`，代表 artifact 不存在；
- metadata 存在但 object 缺失：抛 `ArtifactNotFoundError`，表示已提交引用的 object 丢失；
- object 存在但 metadata 缺失：抛 `ArtifactStoreMetadataError`，表示存在未提交/孤儿 object，不能当作正常 artifact；
- metadata JSON 无法解析或类型不合法：抛 `ArtifactStoreMetadataError`；
- checksum 缺失按 10.4 legacy 策略；checksum 存在但不是 64 位小写十六进制字符串时抛 `ArtifactStoreMetadataError`；checksum 格式合法但与实际 bytes 不一致时抛 `ArtifactChecksumMismatchError`；
- 校验通过后才按 content type 构造 `Artifact`；
- `ArtifactManager.resolve()`、`ArtifactResolver.resolve()` 不得把 mismatch 转换成普通 not-found，也不得吞掉异常。

### 10.4 Legacy 缺 checksum 策略

当前 `LocalArtifactStore.put()` 写出的记录必定有 checksum。2026-07-14 本机快照未发现 `.newsroom/artifacts/.metadata` 与 `.newsroom/runs/.metadata`，但该快照不是部署事实，不能免除上线前数据盘点。为兼容外部旧数据，采用一版兼容策略：

- `get()` 对 checksum 字段缺失的 legacy metadata 允许读取，但不能宣称内容已验证；
- `get()` 返回的 legacy `Artifact` 必须在 `metadata["_artifact_integrity"]` 写入内部标记 `"checksum_missing"`；该键由 store 覆盖且不信任持久化同名输入；
- `ArtifactIntegrityInspector` 读取该内部标记后产生 `checksum_missing` issue，因此整体 `valid=False`；
- 所有新写 metadata 必须含 checksum；
- 不自动在读取时修改 legacy 文件；
- strict reject missing checksum 可在兼容窗口结束后另行提案。

本阶段不得自行改成 strict reject；若要提前结束兼容窗口，必须另建 OpenSpec change，并提供仓库外部署数据盘点和迁移工具。

### 10.5 写入一致性

为避免 object 写完但 metadata 半写导致读取撕裂，本阶段应将 `LocalArtifactStore.put()` 改为同目录临时文件 + `os.replace()`：

1. 写 object temp 并 flush/close；
2. 写 metadata temp 并 flush/close；
3. replace object；
4. 最后 replace metadata，把 metadata 作为 commit marker；
5. `finally` 清理属于本次写入的 temp 文件。

这不是跨文件原子事务；并发写同一 `artifact_id` 仍属于非目标。但它可以防止常见的截断 JSON 和部分 object 替换。实现不得用固定共享 temp 文件名，避免相邻写入互相覆盖。

### 10.6 A4 验收场景

- JSON、text、binary put/get roundtrip；
- object bytes 被篡改：所有 resolve 路径抛 `ArtifactChecksumMismatchError`；
- metadata checksum 格式合法但值被篡改：`ArtifactChecksumMismatchError`；格式非法：`ArtifactStoreMetadataError`；
- metadata JSON 损坏：`ArtifactStoreMetadataError`；
- object/metadata 只存在一半：明确 failure，不返回正常 artifact；
- legacy missing checksum：按 10.4 的固定策略测试；
- temp write 中途异常：不提交新的 metadata commit marker，不遗留可被正常读取的半成品；
- `FilesystemArtifactStore` 既有 checksum mismatch 行为不回退。

### 10.7 Workflow/interface 读取必须接入同一完整性语义

仅修 `LocalArtifactStore.get()` 不能保护现有 run inspection 接口：`ArtifactInspectionService.get_artifact()` 当前直接读取 manifest 路径，`RunInspectionService.replay_run()` 通过 `WorkflowRunInspector.build_replay_content_bundle()` 直接展开文件，二者不会经过 local store。因此 Change 2 必须同时收口这些真实读取路径：

1. 在 `framework/workflow/inspection/inspector.py` 增加一个 strict 单 artifact 读取入口；它接收 `run_dir`、manifest 和 `artifact_key`，使用共享 descendant helper 定位文件，从 `artifact_metadata`/`step_artifacts` 取得 expected checksum，并在解码或 redaction 前校验 SHA-256；
2. expected checksum 缺失时使用与 10.4 相同的 `checksum_missing` 语义；格式非法抛 `ArtifactStoreMetadataError`；值不一致抛 `ArtifactChecksumMismatchError`；文件缺失抛 `ArtifactNotFoundError`；
3. `ArtifactInspectionService.get_artifact()` 必须使用该 strict 入口，不再自行 `Path.read_text()`；list 可以保留 metadata-only 行为，但每个列出的路径仍须通过共享 containment；
4. `WorkflowRunInspector.build_replay_content_bundle()` 增加显式 `strict_artifact_integrity: bool = False` 参数。普通内部诊断调用保持默认兼容；`RunInspectionService.replay_run()` 必须传 `True`，并在展开任何 artifact 内容前对 manifest-listed artifacts 完成 strict 校验；
5. strict replay 遇到任一 mismatch/metadata corruption/missing checksum 时整体失败，不得只把错误放入 `read_error` 后继续返回包含其他内容的成功 bundle；合法的 artifact file missing 仍使用 `ArtifactNotFoundError`；
6. `manifest.json` 是自描述文件，当前写入流程只能在其内部存放 `checksum="pending"`，没有外部可信 digest；本阶段 strict read/replay **明确排除 artifact key `manifest` 的自 checksum 校验**，但仍校验 manifest schema/path/metadata 结构，并严格校验其他 manifest-listed artifacts。不得把 `"pending"` 当作 SHA-256，也不得为了满足自校验引入循环重写；manifest 外部签名/digest 属于后续 change；
7. `framework.workflow.inspection.inspector.ArtifactIntegrityInspector` 可委托共享 checksum/error helper，但其既有非 strict 诊断 API 默认值不得被无意改变。只有上述 service-facing strict 入口保证 fail-closed。

manifest 的 `artifact_metadata`/`step_artifacts` 是 workflow artifact 的 expected checksum 来源，`LocalArtifactStore` 的 `.metadata` 是 object store 的来源；两条读取路径共享算法、格式规则和异常，不要求把 workflow run 文件伪装成 `LocalArtifactStore` object layout。正常 strict replay 必须有显式测试证明 `manifest` 的 `"pending"` 不造成误报，而任一其他 artifact 的篡改仍会阻断内容输出。

---

## 11. 详细需求 A5：引用反序列化严格化

### 11.1 问题定位

`ArtifactReference.from_dict()` 当前在原始值缺失时执行 `str(None)`。同类风险也存在于 `ArtifactRef.from_dict()` 的 `path=str(payload.get("path") or payload.get("uri"))`，因此不能只修一个模型。

### 11.2 决策

`ArtifactReference` 的 constructor 与 `from_dict()` 两个入口必须使用一致验证，防止调用方绕过 deserializer 直接构造坏对象。`ArtifactRef.from_dict()` 的 `path/uri` alias 存在同类 `str(None)` 风险，本阶段只修复其反序列化必填/alias 行为；不在本阶段全面收紧 `ArtifactRef` constructor 的所有字段和 path 字符策略，因为它的 storage/index 消费面更广，完整契约统一归入 `artifact-storage-contract-convergence`。

### 11.3 Alias 解析规则

对于 `ArtifactReference.uri`：

1. `uri` 非 `None` 时取 `uri`；否则取 legacy `path`；
2. 两者都缺失/null：`ValueError("uri is required")`；
3. 原始值必须为非空、非空白字符串，不允许通过 `str()` 把任意对象变成路径；
4. `uri` 与 `path` 同时存在且原始字符串相同：接受；
5. 两者同时存在但冲突：拒绝 ambiguous reference；
6. 通用模型不把 URI 强制解释成本地路径；本地 store、publisher、resolver 在进行文件访问前必须使用统一 relative path helper 拒绝 absolute、parent traversal、drive 和 UNC 路径。

`ArtifactRef.from_dict()` 的 `path/uri` alias 使用同一必填/冲突规则；真正文件访问仍由对应 store 执行统一 relative path 校验。

### 11.4 其他必填字段

`ArtifactRef.from_dict()` 的 `artifact_id`、`run_id`、`artifact_type`、`content_type` 必须在调用 `str()` 前验证存在且非 null/空白，不得生成字符串 `"None"`。`run_id` 和真正用于本地路径的 id 由 store/manager 边界执行安全 segment 校验。

`ArtifactReference` 允许 `run_id=None` 的既有通用引用语义保持不变；一旦提供，必须通过 segment 验证。

### 11.5 错误类型

- 缺字段、null、空白、alias 冲突：`ValueError`，消息包含逻辑字段名；
- 通用引用的缺失/冲突：`ValueError`；storage-owned path 或本地文件访问越界：`ArtifactPathError`；
- 不承诺保留旧的偶然 `KeyError`/`"None"` 行为；这是有意的输入契约收紧。

### 11.6 A5 验收场景

必须覆盖 constructor、`from_dict()` 和 `ArtifactManifest.from_dict()` 嵌套路径：

| payload | 预期 |
| --- | --- |
| 仅 `uri="objects/a1"` | 成功 |
| 仅 legacy `path="objects/a1"` | 成功 |
| `uri` 与 `path` 相同 | 成功 |
| 两者冲突 | 拒绝 |
| missing/null/empty/whitespace | 拒绝 |
| 通用 `ArtifactReference(uri="s3://bucket/key")` | 模型可接受；是否支持读取由对应 store/resolver 决定 |
| `ArtifactValidator.validate_reference(ArtifactReference(uri="s3://bucket/key"))` | 不因 local relative-path 规则误报；仍执行通用必填/id 验证 |
| `ArtifactRef.from_dict()` 的 path/uri missing/null/empty/whitespace | 拒绝 |
| `artifact_id=None`、`run_id=None`（`ArtifactRef`） | 拒绝，不生成 `"None"` |
| 正常 roundtrip | 所有字段与时间语义保持 |

---

## 12. 跨问题公共契约

### 12.1 新增/调整公开异常

| 异常 | 基类 | 触发条件 | 调用方语义 |
| --- | --- | --- | --- |
| `ArtifactPathError` | `ValueError` | 非法 identity/path 或 root containment 失败 | 输入错误，写入前失败 |
| `ArtifactStoreRequiredError` | `RuntimeError` | 请求 integrity inspection 但无 store | 配置错误，不等于 artifact invalid |
| `ArtifactChecksumMismatchError` | `ValueError` | 64 位小写十六进制 expected checksum 与实际 bytes 不一致 | corruption/tamper，不得重试为正常读取 |
| `ArtifactStoreMetadataError` | `ValueError` | metadata JSON/字段损坏，含 checksum 非字符串、长度或字符集非法 | storage metadata corruption |
| `ArtifactNotFoundError` | `FileNotFoundError` | 引用存在但目标 object 不存在 | missing artifact |

### 12.2 错误传播矩阵

| 层 | path error | checksum mismatch | no store | metadata corrupt |
| --- | --- | --- | --- | --- |
| helper/store | 抛 `ArtifactPathError` | 抛 `ArtifactChecksumMismatchError` | 不适用 | 抛 `ArtifactStoreMetadataError` |
| `ArtifactManager.resolve` | 传播 | 传播 | 不适用 | 传播 |
| `ArtifactResolver.resolve` | 传播 | 传播 | 不适用 | 传播 |
| publisher result API | `succeeded=False` | verify/recover 映射 `CORRUPTED` | 不适用 | 映射失败，不伪装 missing |
| integrity inspector | 配置/引用错误不得通过 | 记录 `checksum_mismatch` issue | 非空 manifest 抛 `ArtifactStoreRequiredError` | 记录 `metadata_corrupt` issue 并继续 |
| HTTP API | 400 + `invalid_artifact_path` 或 `invalid_run_id` | 409 + `artifact_checksum_mismatch` | 500 + `artifact_store_unavailable` | 409 + `artifact_metadata_corrupt` |
| CLI | stderr 安全错误，exit `1` | stderr 安全错误，exit `1` | stderr 安全错误，exit `1` | stderr 安全错误，exit `1` |
| MCP resource/tool | `success=False` + `error_type="ArtifactPathError"` | `success=False` + `error_type="ArtifactChecksumMismatchError"` | `success=False` + `error_type="ArtifactStoreRequiredError"` | `success=False` + `error_type="ArtifactStoreMetadataError"` |

`interfaces/api/routers/runs.py` 必须在通用 `ValueError -> 400` 和 `FileNotFoundError -> 404` 之前捕捉 corruption/configuration typed exceptions，使用现有统一 response envelope 返回矩阵中的固定 HTTP status/code。只有 object 和 metadata 均不存在或合法 run/artifact 确实不存在时才返回 404；metadata 已提交但 object 丢失属于 `artifact_not_found` 404，object 孤立、metadata 损坏和 checksum 不一致均不得伪装成 404。

`interfaces/cli/commands/artifacts.py` 与 `interfaces/cli/commands/runs.py` 在本阶段统一将 path、checksum、store-required 和 metadata-corrupt 失败写入 stderr 并返回 exit `1`，且不得输出 artifact 内容。现有 `runs artifacts` 对普通无效输入/缺失使用的 `2`/`3` 保持不变；typed integrity/corruption 异常必须先行捕捉为 `1`，避免被其 `ValueError`/`FileNotFoundError` 分支误分类。

`interfaces/services/mcp_service.py` 继续使用现有 MCP result envelope，不新增第二套错误 schema；上述异常通过 `type(exc).__name__` 形成稳定 `error_type`，`success=False`，并使用已脱敏 message。`interfaces/api/routers/mcp.py` 不得再对 `result.success=False` 无条件调用 `helpers.success()`：path error 映射 HTTP 400，checksum/metadata corruption 映射 HTTP 409，store-required 映射 HTTP 500，code 使用 12.2 的固定 HTTP code，并把 MCP `error_type` 放在 error details；只有 MCP result 自身 `success=True` 时才返回外层 HTTP success envelope。任何入口都不得以 HTTP 200、CLI exit `0`、MCP `success=True`、空内容或普通 not-found 掩盖 corruption。

### 12.3 可观测性与敏感信息

失败记录至少包含：

- error type/code；
- operation（publish/read/verify/inspect）；
- `run_id`/`artifact_id` 的安全表示；
- publisher/store id；
- 是否产生副作用；
- integrity issue reason。

日志和 result metadata 不得包含 artifact 内容、secret metadata、完整 credential 或 artifact root 的敏感绝对路径。既有 `redact_metadata()` 行为必须保留。

### 12.4 兼容矩阵

| 现有行为 | 本阶段行为 | 兼容判断 |
| --- | --- | --- |
| 合法 `run-1`、UUID run id | 保持成功 | 兼容 |
| nested artifact relative path | 保持成功 | 兼容 |
| 非保留 custom metadata | 保持并脱敏 | 兼容 |
| `path` legacy alias | 继续支持 | 兼容 |
| metadata 缺 checksum | 临时可读但 inspection 不通过 | 有意收紧 |
| 非法 `../run` | 写出 root | 改为写入前失败 |
| reserved metadata 覆盖 | 最后写覆盖 | 改为显式失败 |
| no-store inspection | 假通过 | 改为配置异常 |
| tampered object resolve | 返回内容 | 改为 mismatch 异常 |
| missing URI | 生成 `"None"` | 改为模型边界失败 |

---

## 13. 文件级影响矩阵

### 13.1 必须新增

| 文件 | 责任 |
| --- | --- |
| `framework/artifacts/paths.py` | identity、relative path、canonical descendant 的唯一安全实现 |
| `framework/artifacts/stores/errors.py` | store 共享异常，消除 exception 对具体 store 的所有权耦合 |
| `tests/framework/artifacts/test_paths.py` | 平台无关与 Windows 风格的对抗性路径测试 |

### 13.2 必须修改

| 文件 | 修改点 |
| --- | --- |
| `framework/artifacts/runtime/manager.py` | 所有 run/path 入口统一校验和 canonical containment |
| `framework/artifacts/runtime/publisher.py` | run/path 校验、reserved metadata 拒绝、可信 ref 构造 |
| `framework/artifacts/stores/local.py` | 统一路径、read-time checksum、metadata error、临时写入 |
| `framework/artifacts/stores/filesystem.py` | 复用 shared path/error，不保留重复验证实现 |
| `framework/artifacts/models/reference.py` | `ArtifactReference` constructor/from_dict 一致验证；`ArtifactRef.from_dict()` 必填与 alias 验证，不全面收紧其 constructor |
| `framework/artifacts/runtime/validator.py` | 仅对 `artifact_id`/已提供的 `run_id` 复用 segment helper；通用 `uri` 不调用 local relative-path helper，保持 remote URI 合法 |
| `framework/artifacts/inspection/integrity.py` | no-store fail-fast、准确计数、typed issue |
| `framework/artifacts/__init__.py` | 保持并扩展公开异常/helper export |
| `framework/artifacts/stores/__init__.py` | 从 `errors.py` 重导出异常 |
| `framework/workflow/runners/artifact.py` | `artifact_metadata` reserved key gate |
| `framework/workflow/runtime/execution_context.py` | workflow 入口在副作用前验证显式 run id |
| `framework/workflow/runtime/manifest.py` | `JsonManifestStore` 使用共享 boundary helper |
| `framework/workflow/runtime/executor.py` | checkpoint manifest 直接路径旁路收口 |
| `framework/workflow/runtime/artifact_publishers.py` | manifest-derived path 使用共享 helper；保留 manifest self-checksum `pending` 排除契约 |
| `framework/workflow/runtime/runner.py` | artifact indexing 读取 manifest path 前执行共享 containment |
| `framework/workflow/checkpoint/recovery.py` | checkpoint run/path 解析使用共享 segment/descendant helper |
| `framework/workflow/operations/service.py` | operation/resume/rerun 的 run directory helper 收口 |
| `framework/workflow/inspection/inspector.py` | path helper 委托；新增 service-facing strict artifact read/replay checksum 入口，同时保留诊断默认兼容 |
| `framework/tool/builtin/artifact.py` | artifact load/search/write 全部委托 manager/shared path boundary，不保留独立拼接 |
| `interfaces/services/artifact_service.py` | interface 文件解析使用共享 descendant helper |
| `interfaces/services/run_inspection_service.py` | run directory 拒绝 traversal/absolute；replay 强制 strict artifact integrity |
| `interfaces/services/run_operation_service.py` | operation 前置 run 存在性检查先校验并 canonical resolve |
| `interfaces/services/storage_service.py` | artifact-index diagnostics 使用共享 run/path helper，删除独立 `_safe_artifact_path` 算法 |
| `interfaces/api/routers/runs.py` | typed path/integrity/store 异常按 12.2 固定映射，且在宽泛异常前捕捉 |
| `interfaces/api/routers/mcp.py` | MCP failed result 映射为外层 HTTP error，禁止 `success=False` 被包装为 HTTP success |
| `interfaces/cli/commands/artifacts.py` | artifact list/show 的安全错误输出与 exit `1` 契约 |
| `interfaces/cli/commands/runs.py` | run show/replay/diagnostics/artifacts 的 typed failure 映射 |
| `interfaces/services/mcp_service.py` | run/artifact resource 和 tool 保持 `success=False` typed error envelope |

### 13.3 必须扩展测试

| 测试文件/目录 | 覆盖 |
| --- | --- |
| `tests/framework/artifacts/test_store_manager.py` | manager 非法 run id、resolve mismatch、合法回归 |
| `tests/framework/artifacts/test_runtime_publish_resolve.py` | publisher path、reserved metadata、recover corruption |
| `tests/framework/artifacts/test_inspection.py` | no-store、missing、mismatch、计数、empty manifest |
| `tests/framework/artifacts/test_models.py` | `ArtifactReference` constructor/from_dict/manifest nested；`ArtifactRef.from_dict()` adversarial cases |
| `tests/framework/artifacts/test_run_manifest.py` | reference new/legacy alias roundtrip、manifest nested、manager manifest 非法 run id 无副作用 |
| `tests/infrastructure/storage/test_artifact_store.py` | `ArtifactRef` roundtrip、FilesystemArtifactStore unsafe path/checksum 与 shared exception 兼容回归 |
| `tests/framework/workflow/runtime/test_manifest_integration.py` | 标准 manifest/index、恶意 workflow run id、strict replay checksum 集成回归 |
| `tests/framework/workflow/checkpoint/test_checkpoint_manifest_ref.py` | checkpoint artifact ref 回归 |
| `tests/framework/workflow/test_artifact_step_runner.py`（新增） | artifact step reserved metadata、failed outcome、无文件/ref/buffer 副作用与正常 publish |
| `tests/framework/tool/test_builtin_artifact_tools.py`（新增） | artifact load/search/write traversal、symlink containment 和正常 nested path |
| `tests/interfaces/services/test_artifact_inspection_service.py` | direct artifact read traversal、missing、checksum/metadata corruption 和正常读取 |
| `tests/interfaces/services/test_run_inspection_service.py` | run directory、strict replay checksum、diagnostics 默认兼容边界 |
| `tests/interfaces/services/test_storage_service.py` | artifact index diagnostics 的 run/path traversal、checksum 与正常回归 |
| `tests/interfaces/api/test_api_run_inspection.py` | get/list/replay/diagnostics/artifact 的 HTTP 400/404/409/500 error code 契约 |
| `tests/interfaces/api/test_api_run_operations.py` | cancel/rerun/resume/skip 的恶意 run id 在 service 副作用前返回 400 |
| `tests/interfaces/api/test_http_api_foundation.py` | runs router 统一错误 envelope 与 typed exception 优先级 |
| `tests/interfaces/cli/test_artifacts_commands.py` | `artifacts list/show` typed failure、stderr、exit `1`、不泄漏内容 |
| `tests/interfaces/cli/test_runs_commands.py` | `runs show/replay/diagnostics/artifacts` typed failure 与既有 `2`/`3` 兼容 |
| `tests/interfaces/services/test_mcp_application_service.py` | run/artifact resource 的 stable `error_type` 与 `success=False` |
| `tests/interfaces/api/test_api_mcp.py` | HTTP 上的 MCP resource/tool failure envelope 不被包装为成功 |
| `tests/interfaces/mcp/test_stdio_server.py` | MCP JSON-RPC artifact resource failure 传播且不输出被篡改内容 |
| `tests/interfaces/mcp/test_mcp_contracts.py` | stable resource template、result envelope 与 `error_type` 契约 |

### 13.4 不应顺手修改

- `business/research` 业务模型；
- 前端或 UI；
- unrelated storage repositories；
- LLM、agent、memory 或 skill 逻辑；
- `framework.workflow.inspection.inspector.ArtifactIntegrityInspector` 的既有非 strict 默认行为；本阶段只新增/委托 10.7 明确要求的 service-facing strict 入口和共享 checksum helper。

---

## 14. 测试计划

### 14.1 单元测试：路径

对 helper 使用参数化矩阵，至少包含：

```text
valid:
uuid hex
run-1
a.b
_records
steps/s1/output.json (relative path only)

invalid:
""
"   "
.
..
../x
..\x
a/b          (segment)
a\b         (segment)
/x
C:\x
C:x
\\server\share
\\?\C:\x
steps/../../secret
report.txt:payload
name.
name<bad>
CON
NUL.txt
COM1
```

测试必须在 Windows 当前环境通过，也必须以 `PureWindowsPath`/separator normalization 方式保证未来 POSIX CI 不会把反斜杠当普通字符放过。

### 14.2 单元测试：manager/store/publisher

- manager 的所有 filesystem public entry 均拒绝非法 run id；
- publisher 非法 run/path 返回 failed result；
- 每个 reserved key 冲突无写入；
- 正常 metadata、redaction、content type 和 extension 保持；
- object/metadata checksum 篡改；
- metadata JSON 损坏；
- half-written pair；
- legacy missing checksum 策略；
- binary/JSON/text roundtrip；
- delete/list 不越界。

### 14.3 单元测试：integrity/reference

- 非空 manifest 无 store、空 manifest 无 store；
- empty manifest；
- all valid；
- missing；
- checksum mismatch；
- checksum missing；
- metadata corrupt；
- multiple issues 后继续检查；
- `ArtifactReference` constructor/from_dict/manifest nested；
- `ArtifactRef.from_dict()` 必填和 alias；其 constructor 全字段收紧不在本阶段；
- uri/path alias 同值与冲突；
- required id/path null/blank/unsafe。

### 14.4 Workflow 集成测试

必须使用真实 `ArtifactManager` 和临时目录，不只 mock：

1. `WorkflowRunner.execute(..., run_id="../escape")` 在 run dir、manifest、event、checkpoint 前失败；
2. `ArtifactStepRunner` 接收 `artifact_metadata={"run_id": "other"}` 时 outcome `FAILED`，无文件、无 ref、无 buffer write；
3. 标准 workflow 成功，manifest artifact refs、artifact index、checkpoint 和 replay 仍可读取；
4. 正常 strict replay 接受 manifest self-checksum `"pending"`，同时验证其他 manifest-listed artifact；
5. workflow artifact 被篡改后，service-facing strict artifact read/replay 抛 `ArtifactChecksumMismatchError`，不返回任何 artifact content；非 strict diagnostics 仍报告 checksum warning/failure，不误报为已验证；
6. rerun/resume/skip 生成的合法新 run id 保持工作。

### 14.5 Interface 回归测试

- `/api/v1/runs/{run_id}` 与 artifact detail 路径接收 traversal/drive/UNC 形态时返回 400 类输入错误；
- 不读取 artifact root 外的伪造 manifest 或 artifact；
- 合法 missing run/artifact 仍保持 404；
- checksum mismatch 返回 HTTP 409 + `artifact_checksum_mismatch`，metadata corruption 返回 HTTP 409 + `artifact_metadata_corrupt`，store 配置缺失返回 HTTP 500 + `artifact_store_unavailable`；
- CLI path/integrity/configuration failure 写 stderr、exit `1`、不输出 artifact content；
- MCP 同类入口返回 `success=False` 和 12.2 固定 `error_type`。
- MCP HTTP router 对 failed MCP result 返回外层 `success=False/ok=False` 与固定 400/409/500，而不是 HTTP 200 success envelope。

### 14.6 测试质量要求

- 禁止只断言抛异常；必须同时断言 root 外无文件、root 内无部分文件；
- 对 publisher 必须断言 `artifact_ref is None`；
- 对 integrity 必须断言 `checked_count` 和 issue reason；
- 对 mismatch 必须断言具体异常类型；
- 禁止为了让旧测试通过而放宽安全 helper 或吞异常；
- 测试可用 fake store，但至少有一组真实文件系统集成测试验证真实 bytes。

---

## 15. OpenSpec 拆分与实施顺序

### 15.1 前置规格整理

在创建本阶段 change 前：

1. 归档 `artifact-store-index`，让 capability 进入 `openspec/specs/`；
2. 若 `artifact-inspection-interface` 的公共行为将被修改，先归档该 change；
3. 若 workflow storage capability 需要 delta，归档 `workflow-storage-indexing`；
4. 执行 `openspec validate --all --strict`，确认归档后的主规格一致。

归档动作和本阶段实现建议使用独立 commit，便于审查规格迁移与代码修复。

### 15.2 Change 1：`artifact-runtime-boundary-hardening`

覆盖 A1、A2、A5：

- 公共 path boundary helper；
- manager/publisher/store/workflow/interface 直接旁路收口；
- reserved metadata gate；
- `ArtifactReference` constructor/deserialization strictness 与 `ArtifactRef.from_dict()` 必填/alias strictness；
- 无副作用的对抗性测试。

任务分解：

```text
B1. 建立 ArtifactPathError 与公共 path helper
B2. 收口 ArtifactManager、LocalArtifactPublisher 和两种 local store
B3. 收口 JsonManifestStore、artifact publishers/indexer、checkpoint、tool、operation/storage service 直接路径旁路
B4. 建立 reserved metadata 契约并接入 ArtifactStepRunner
B5. 严格化 ArtifactReference constructor/from_dict，并仅收紧 ArtifactRef.from_dict 的必填/alias 行为
B6. 补齐 path/reference/publisher/workflow/interface 测试
B7. 运行 strict OpenSpec、targeted tests、compile、smoke
```

### 15.3 Change 2：`artifact-integrity-verification-hardening`

依赖 Change 1，覆盖 A3、A4：

- 共享 store exceptions；
- `LocalArtifactStore` read-time checksum；
- workflow inspector strict artifact read/replay checksum，并由 interface service 强制启用；
- metadata corruption/legacy checksum 语义；
- no-store inspector fail-fast；
- accurate count/issue；
- manager/resolver/workflow inspection 回归。

任务分解：

```text
I1. 提取共享 store exceptions 并保持 public exports
I2. 实现 LocalArtifactStore read-time checksum 和 metadata validation
I3. 实现安全临时写入与 half-written state 处理
I4. 修正 ArtifactIntegrityInspector no-store 与计数语义
I5. 接通 mismatch/corruption issue 映射
I6. 实现 workflow inspector strict artifact read/replay，并接入 artifact/run inspection services
I7. 补齐 tamper/legacy/integrity/workflow/interface 回归测试
I8. 运行 strict OpenSpec、targeted tests、compile、smoke
```

### 15.4 后续 Change：`artifact-storage-contract-convergence`

仅登记，不纳入本阶段 DoD：

- 决定 canonical reference model；
- 决定 canonical local store；
- 合并或清晰分工两套 inspector；
- 迁移所有调用方；
- 删除失去职责的重复实现。

不得以“未来会合并”为理由推迟本阶段安全修复。

### 15.5 提交边界

提交必须保持以下聚焦边界；可在不混入无关变更且每个 commit 可验证的前提下合并相邻边界：

1. `docs/openspec`: 归档旧 completed artifact changes；
2. `fix(artifacts)`: runtime boundary / reserved metadata / references；
3. `fix(artifacts)`: checksum / integrity semantics；
4. `test(artifacts)`: 如测试未随对应实现 commit 一起提交，则单独补齐集成回归。

更推荐测试与实现同 commit，保证每个修复 commit 自身可验证。不得混入无关 dirty worktree 变更。

---

## 16. 验收标准

### 16.1 安全边界

- [ ] `ArtifactManager`、`LocalArtifactPublisher`、local stores 及列出的直接旁路均使用同一 path boundary helper。
- [ ] `../`、`..\`、absolute、drive-relative、UNC/device、multi-segment run id 在任何文件副作用前失败。
- [ ] canonical target 必须是 canonical root 的 descendant。
- [ ] 对抗测试明确证明 artifact root 外没有新文件或目录。
- [ ] 合法现有 run id 与 nested artifact path 保持成功。

### 16.2 Metadata 与引用

- [ ] caller metadata 不能覆盖 `publisher_id`、`run_id` 或 artifact step 系统字段。
- [ ] 冲突返回明确失败，且不创建文件、不返回 ref。
- [ ] 正常 custom metadata 和敏感字段脱敏不回退。
- [ ] `ArtifactReference` 与 `ArtifactRef` 不再生成字符串 `"None"`。
- [ ] `uri/path` legacy alias 兼容，同值接受、冲突拒绝。

### 16.3 完整性

- [ ] 无 store 的 non-empty integrity inspection 不再返回 report success，而是抛 `ArtifactStoreRequiredError`。
- [ ] `checked_count` 只统计实际检查项。
- [ ] `LocalArtifactStore.get()` 在返回前重新计算 checksum。
- [ ] object 或 expected checksum 被篡改时，manager/resolver/store 均产生 `ArtifactChecksumMismatchError`。
- [ ] interface direct artifact read 与 run replay 在输出内容前执行 manifest checksum strict validation，篡改时产生同一 typed exception。
- [ ] metadata corruption、missing object 和 checksum missing 有固定、测试化语义。
- [ ] `FilesystemArtifactStore` 既有 mismatch 行为保持。

### 16.4 集成和回归

- [ ] 恶意显式 workflow `run_id` 在 run dir/event/manifest 创建前失败。
- [ ] artifact step reserved metadata 冲突产生 failed outcome 且无 artifact 副作用。
- [ ] 正常 workflow manifest、artifact index、checkpoint、replay 通过。
- [ ] interface/CLI/MCP 不可通过 run id 或 artifact path 读取 root 外文件。
- [ ] 所有 targeted tests、compile、smoke 和 strict OpenSpec 验证通过。

---

## 17. 验证命令

Change 1：

```powershell
openspec validate artifact-runtime-boundary-hardening --strict
.\.venv\Scripts\python.exe -m pytest tests\framework\artifacts -q
.\.venv\Scripts\python.exe -m pytest tests\infrastructure\storage\test_artifact_store.py -q
.\.venv\Scripts\python.exe -m pytest tests\framework\workflow tests\framework\tool\test_builtin_artifact_tools.py -q
.\.venv\Scripts\python.exe -m pytest tests\interfaces\services\test_artifact_inspection_service.py tests\interfaces\services\test_run_inspection_service.py tests\interfaces\services\test_storage_service.py -q
.\.venv\Scripts\python.exe -m pytest tests\interfaces\api\test_api_run_inspection.py tests\interfaces\api\test_api_run_operations.py tests\interfaces\api\test_http_api_foundation.py tests\interfaces\cli\test_artifacts_commands.py tests\interfaces\cli\test_runs_commands.py tests\interfaces\services\test_mcp_application_service.py tests\interfaces\api\test_api_mcp.py tests\interfaces\mcp\test_stdio_server.py tests\interfaces\mcp\test_mcp_contracts.py -q
```

Change 2：

```powershell
openspec validate artifact-integrity-verification-hardening --strict
.\.venv\Scripts\python.exe -m pytest tests\framework\artifacts -q
.\.venv\Scripts\python.exe -m pytest tests\infrastructure\storage\test_artifact_store.py -q
.\.venv\Scripts\python.exe -m pytest tests\framework\contracts\test_artifact_manifest_contract.py tests\framework\workflow\runtime\test_manifest_integration.py -q
.\.venv\Scripts\python.exe -m pytest tests\interfaces\services\test_artifact_inspection_service.py tests\interfaces\services\test_run_inspection_service.py tests\interfaces\services\test_storage_service.py -q
.\.venv\Scripts\python.exe -m pytest tests\interfaces\api\test_api_run_inspection.py tests\interfaces\api\test_http_api_foundation.py tests\interfaces\cli\test_artifacts_commands.py tests\interfaces\cli\test_runs_commands.py tests\interfaces\services\test_mcp_application_service.py tests\interfaces\api\test_api_mcp.py tests\interfaces\mcp\test_stdio_server.py tests\interfaces\mcp\test_mcp_contracts.py -q
```

每个代码 change 的最终门禁：

```powershell
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
openspec validate --all --strict
git diff --check
```

如目标测试文件实际名称在实施前发生变化，应通过 `git ls-files tests` 选择等价 live test，不得因为路径漂移跳过对应测试层。

---

## 18. 发布、迁移、回滚与可观测性

### 18.1 发布顺序

```text
归档旧规格
-> boundary change + tests
-> integrity change + tests
-> full smoke
-> 本地/测试环境正常 workflow 验证
-> 生产或共享环境发布
```

Change 1 与 Change 2 必须可独立回滚，但完整发布必须两者都完成。只发布 Change 1 会关闭写越界和身份混淆，但不会关闭 silent tamper read；只发布 Change 2 则仍保留路径逃逸，均不算阶段完成。

### 18.2 数据迁移

- 运行前盘点 artifact metadata 中缺 checksum 的记录数量；
- 本地仓库当前未发现默认 `LocalArtifactStore` metadata 目录，但不能把本机状态当作部署环境事实；
- 若部署数据存在 legacy missing checksum，使用 10.4 兼容策略上线并记录计数；
- 不自动修改、重命名或删除历史 artifact；
- 不自动 sanitize 历史 run id；发现非法历史目录时输出离线迁移报告，由运维明确决定隔离、重命名映射或只读保留。

### 18.3 回滚条件

出现以下任一情况应停止发布并回滚对应 change：

- 合法历史 run id 被大面积拒绝；
- 标准 workflow 无法创建 manifest/index/checkpoint；
- checksum mismatch 在未篡改 artifact 上系统性误报；
- interface 正常 404/读取契约被破坏；
- temp write 导致 metadata/object 可见性恶化或残留失控。

不得通过关闭校验、catch-all 后返回 success 或删除失败断言来完成回滚。回滚后保留失败样本并创建根因修复任务。

### 18.4 运行指标

至少提供结构化计数或可从日志聚合的事件：

```text
artifact_path_rejected_total{field,operation}
artifact_reserved_metadata_rejected_total{key,publisher}
artifact_checksum_mismatch_total{store,operation}
artifact_metadata_corrupt_total{store}
artifact_checksum_missing_total{store}
artifact_integrity_inspection_total{result}
```

如果当前项目没有通用 metrics sink，可先使用结构化 event/log；不得为本阶段引入新的重型监控依赖。

---

## 19. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 外部 client 使用特殊字符 run id | 新校验造成兼容中断 | 本阶段只施加安全边界，不先引入窄字符白名单；上线前盘点真实数据 |
| Windows 与 POSIX 对反斜杠解释不同 | 跨平台 CI 放过 traversal | 显式使用 Windows/Posix path 语义与 separator normalization 测试 |
| shared helper 只接主路径，旁路仍存在 | 宣称修复但 interface/operation 仍可越界 | 文件级矩阵列出直接旁路，验收逐一验证 |
| reserved metadata 拒绝暴露旧 workflow 配置 | 部分 artifact step 开始失败 | 先搜索现有调用方；错误明确到 key；不静默覆盖 |
| legacy metadata 缺 checksum | strict read 阻断历史数据 | 一版兼容读取 + integrity `checksum_missing`，部署前盘点 |
| checksum 校验增加 I/O/CPU | 大 artifact 读取延迟 | 当前读取本来已读取全量 bytes，只增加 SHA-256 计算；记录指标后再优化流式读取 |
| temp + replace 被误认为跨文件事务 | 并发/掉电仍可能产生半状态 | metadata 最后提交、明确 half-state 语义；跨文件事务和锁留给后续 |
| 同名 integrity inspector 被误改 | workflow inspection 产品语义回归 | import 路径与测试分开；只在明确集成需求下调整 workflow inspector |
| 395 个 completed/no-task change 未整理 | 新 delta 缺主规格基线 | 先归档本次直接相关 capability，不要求先清空全部历史 change |

---

## 20. Definition of Done

本阶段只有在以下条件全部满足时才完成：

- [x] 两个必做 OpenSpec change 均创建并通过 strict validation；
- [x] 所有 A1-A5 需求具有规范性 SHALL requirement 与可执行 scenario；
- [x] 旧相关 capability 已按需要归档到主规格，未直接篡改 completed change 历史；
- [x] 公共 path helper 成为 artifact root 路径的唯一判断来源，已确认旁路全部处理；
- [x] reserved metadata、reference、checksum、no-store 语义均按本文固定，不留“二选一”实现决定；
- [x] 对抗性单元测试与真实 workflow/interface 集成测试全部通过；
- [x] `.\.venv\Scripts\python.exe -m scripts.dev smoke` 通过；
- [x] `openspec validate --all --strict` 通过；
- [x] `git diff --check` 通过；
- [x] 每个代码变更已按范围提交，未混入无关工作树内容；
- [x] PRD metadata 的 `Implementation status` 更新为 `IMPLEMENTED`，并补充 commits、归档 change 路径和最终验证结果。

未满足任一项时，状态只能是 `IN_PROGRESS` 或 `BLOCKED`，不能以“主要路径已修”“14 个原测试仍通过”或“后续 convergence 会处理”为由标记完成。

---

## 21. 实施记录

### 21.1 交付边界与提交

| 边界 | 提交 | 结果 |
| --- | --- | --- |
| PRD | `fd84a147` | 建立阶段 18 的缺陷证据、修复契约、测试矩阵和 DoD |
| artifact storage 基线规格归档 | `4d45001f` | 把后续 delta 所需的 storage capability 同步到主规格 |
| artifact tool 基线规格归档 | `45e7b4bf` | 把 builtin artifact tool/search capability 同步到主规格 |
| replay interface 基线规格归档 | `d5452466` | 把 artifact inspection、run replay API/CLI/MCP capability 同步到主规格 |
| Change 1 实现 | `03ec11f0` | 关闭 A1、A2、A5：统一 path boundary、保留字段保护和 reference 反序列化收紧 |
| Change 2 实现 | `65bdf330` | 关闭 A3、A4：共享 typed errors、atomic local-store write、checksum verification、strict replay 与 adapter 错误契约 |
| Change 1 归档 | `b291e9f1` | 归档到 `openspec/changes/archive/2026-07-14-artifact-runtime-boundary-hardening/` 并同步 6 份 capability |
| Change 2 归档 | `84abfd20` | 归档到 `openspec/changes/archive/2026-07-14-artifact-integrity-verification-hardening/` 并同步 7 份 capability |

### 21.2 A1-A5 关闭证据

| 缺陷 | 最终行为 | 主要实现证据 |
| --- | --- | --- |
| A1 `run_id` / path 逃逸 | segment、relative path、canonical descendant 三层校验在文件副作用前执行；workflow、tool、service 旁路统一接入 | `framework/artifacts/paths.py`、`ArtifactManager`、publisher/store/workflow inspection 与 adversarial path tests |
| A2 trusted metadata 被覆盖 | publisher 与 artifact step 对保留字段冲突 fail-closed，不产生 file/ref/manifest/index/buffer 副作用 | reserved metadata contract 与 artifact-step/publisher 回归 |
| A3 no-store integrity 假成功 | 空 manifest 返回 `valid=True, checked_count=0`；非空且无 store 抛 `ArtifactStoreRequiredError`；计数只包含实际 store 尝试 | `framework/artifacts/inspection/integrity.py` 与 mixed-failure classification tests |
| A4 checksum 篡改静默通过 | `LocalArtifactStore.get()` 校验 pair state、metadata 和 SHA-256；direct artifact/replay 在 decode/redact/content return 前 strict verify | shared store errors/helpers、local store fault injection、workflow strict preflight、API/CLI/MCP regressions |
| A5 缺失 path 被转成 `"None"` | constructor/from_dict 对 required id/path、alias 同值/冲突和本地路径边界执行显式校验，同时保留 remote URI 表达能力 | `ArtifactReference` / `ArtifactRef.from_dict()` contract tests |

### 21.3 最终验证

| 门禁 | 结果 |
| --- | --- |
| Change 1 定向矩阵 | `483 passed, 12 skipped` |
| Change 2 定向矩阵 | `394 passed, 6 skipped` |
| `.\.venv\Scripts\python.exe -m scripts.dev compile` | 通过 |
| `.\.venv\Scripts\python.exe -m scripts.dev smoke` | `903 passed, 23 skipped`，source validation 通过 |
| `openspec validate --all --strict` | `507 passed, 0 failed` |
| `git diff --check` | 通过 |

定向矩阵中的 skip 均为当前 Windows 账户缺少 symlink 创建权限时的条件性跳过；没有跳过 checksum、metadata、half-state、strict replay 或 adapter error contract 用例。API 测试产生的 FastAPI `on_event` deprecation warning 为既存技术债，不影响本阶段验收。

### 21.4 Legacy checksum 只读盘点

2026-07-14 对仓库本地 `.newsroom` 做了只读递归盘点：未发现任何 `.metadata` 目录；默认 `F:\github\NewsRoom\.newsroom\artifacts\.metadata` 不存在，因此本机统计为 `metadata_roots=0`、`json_count=0`、`checksum_missing=0`、`invalid_json=0`。盘点没有创建、修改、回填、重命名或删除历史数据。

该结果只证明当前开发工作区没有待迁移的 `LocalArtifactStore` legacy metadata，不能外推到生产或共享部署。部署前仍必须对实际 artifact root 运行同等只读盘点；若发现缺 checksum 记录，按 10.4 的一版兼容读取策略上线，记录计数并另行制定显式迁移，不得在 read path 自动回填。
