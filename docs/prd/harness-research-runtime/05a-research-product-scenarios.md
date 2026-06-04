# 阶段 5A：Research 产品场景与业务工作流

## 阶段目标

把 Research 从“单篇论文摘要”明确建模为研究情报业务上下文。Research 首轮业务聚焦论文，但需要覆盖 Paper with Code 展示、代码仓库情报、3 分钟速读、分类体系、阅读器、阅读笔记、方法/benchmark 图谱，以及 Agent skill/tool intelligence 的扩展边界。

本阶段只做业务 PRD 和模型边界规划。实现顺序仍然以后续阶段为准：先做框架层 Harness，再做 Research 第一批闭环；UI 暂时不做。

## Research 的产品定位

Research 是：

```text
论文情报
+ 代码仓库情报
+ 论文阅读器
+ 用户阅读记忆
+ 方法 / benchmark 图谱
+ agent skill / tool intelligence
```

Research 不是：

```text
旧 paper_radar 兼容层
旧 paper API 包装层
纯 LLM 摘要工具
纯 PDF viewer
```

## 业务模块拆分

建议最终模块：

```text
business/research/
  paper_card/
  taxonomy/
  reader/
  reader_repair/
  reading_session/
  code_repository/
  benchmark/
  method_graph/
  agent_intelligence/
  rag/
  workflows/
  application/
```

第一批只实现必要闭环，后续模块先保留清晰边界。

## 场景 1：Paper with Code 展示卡片

### 目标

论文展示框需要显示论文核心信息、PDF、代码仓库、GitHub 热度、分类、速读、reader 状态。

### 输出字段

```text
paper_id
title
authors
abstract
published_at
source_url
pdf_url
code_url
github_repo
github_stars
github_star_growth_daily
github_forks
github_last_commit_at
github_license
three_minute_read
domains
areas
tasks
methods
benchmarks
reader_payload_status
quality_flags
metadata
```

### 确定性逻辑

不应交给 LLM 的部分：

```text
PDF URL 提取和规范化
GitHub URL 提取和规范化
GitHub stars / forks / license / last commit
star growth daily
source URL lineage
reader payload status
```

这些应由 service / tool / repository 处理。

### LLM worker 候选

LLM 只生成候选：

```text
candidate_three_minute_read
candidate_domains
candidate_areas
candidate_tasks
candidate_methods
candidate_benchmarks
candidate_contributions
```

Harness / Research gate 决定是否采纳。

### Gate

```text
PaperCardSourceLineageGate
PaperCardCodeUrlGate
PaperCardGithubMetricGate
PaperCardSummaryEvidenceGate
PaperCardTaxonomyGate
PaperCardRequiredFieldGate
```

## 场景 2：Taxonomy 分类体系

### 目标

论文展示框和后续检索都需要稳定分类体系，不允许 LLM 自由创造分类。

### 三层分类

```text
Domain:
  General
  Vision
  Video
  Language
  Audio
  Robotics
  Multimodal
  Code

Area:
  Agent
  Image Understanding
  Reasoning
  Question Answering
  Generation
  Retrieval
  Evaluation
  Planning
  Tool Use

Task:
  web agent
  code agent
  tool use
  visual question answering
  image captioning
  long-context QA
  math reasoning
  paper reading
  benchmark evaluation
  skill evolution
```

### 目录建议

```text
business/research/taxonomy/
  __init__.py
  models.py
  registry.py
  classifier.py
  gates.py
  rules.py
```

### 约束

- Taxonomy registry 是确定性资产。
- LLM 只能输出 taxonomy candidate。
- candidate 必须带 evidence refs 和 confidence。
- 不在 registry 内的分类必须进入 review，不自动新增。

## 场景 3：3 分钟速读

### 目标

为论文展示卡片和阅读器生成短速读内容。

输出建议：

```text
problem
core_idea
key_contributions
method_summary
experiment_summary
limitations
why_it_matters
read_next
evidence_refs
confidence
```

约束：

- 每个关键 claim 必须有 evidence refs。
- 不能凭 abstract 单独生成全部结论。
- 不能输出未验证 SOTA claim。
- 不能把 speculation 写成事实。

可使用子 Agent：

```text
SummaryCandidateWorker
SummaryEvidenceVerifier
```

两者必须通过阶段 3C 隔离。

## 场景 4：Reader Compilation

### 目标

把原始论文渲染成项目自己的阅读器 payload，而不是直接展示原 PDF。

核心流程：

```text
load_paper_source
-> compile_document
-> extract_sections
-> extract_figures
-> extract_tables
-> extract_equations
-> extract_citations
-> build_reader_payload
-> verify_reader_payload
-> repair_reader_payload_if_needed
-> publish_reader_artifact
```

Reader payload 至少包含：

```text
paper
sections
figures
tables
equations
references
navigation
annotations
source_lineage
quality
metadata
```

常见问题：

```text
image_missing_or_broken
figure_caption_mismatch
latex_source_rendered
formula_placeholder_missing
table_parse_error
section_boundary_error
citation_link_error
reference_parse_error
source_lineage_missing
reader_payload_schema_error
```

这些问题进入阶段 6A Reader Repair Memory / Repair RAG。

## 场景 5：Reading Session 与阅读笔记

### 目标

用户读论文时产生笔记、划线、问题、回答、书签、困惑点。用户最后选择部分内容，生成一份阅读笔记。

### 用户事件

```text
highlight_created
note_created
question_asked
answer_generated
bookmark_created
confusion_marked
section_selected
reading_note_requested
```

### 输出阅读笔记

```text
reading_note_id
paper_id
user_id
selected_highlights
selected_notes
selected_questions
generated_summary
key_takeaways
method_notes
benchmark_notes
open_questions
source_refs
user_selection_refs
created_at
metadata
```

### 记忆关系

```text
Episodic Memory:
  用户某次阅读的问题、笔记、困惑点、生成过的阅读笔记。

Semantic Memory:
  论文事实、claim、method、benchmark、section relation。

Procedural Memory:
  用户偏好的笔记格式、常用阅读策略、常见 reader repair 策略。
```

### 隐私与边界

- 用户阅读笔记属于用户级 memory，不应默认进入 project/global memory。
- 生成阅读笔记时只能召回当前用户授权范围内的 reading session。
- 不能把其他用户私有问题或笔记召回到当前用户上下文。

## 场景 6：Code Repository Intelligence

### 目标

论文里的 GitHub 代码不只是展示链接，还要成为 Research 情报。

字段建议：

```text
repo_url
owner
name
stars
forks
watchers
open_issues
license
default_branch
last_commit_at
release_count
has_requirements
has_readme
has_examples
has_training_script
has_inference_demo
has_model_checkpoint
install_instructions_ref
paper_code_alignment
metadata
```

### Star Growth

需要记录历史点：

```text
repo_url
observed_at
stars
forks
watchers
```

计算：

```text
star_growth_daily
star_growth_7d
star_growth_30d
trend_label
```

### LLM 可参与但不决策

LLM 可以生成：

```text
candidate_code_summary
candidate_paper_code_alignment
candidate_reproducibility_notes
```

Gate 验证：

```text
CodeRepoUrlGate
GithubMetricFreshnessGate
CodeReadmeLineageGate
PaperCodeAlignmentGate
CodeReproducibilityGate
```

## 场景 7：Method / Benchmark Graph

### 目标

抽取论文中的方法、benchmark、dataset、metric、score、baseline、SOTA claim，形成可查询图谱。

### 图谱关系

```text
Paper
-> proposes Method
-> evaluates_on Benchmark
-> reports MetricScore
-> compares_with Baseline
-> uses Dataset
-> claims SOTA
```

核心模型：

```text
ResearchMethod
ResearchBenchmark
ResearchDataset
ResearchMetric
ResearchScore
ResearchBaseline
ResearchSOTAClaim
```

必须支持问题：

```text
哪些论文在同一个 benchmark 上测过？
当前最高分是谁？
某个方法在哪些任务上有效？
某个 benchmark 最近有没有被刷新？
某个 SOTA claim 是否只来自作者自报？
```

### Gate

```text
BenchmarkExtractionSchemaGate
BenchmarkEvidenceLineageGate
MetricNormalizationGate
ScoreRangeGate
SOTAClaimVerificationGate
CrossPaperBenchmarkConsistencyGate
```

Benchmark 抽取和 Benchmark 验证必须通过阶段 3C 子 Agent 隔离。

## 场景 8：Agent Skill / Tool Intelligence

### 目标

Research 需要支持 agent 相关任务类型下的 skill、tool、benchmark、score、paper 的关系分析。

图谱关系：

```text
AgentTask
-> Skill
-> Tool
-> Benchmark
-> Score
-> Paper
```

示例任务类型：

```text
web agent
code agent
tool use
memory agent
multi-agent coordination
self-evolving skill
reader repair
paper analysis
```

输出信息：

```text
task_type
representative_papers
methods
benchmarks
high_scoring_skills
tools
failure_modes
evidence_refs
confidence
```

这部分后续可以和阶段 3A skill evolution 连接，但普通 Research run 不允许直接修改 active skill。

## 子 Agent 隔离落点

Research 中必须隔离的关系：

| 关系 | 隔离原因 |
| --- | --- |
| SummaryCandidateWorker vs SummaryEvidenceVerifier | 避免摘要生成的猜测污染证据验证。 |
| TaxonomyClassifier vs TaxonomyGate | 避免模型自由创造分类。 |
| ReaderRepairProposer vs ReaderRepairVerifier | 修复者不能自己验证自己。 |
| RAGPlanner vs ClaimVerifier | 检索计划理由不能污染 claim 验证。 |
| BenchmarkExtractor vs BenchmarkClaimVerifier | 抽取候选不能直接变成已验证 benchmark 事实。 |
| CodeRepoProfiler vs PaperCodeAlignmentVerifier | 代码摘要不能替代论文-代码对应验证。 |
| ReadingNoteGenerator vs Privacy/SourceGate | 阅读笔记生成不能越权使用用户私有记忆。 |
| SkillCandidateGenerator vs SkillEvaluator/Promoter | skill 候选生成不能直接晋升。 |

这些隔离关系必须复用阶段 3C 的 `framework/harness/subagents`，不要在 Research 里自建隔离机制。

## 推荐实现顺序

### 第一批

```text
Paper Card
Taxonomy
3 分钟速读
Reader Payload
Reader Repair Memory
Reading Notes
```

目标：能服务单篇论文展示、阅读和笔记生成。

### 第二批

```text
Code Repository Intelligence
Benchmark Graph
Method Graph
```

目标：让 Research 从单篇论文进入跨论文比较。

### 第三批

```text
Agent Skill / Tool Intelligence
SOTA tracking
personalized research memory
```

目标：形成长期研究情报和自进化输入。

## 对阶段 5/6/6A 的影响

阶段 5 建模时必须预留：

```text
paper_card
taxonomy
reader
reader_repair
reading_session
code_repository
benchmark
method_graph
agent_intelligence
```

阶段 6 第一批闭环只要求跑通：

```text
paper_card basics
taxonomy candidate + gate
three_minute_read
reader_payload
reader_issue detection
```

阶段 6A 继续实现：

```text
reader repair memory
repair RAG
repair consolidation
```

Code Repository / Benchmark / Method Graph / Agent Intelligence 可以先定义 domain models 和 ports，不要求第一批完整闭环。

## 测试要求

新增或补充：

```text
tests/business/research/paper_card/test_paper_card_models.py
tests/business/research/taxonomy/test_taxonomy_registry.py
tests/business/research/taxonomy/test_taxonomy_gate.py
tests/business/research/reader/test_reader_payload_models.py
tests/business/research/reading_session/test_reading_note_models.py
tests/business/research/code_repository/test_code_repo_models.py
tests/business/research/benchmark/test_benchmark_models.py
tests/business/research/method_graph/test_method_graph_models.py
tests/business/research/agent_intelligence/test_agent_intelligence_models.py
```

必须覆盖：

- Paper card 字段可序列化。
- GitHub metrics 不能由 LLM fake 生成。
- taxonomy candidate 必须来自 registry。
- reader payload 必须带 source lineage。
- reading note 必须带 user selection refs 和 source refs。
- code repo model 支持 star growth observation。
- benchmark score 必须带 metric、dataset、paper refs。
- method graph 关系可序列化。
- agent intelligence 只表达业务图谱，不直接发布 skill。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/business/research -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Research 产品场景被明确拆分成业务模块。
- 第一批、第二批、第三批范围清晰。
- Paper Card / Taxonomy / Reader / Reading Session / Code Repository / Benchmark / Method Graph / Agent Intelligence 的模型边界清晰。
- 子 Agent 隔离关系明确，并指向阶段 3C 通用机制。
- 不接旧 paper_radar，不做 UI。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/05a-research-product-scenarios.md。
要求：
1. 将 Research 业务建模为论文情报、代码仓库情报、阅读器、用户阅读记忆、方法/benchmark 图谱、agent skill/tool intelligence。
2. 在 business/research 下预留 paper_card、taxonomy、reader、reader_repair、reading_session、code_repository、benchmark、method_graph、agent_intelligence、rag 模块边界。
3. 第一批只要求 Paper Card、Taxonomy、3 分钟速读、Reader Payload、Reader Repair Memory、Reading Notes 的模型和 workflow 边界；Code Repository、Benchmark、Method Graph、Agent Intelligence 先定义 domain models 和 ports。
4. Paper with Code 展示卡必须支持 pdf_url、code_url、github_repo、github_stars、star_growth_daily、three_minute_read、domains、areas、tasks、methods、benchmarks、reader_payload_status。
5. GitHub stars、star growth、repo metadata 必须来自真实工具/数据源端口，不能由 LLM 编造。
6. Taxonomy 必须有 registry，LLM 只能输出 candidate，TaxonomyGate 决定是否采纳。
7. Reader payload 必须包含 sections、figures、tables、equations、references、navigation、source_lineage、quality。
8. Reading notes 必须基于用户选择的 highlights、notes、questions、answers、source refs 生成，并经过 privacy/source gate。
9. Method / Benchmark Graph 必须能表达 Paper、Method、Benchmark、Dataset、Metric、Score、Baseline、SOTAClaim。
10. Agent Skill / Tool Intelligence 只表达任务、skill、tool、benchmark、score、paper 的业务图谱，不直接发布或修改 active skill。
11. Research 中的摘要生成/验证、分类候选/gate、reader repair proposer/verifier、benchmark extractor/verifier、code profiler/alignment verifier、reading note generator/privacy gate 必须复用阶段 3C 子 Agent 隔离。
12. 添加对应 domain model、taxonomy、reader、reading session、code repo、benchmark、method graph、agent intelligence 测试。
13. 运行 python -m scripts.dev compile、python -m pytest tests/business/research -q、openspec validate harness-research-runtime --strict。
14. 修改完成后提交。
全部回复和问题用中文。
```
