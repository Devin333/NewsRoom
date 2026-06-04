# 阶段 6：Research 单篇论文闭环

## 阶段目标

用新 Harness 跑通 Research 单篇论文后端闭环。使用 fake LLM、fake repository、fake source provider、fake artifact store。阶段 6 不做 UI，不接旧 paper API，不复用旧 paper_radar。

## 目标流程

```text
load_paper_source
-> compile_document
-> build_evidence_pack
-> analyze_structure
-> analyze_contribution
-> analyze_experiments
-> verify_claims
-> quality_gate
-> build_reader_payload
-> publish_artifacts
```

## Application Service

新增或完善：

```text
business/research/application/analyze_paper.py
business/research/application/build_reader.py
business/research/application/ask_paper.py
```

### AnalyzePaperUseCase

输入：

```text
paper_id
source_ref 或 paper metadata
run_id
options
```

输出：

```text
ResearchAnalysisResult
run_id
analysis
quality
reader_payload_ref
artifact_refs
trace_ref
```

职责：

- 组装 HarnessRunSpec。
- 注入 Research workflow spec。
- 调用 Harness。
- 将 Harness 输出投影成 Research result。

不允许：

- 直接调用 LLM。
- 直接写 infrastructure。
- 调用旧 paper_radar orchestrator。

## Fake 数据和真实业务规则

生产代码不能写假业务能力。测试里可以使用 fake：

```text
FakeResearchPaperRepository
FakeResearchSourceProvider
FakeResearchDocumentCompiler
FakeResearchLLMWorker
FakeResearchArtifactStore
```

fake 论文内容应体现真实论文结构：

```text
title
abstract
introduction
method
experiments
limitations
references
```

不要用 `"foo"`、`"bar"` 这类无法表达业务规则的数据。

## LLM Worker 使用边界

LLM worker 只允许生成候选：

```text
candidate_summary
candidate_contributions
candidate_experiment_claims
candidate_limitations
candidate_reader_answer
```

Harness 和 Research services 决定：

```text
是否采纳
是否证据足够
是否返工
是否通过质量门
是否写 artifact
```

## Quality Gate

至少检查：

| 检查 | 失败处理 |
| --- | --- |
| 每个主要 claim 有 evidence | 返工或失败。 |
| analysis 不为空 | 失败。 |
| reader payload 有章节导航 | 失败。 |
| source lineage 存在 | 失败。 |
| LLM 输出没有非法流程字段 | 忽略并记录 warning。 |

## Artifact

至少产出：

```text
research-analysis.json
research-reader-payload.json
research-quality-result.json
harness-trace.json
```

阶段 6 用 fake artifact store 即可，但 domain/application 不应依赖具体 store。

## 测试要求

新增：

```text
tests/business/research/application/test_analyze_paper_use_case.py
tests/business/research/application/test_build_reader_use_case.py
tests/business/research/application/test_ask_paper_use_case.py
tests/business/research/integration/test_single_paper_loop_fake_runtime.py
```

必须覆盖：

- 单篇论文完整闭环成功。
- fake LLM 返回 `next_step` 不影响流程。
- evidence 缺失时 quality gate 失败。
- quality gate 失败时 Harness retry 或 fail。
- artifact refs 完整。
- trace 能解释每个 step。
- 不依赖旧 paper_radar。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness tests/business/research -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Fake runtime 跑通单篇论文完整闭环。
- 输出 ResearchAnalysis、ResearchReaderPayload、ResearchQualityResult。
- Harness trace 可导出。
- 质量门失败路径可测试。
- 不做 UI，不接旧 API。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/06-research-single-paper-loop.md。
要求：
1. 用新 Harness 跑通 Research 单篇论文闭环。
2. 实现 AnalyzePaperUseCase、BuildReaderUseCase、AskPaperUseCase 的后端应用层逻辑。
3. 使用 fake LLM、fake repository、fake source provider、fake compiler、fake artifact store 测试，不接真实 UI。
4. LLM 只生成候选内容，不能决定流程。
5. 输出 ResearchAnalysis、ResearchReaderPayload、ResearchQualityResult 和 Harness trace/artifact refs。
6. 添加完整闭环、质量门失败、非法 LLM 流程字段、artifact、trace 测试。
7. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness tests/business/research -q、openspec validate harness-research-runtime --strict。
8. 修改完成后提交。
全部回复和问题用中文。
```
