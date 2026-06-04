# 阶段 9：旧业务与旧测试删除

## 阶段目标

删除不服务新 Harness + Research 的旧业务、旧接口、旧测试、旧兼容 adapter 和 legacy fallback。阶段 9 是项目收敛阶段，目标是让仓库只保留有用资产。

## 删除范围

根据阶段 0 审计和阶段 5-7 的新 Research 实现，删除这些不再服务新架构的内容：

```text
business/boards/paper_radar
business/boards/cross_board
business/boards/project_radar
business/boards/community_pulse
interfaces/services/paper_*.py
interfaces/api/routers/papers.py
tests/business/boards
tests/interfaces/services/test_paper_*.py
tests/interfaces/api/test_papers_*.py
旧 paper reader / paper radar API contract 测试
旧前端 paper UI 测试
旧兼容 mapper / adapter / fallback
```

如果某个旧模块仍被非 UI 的基础服务使用，必须做二选一：

1. 将真实可用能力迁移到 `business/research` 或通用 framework。
2. 如果只是旧兼容，删除调用方一起替换。

不要为了减少改动保留旧兼容层。

## 测试处理标准

### 保留

保留这些测试：

- 新 Harness 测试。
- 新 Research 测试。
- 通用框架能力测试。
- infrastructure 通用存储、LLM、tool、worker、memory 测试。
- 接口层 Research 新测试。

### 迁移

旧测试中如果表达真实业务规则，迁移到新测试：

| 旧规则 | 新位置 |
| --- | --- |
| 论文 claim 必须有证据 | `tests/business/research/services/test_quality_gate.py` |
| reader payload 必须有章节导航 | `tests/business/research/application/test_build_reader_use_case.py` |
| ask paper 必须返回 evidence refs | `tests/business/research/application/test_ask_paper_use_case.py` |
| PDF/TeX 编译真实规则 | `business/research` compiler port 或后续 compiler adapter 测试 |

### 删除

直接删除：

- 只验证旧 API 路径的测试。
- 只验证旧 payload shape 的测试。
- 只验证旧 paper_radar 排名/看板/订阅/UI 的测试。
- 只为了旧兼容 fallback 存在的测试。
- 删除后不再对应任何新需求的测试。

## 接口收敛

新接口保留：

```text
interfaces/services/research_service.py
interfaces/api/routers/research.py
```

旧接口删除后，需要更新：

```text
interfaces/services/__init__.py
interfaces/api/router registration
tests/interfaces/api/test_openapi_schema.py
docs/api/openapi.json 如果项目要求同步
sdk 如果仍暴露旧 paper client
```

如果 SDK/UI 暂不迁移且会阻塞删除，必须在阶段 9 明确选择：

- 本轮删除 SDK/UI 旧 paper surface；或
- 将 SDK/UI 相关删除延后到单独 OpenSpec，但不能保留后端旧兼容。

## 数据与真实来源

生产代码不使用假数据。旧 frontend 静态 paper 数据如果不服务后端 Research，可以保留在 frontend 直到 UI 阶段，也可以删除旧 UI 时一起删。阶段 9 不做 UI，所以不要为了前端假数据保留后端旧业务。

## 架构测试

新增或更新：

```text
tests/architecture/test_no_legacy_paper_radar.py
tests/architecture/test_research_only_business_surface.py
tests/architecture/test_no_legacy_paper_interfaces.py
```

必须检查：

- 生产代码不再 import `business.boards.paper_radar`。
- 新后端不再 import 旧 `paper_service`。
- `business/research` 是论文业务唯一业务层。
- 废弃测试路径不存在或不再被收集。

## 验收命令

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec validate harness-research-runtime --strict
```

如果全量 smoke 因 UI 未迁移失败，不能直接忽略；必须判断 smoke 是否还在检查旧 UI。如果是旧 UI 范围，应更新 smoke 范围或拆出后端 smoke，并在 OpenSpec 中说明 UI out of scope。

## 完成标准

- 旧业务层不再参与后端运行。
- 旧 paper_radar 依赖被删除。
- 旧 paper API 被删除或不再注册。
- 旧测试中废弃行为被删除，有价值规则已迁移。
- 新 Harness + Research 全量测试通过。
- 仓库没有为了旧兼容保留的 adapter/fallback。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/09-legacy-business-test-deletion.md。
要求：
1. 根据 audit-inventory.md 删除不服务新 Harness + Research 的旧业务、旧接口、旧测试和旧兼容。
2. 旧测试中有真实业务规则的迁移到 tests/business/research 或 tests/framework/harness；只验证废弃行为的删除。
3. 删除旧 paper_radar 后更新 import、router registration、service __init__、OpenAPI/SDK 相关引用。
4. 添加架构测试，确保生产代码不再 import business.boards.paper_radar 或旧 paper interfaces。
5. 不做 UI。如果 smoke 仍检查旧 UI，按 UI out of scope 更新后端 smoke 范围并记录原因。
6. 运行 python -m scripts.dev compile、python -m scripts.dev test、python -m scripts.dev smoke、openspec validate harness-research-runtime --strict。
7. 修改完成后提交。
全部回复和问题用中文。
```
