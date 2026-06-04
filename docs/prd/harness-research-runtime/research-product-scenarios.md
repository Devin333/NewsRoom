# Research Product Scenarios

本文档是阶段 5A 的结构化产物，供阶段 5 `business/research` 建模直接引用。它不创建代码、不定义测试文件，只把产品场景转成稳定的领域输入、端口边界、确定性职责、LLM candidate 边界、gate 和后端可见结果。

## 全局边界

Research 的第一轮实现仍以论文业务为中心，但领域模型必须覆盖研究情报的长期形态：

```text
论文情报
+ 代码仓库情报
+ 论文阅读器
+ 用户阅读记忆
+ 方法 / benchmark 图谱
+ agent skill / tool intelligence
+ Research RAG
```

所有场景共同遵守以下约束：

| 约束 | 要求 |
| --- | --- |
| Harness 控制流程 | Research 只提供 domain models、ports、services、workflow spec 和 gate；运行时路由、重试、memory write、artifact publication 由 Harness 决定。 |
| LLM 只产出 candidate | LLM 不写最终模型的确定性字段，不决定 taxonomy 接受、quality verdict、RAG 停止、reader repair 发布或 skill promotion。 |
| 真实数据端口 | GitHub metrics、source lineage、PDF/source metadata、reader artifact 状态、repository freshness 等生产数据必须来自真实工具或 repository port。 |
| 证据优先 | summary、taxonomy、benchmark、method、code alignment、reading note 都必须保留 `evidence_refs` / `source_refs`。 |
| 子 Agent 隔离 | candidate worker 和 verifier/gate 必须复用阶段 3C `framework/harness/subagents`，不在 Research 内自建隔离机制。 |
| 旧系统排除 | 不依赖 `business/boards/paper_radar`、旧 paper API、旧 reader payload、旧 UI compatibility adapter 或 frontend。 |

## 批次范围

| 批次 | 场景 | 阶段 5 建模要求 | 阶段 6/6A 闭环要求 |
| --- | --- | --- | --- |
| 第一批 | Paper Card、Taxonomy、3 分钟速读、Reader Payload、Reader Repair Memory、Reading Notes、Research RAG projection | 建立模型、端口、services、workflow spec、gate 和测试输入 | 阶段 6 跑通单篇论文 basics、taxonomy gate、速读、reader payload、issue detection；阶段 6A 完成 repair memory/RAG |
| 第二批 | Code Repository Intelligence、Benchmark Graph、Method Graph | 建立领域模型、端口和 gate 边界 | 暂不要求第一批完整闭环 |
| 第三批 | Agent Skill / Tool Intelligence、SOTA tracking、personalized research memory | 建立业务图谱模型和禁止事项 | 后续和 skill evolution / personalized memory 连接 |

## 场景矩阵

### 1. Paper Card

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端可返回单篇论文展示卡，包含论文来源、PDF、代码仓库、GitHub 热度、分类、速读、reader 状态和质量标记。 |
| Domain model candidates | `ResearchPaper`、`ResearchPaperCard`、`ThreeMinuteRead`、`TaxonomyAssignment`、`CodeRepositoryProfile`、`ReaderArtifactStatus`、`QualityFlag`。 |
| Ports / services candidates | `PaperSourceProvider`、`GithubRepositoryPort`、`PaperCardBuilder`、`ReaderArtifactRepository`、`TaxonomyGate`、`SummaryEvidenceGate`。 |
| Deterministic responsibilities | `pdf_url` / `code_url` / `github_repo` 规范化；GitHub stars/forks/license/last commit/star growth 读取和计算；source lineage；reader payload status；required field validation。 |
| LLM candidate responsibilities | `candidate_three_minute_read`、`candidate_domains`、`candidate_areas`、`candidate_tasks`、`candidate_methods`、`candidate_benchmarks`、`candidate_contributions`。 |
| Gates | `PaperCardSourceLineageGate`、`PaperCardCodeUrlGate`、`PaperCardGithubMetricGate`、`PaperCardSummaryEvidenceGate`、`PaperCardTaxonomyGate`、`PaperCardRequiredFieldGate`。 |
| Backend-visible outcomes | `ResearchPaperCard` 可序列化；包含 `paper_id`、`title`、`authors`、`abstract`、`published_at`、`source_url`、`pdf_url`、`code_url`、`github_repo`、`github_stars`、`github_star_growth_daily`、`github_forks`、`github_last_commit_at`、`github_license`、`three_minute_read`、`domains`、`areas`、`tasks`、`methods`、`benchmarks`、`reader_payload_status`、`quality_flags`、`metadata`。 |
| Stage 5 test input | Paper card 字段可序列化；GitHub metrics 不能由 LLM candidate 写入最终模型；缺少 source lineage 或 required field 时 gate 拒绝。 |
| Explicit exclusions | 不读取旧 `paper_radar` public payload；不复用旧 paper cache；不创建 UI card adapter。 |

### 2. Taxonomy

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端拥有稳定分类体系，Paper Card、RAG、benchmark/method 查询和 agent intelligence 共享同一个 registry。 |
| Domain model candidates | `TaxonomyRegistry`、`TaxonomyDomain`、`TaxonomyArea`、`TaxonomyTask`、`TaxonomyCandidate`、`TaxonomyAssignment`、`TaxonomyReviewItem`。 |
| Ports / services candidates | `TaxonomyRegistryProvider`、`TaxonomyClassifierWorkerPort`、`TaxonomyGate`、`TaxonomyReviewRepository`。 |
| Deterministic responsibilities | registry 维护；candidate 是否在 registry 内；evidence refs 是否覆盖；confidence 范围；不在 registry 内的分类进入 review。 |
| LLM candidate responsibilities | 从论文 evidence 生成 `candidate_domains`、`candidate_areas`、`candidate_tasks` 和理由，但不能新增 registry 项。 |
| Gates | `TaxonomyRegistryGate`、`TaxonomyEvidenceGate`、`TaxonomyConfidenceGate`、`TaxonomyReviewRoutingGate`。 |
| Backend-visible outcomes | 可序列化的 taxonomy assignment；未接受 candidate 的 review reason；Paper Card 使用已通过 gate 的分类。 |
| Stage 5 test input | taxonomy candidate 必须来自 registry；不在 registry 内时不自动采纳；candidate 必须有 `evidence_refs` 和 `confidence`。 |
| Explicit exclusions | 不沿用旧 board taxonomy；不让 LLM 自由创造分类；不提供 UI taxonomy editor。 |

### 3. Three-minute Read

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端为 Paper Card 和 Reader 返回短速读结构，帮助用户快速理解问题、核心思路、贡献、实验、局限和后续阅读。 |
| Domain model candidates | `ThreeMinuteRead`、`ResearchClaim`、`EvidenceRef`、`SummaryCandidate`、`SummaryVerificationResult`。 |
| Ports / services candidates | `SummaryCandidateWorkerPort`、`SummaryEvidenceVerifierPort`、`ResearchEvidenceBuilder`、`CitationVerifier`、`SummaryQualityGate`。 |
| Deterministic responsibilities | 每个关键 claim 必须绑定 evidence refs；禁止 abstract-only 全文结论；禁止未验证 SOTA claim；区分 speculation 和 fact；输出 schema 校验。 |
| LLM candidate responsibilities | 生成 `problem`、`core_idea`、`key_contributions`、`method_summary`、`experiment_summary`、`limitations`、`why_it_matters`、`read_next` 的候选文本。 |
| Gates | `SummarySchemaGate`、`SummaryEvidenceCoverageGate`、`SummaryUnsupportedClaimGate`、`SummarySOTAClaimGate`、`SummarySpeculationGate`。 |
| Backend-visible outcomes | `ThreeMinuteRead` 可序列化并带 `evidence_refs`、`confidence`、`quality_flags`；未通过 gate 时返回 rejection reason 或 route_to_repair 输入。 |
| Stage 5 test input | 无 evidence 的关键 claim 被拒绝；SOTA claim 必须有 benchmark/source refs；速读模型可序列化。 |
| Explicit exclusions | 不复用旧 paper summary payload；不把 LLM 自评当 gate；不做纯摘要工具入口。 |

### 4. Reader Payload

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端把论文源编译成 NewsRoom 自有 reader payload，而不是直接把 PDF 当最终阅读器。 |
| Domain model candidates | `ResearchDocument`、`ResearchSection`、`ResearchFigure`、`ResearchTable`、`ResearchEquation`、`ResearchReference`、`ReaderNavigation`、`ReaderAnnotation`、`ResearchReaderPayload`、`ReaderQuality`。 |
| Ports / services candidates | `PaperSourceProvider`、`DocumentCompilerPort`、`SectionExtractor`、`FigureExtractor`、`TableExtractor`、`EquationExtractor`、`CitationExtractor`、`ReaderPayloadBuilder`、`ReaderPayloadGate`、`ArtifactStorePort`。 |
| Deterministic responsibilities | section/figure/table/equation/reference extraction lineage；schema validation；navigation consistency；source hash；artifact ref；reader quality flags。 |
| LLM candidate responsibilities | 可辅助生成 section title normalization、figure/table description candidate、annotation candidate，但不能决定 source lineage 或 artifact publication。 |
| Gates | `ReaderPayloadSchemaGate`、`ReaderSourceLineageGate`、`ReaderNavigationGate`、`ReaderCitationLinkGate`、`ReaderTableEquationGate`、`ReaderArtifactPublicationGate`。 |
| Backend-visible outcomes | `ResearchReaderPayload` 包含 `paper`、`sections`、`figures`、`tables`、`equations`、`references`、`navigation`、`annotations`、`source_lineage`、`quality`、`metadata`；可发布 artifact ref。 |
| Stage 5 test input | reader payload 必须带 source lineage；section/table/equation/reference 模型可序列化；缺少 lineage 或 schema 错误时 gate 拒绝。 |
| Explicit exclusions | 不依赖旧 reader payload schema；不迁移旧 PDF viewer UI；不让接口层直接组装 reader payload。 |

### 5. Reading Session And Reading Note

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端记录用户阅读事件，并基于用户显式选择的划线、笔记、问题、回答和 source refs 生成阅读笔记。 |
| Domain model candidates | `ReadingSession`、`ReadingEvent`、`Highlight`、`ReaderNote`、`ReaderQuestion`、`ReaderAnswer`、`Bookmark`、`ConfusionMarker`、`ReadingNote`、`UserSelectionRef`。 |
| Ports / services candidates | `ReadingSessionRepository`、`ReadingMemoryPort`、`ReadingNoteService`、`ReadingNoteGeneratorWorkerPort`、`ReadingPrivacyGate`、`ReadingSourceGate`。 |
| Deterministic responsibilities | user_id/session_id 授权；只召回当前用户允许范围；user selection refs 校验；source refs 校验；memory namespace routing。 |
| LLM candidate responsibilities | 基于授权上下文生成 `generated_summary`、`key_takeaways`、`method_notes`、`benchmark_notes`、`open_questions` 的候选内容。 |
| Gates | `ReadingNotePrivacyGate`、`ReadingNoteSourceGate`、`ReadingNoteSelectionGate`、`ReadingNoteSchemaGate`、`ReadingMemoryNamespaceGate`。 |
| Backend-visible outcomes | `ReadingNote` 可序列化；包含 `reading_note_id`、`paper_id`、`user_id`、`selected_highlights`、`selected_notes`、`selected_questions`、`generated_summary`、`key_takeaways`、`method_notes`、`benchmark_notes`、`open_questions`、`source_refs`、`user_selection_refs`、`created_at`、`metadata`。 |
| Stage 5 test input | reading note 必须带 `user_selection_refs` 和 `source_refs`；跨用户 memory 召回被拒绝；session/note 模型可序列化。 |
| Explicit exclusions | 不从其他用户私有笔记召回；不默认写 project/global memory；不复用旧 reader interaction API。 |

### 6. Code Repository Intelligence

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端把论文代码仓库建模为研究情报，包括 repo metadata、活跃度、star growth、可复现线索和论文-代码对应关系。 |
| Domain model candidates | `CodeRepositoryProfile`、`CodeRepositoryObservation`、`StarGrowthWindow`、`RepositoryCapabilitySignal`、`PaperCodeAlignment`、`CodeReproducibilityNote`。 |
| Ports / services candidates | `GithubRepositoryPort`、`RepositoryObservationRepository`、`CodeRepositoryProfiler`、`PaperCodeAlignmentVerifier`、`CodeReproducibilityGate`。 |
| Deterministic responsibilities | repo URL 规范化；GitHub stars/forks/watchers/open issues/license/default branch/last commit/release count 读取；star growth 计算；README/example/training/inference/checkpoint 文件信号。 |
| LLM candidate responsibilities | 生成 `candidate_code_summary`、`candidate_paper_code_alignment`、`candidate_reproducibility_notes`，必须绑定 README/source refs。 |
| Gates | `CodeRepoUrlGate`、`GithubMetricFreshnessGate`、`CodeReadmeLineageGate`、`PaperCodeAlignmentGate`、`CodeReproducibilityGate`。 |
| Backend-visible outcomes | `CodeRepositoryProfile` 可序列化；支持 observation history 和 `star_growth_daily`、`star_growth_7d`、`star_growth_30d`、`trend_label`。 |
| Stage 5 test input | code repo model 支持 star growth observation；LLM candidate 不能写最终 GitHub metrics；缺少 freshness/source refs 时 gate 拒绝。 |
| Explicit exclusions | 不使用伪造 GitHub metrics；不从旧 project_radar board payload 读取最终指标；不做 repo UI。 |

### 7. Benchmark Graph

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端可表达论文在 benchmark/dataset/metric 上的 score、baseline 和 SOTA claim，为跨论文比较做准备。 |
| Domain model candidates | `ResearchBenchmark`、`ResearchDataset`、`ResearchMetric`、`ResearchScore`、`ResearchBaseline`、`ResearchSOTAClaim`、`BenchmarkEvidenceRef`。 |
| Ports / services candidates | `BenchmarkExtractorWorkerPort`、`BenchmarkClaimVerifierPort`、`BenchmarkGraphRepository`、`MetricNormalizer`、`ScoreRangeGate`。 |
| Deterministic responsibilities | metric normalization；score range validation；dataset/benchmark refs；paper refs；cross-paper benchmark consistency；SOTA claim verification status。 |
| LLM candidate responsibilities | 从 evidence 中抽取 benchmark/dataset/metric/score/baseline/SOTA candidate，但不能把 candidate 直接写成 verified fact。 |
| Gates | `BenchmarkExtractionSchemaGate`、`BenchmarkEvidenceLineageGate`、`MetricNormalizationGate`、`ScoreRangeGate`、`SOTAClaimVerificationGate`、`CrossPaperBenchmarkConsistencyGate`。 |
| Backend-visible outcomes | benchmark graph edge 可序列化；可回答同一 benchmark 上有哪些论文、当前最高分是谁、SOTA claim 是否只来自作者自报。 |
| Stage 5 test input | benchmark score 必须带 metric、dataset、paper refs；score range 异常被拒绝；SOTA claim 有 verification status。 |
| Explicit exclusions | 不继承旧 board ranking score；不让 extractor 自己验证自己；不提供可视化图谱 UI。 |

### 8. Method Graph

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端可表达 paper、method、task、benchmark、dataset、metric、score、baseline 的关系，用于方法谱系和跨论文比较。 |
| Domain model candidates | `ResearchMethod`、`ResearchMethodRelation`、`MethodBenchmarkEdge`、`MethodTaskEdge`、`MethodEvidenceRef`。 |
| Ports / services candidates | `MethodExtractorWorkerPort`、`MethodGraphBuilder`、`MethodGraphRepository`、`MethodEvidenceGate`。 |
| Deterministic responsibilities | graph edge schema；method identity normalization；evidence refs；relationship type validation；duplicate edge handling。 |
| LLM candidate responsibilities | 生成 method/entity/relation candidate 和 method summary candidate，但不能决定 final graph acceptance。 |
| Gates | `MethodGraphSchemaGate`、`MethodEvidenceLineageGate`、`MethodRelationTypeGate`、`MethodDuplicateGate`、`MethodBenchmarkConsistencyGate`。 |
| Backend-visible outcomes | method graph relations 可序列化；可查询某个方法在哪些任务和 benchmark 上有效。 |
| Stage 5 test input | method graph 关系可序列化；无 evidence refs 的 edge 被拒绝；重复 edge 可确定性合并。 |
| Explicit exclusions | 不复用旧 board method tags；不把 LLM entity list 当最终图谱；不做 UI graph。 |

### 9. Agent Skill / Tool Intelligence

| 维度 | 内容 |
| --- | --- |
| Business outcome | 后端可表达 agent 任务、skill、tool、benchmark、score、paper 的业务图谱，为研究 skill/tool 趋势和后续 skill evolution 输入做准备。 |
| Domain model candidates | `AgentTaskType`、`AgentSkillReference`、`AgentToolReference`、`AgentBenchmarkReference`、`AgentScoreReference`、`AgentSkillToolIntelligence`、`AgentFailureMode`。 |
| Ports / services candidates | `AgentIntelligenceExtractorWorkerPort`、`AgentIntelligenceRepository`、`AgentIntelligenceGate`、`SkillEvolutionCandidatePort`。 |
| Deterministic responsibilities | 任务类型 registry；skill/tool refs；evidence refs；confidence 范围；禁止 active skill mutation；skill evolution handoff 只输出 candidate input。 |
| LLM candidate responsibilities | 生成 representative papers、methods、benchmarks、high scoring skills、tools、failure modes 的候选分析。 |
| Gates | `AgentTaskRegistryGate`、`AgentIntelligenceEvidenceGate`、`AgentSkillMutationGate`、`AgentConfidenceGate`、`SkillEvolutionHandoffGate`。 |
| Backend-visible outcomes | `AgentSkillToolIntelligence` 可序列化；表达 `task_type`、`representative_papers`、`methods`、`benchmarks`、`high_scoring_skills`、`tools`、`failure_modes`、`evidence_refs`、`confidence`、`metadata`。 |
| Stage 5 test input | agent intelligence 只表达业务图谱；普通 Research run 不能发布或修改 active skill；confidence/source refs 可验证。 |
| Explicit exclusions | 不直接调用 skill promoter；不修改 active skill package；不做 agent marketplace UI。 |

### 10. Research RAG

| 维度 | 内容 |
| --- | --- |
| Business outcome | Research 能把论文业务问题投影成 Harness bounded RAG 的 retrieval goal 和 context projection，用于 claim verification、summary、reader repair 和 reading note。 |
| Domain model candidates | `ResearchRetrievalGoal`、`ResearchRAGContext`、`ResearchEvidencePack`、`ResearchRAGGapReport`、`ResearchSourceRef`、`ResearchMemoryContext`。 |
| Ports / services candidates | `ResearchRAGPolicyBuilder`、`ResearchEvidenceBuilder`、`ResearchContextProjector`、`ResearchRAGGate`；通用 loop 使用 `framework/harness/rag`。 |
| Deterministic responsibilities | allowed source refs；allowed memory namespaces；required evidence types；context projection；gap report；不执行多轮 retrieval loop。 |
| LLM candidate responsibilities | 可提出 retrieval question candidate、evidence summary candidate、gap explanation candidate，但不能决定 retrieval stop、source acceptance 或 memory acceptance。 |
| Gates | `ResearchRetrievalGoalGate`、`ResearchRAGSourceScopeGate`、`ResearchRAGMemoryNamespaceGate`、`ResearchEvidenceCoverageGate`、`ResearchRAGContextProjectionGate`。 |
| Backend-visible outcomes | `ResearchRetrievalGoal` 和 `ResearchRAGContext` 可序列化；可被 Harness RAGSessionSpec 消费；输出 accepted/rejected/conflicting evidence 和 gap report。 |
| Stage 5 test input | Research RAG workflow spec 只声明业务目标和 gate；不实现通用 RAG loop；source/memory scope 越界被拒绝。 |
| Explicit exclusions | 不在 `business/research` 直接调用 RetrievalPort 多轮循环；不把动态 RAG 结果放入 stable prefix；不复用旧 paper search API 作为领域真相。 |

### 11. Reader Repair Memory Impact

| 维度 | 内容 |
| --- | --- |
| Business outcome | Reader payload 构建问题先成为可审计 repair memory，再通过阶段 6A 的 repair RAG 和后续 skill evolution 形成稳定策略。 |
| Domain model candidates | `ReaderIssue`、`ReaderRepairCase`、`ReaderRepairStrategy`、`ReaderRepairContextPack`、`RepairMemoryWriteIntent`、`RepairConsolidationCandidate`。 |
| Ports / services candidates | `ReaderIssueDetector`、`ReaderRepairMemoryPort`、`ReaderRepairProposerWorkerPort`、`ReaderRepairVerifierPort`、`ReaderRepairGate`、`RepairStrategyConsolidator`。 |
| Deterministic responsibilities | issue type/severity/error signature；payload before/after refs；source refs；verification results；memory namespace；ordinary run 只产生 memory write intent，不发布 skill。 |
| LLM candidate responsibilities | 生成 repair strategy candidate、repair explanation candidate、procedural strategy candidate，但不能自己验证自己或发布 skill。 |
| Gates | `ReaderIssueSchemaGate`、`ReaderRepairSourceLineageGate`、`ReaderRepairPayloadFidelityGate`、`ReaderRepairMemoryPolicyGate`、`ReaderRepairSkillMutationGate`。 |
| Backend-visible outcomes | reader issue / repair case / repair strategy 可序列化；成功修复记录为 episodic/procedural memory 输入；稳定策略可作为 skill candidate seed。 |
| Stage 5 test input | reader issue、repair case、repair strategy model 可序列化；reader repair workflow spec 不发布 skill；ordinary repair run 不能修改 active skill。 |
| Explicit exclusions | 不让 reader repair 直接 patch active skill；不复用旧 visual compiler repair payload；不做 UI 修复面板。 |

## 阶段 5 测试输入汇总

阶段 5 建模时至少把以下输入转成测试：

- `ResearchPaperCard`、`ThreeMinuteRead`、`ResearchReaderPayload`、`ReadingSession`、`ReadingNote`、`CodeRepositoryProfile`、`ResearchBenchmark`、`ResearchMethod`、`AgentSkillToolIntelligence` 可序列化。
- GitHub metrics、star growth、license、last commit、repo freshness 只能来自 port/tool 数据，不能由 LLM candidate 写入最终模型。
- taxonomy candidate 必须属于 registry；不属于 registry 的 candidate 进入 review，不自动新增。
- reader payload 必须带 `source_lineage`，并覆盖 sections、figures、tables、equations、references、navigation、quality。
- reading note 必须带 `user_selection_refs` 和 `source_refs`，并通过 privacy/source gate。
- benchmark score 必须带 metric、dataset、paper refs；SOTA claim 必须有 verification status。
- method graph 和 agent intelligence 只表达业务图谱，不发布 skill、不修改 active skill。
- Research RAG 只表达业务 retrieval goal、source/memory scope 和 context projection，不实现通用 RAG loop。
- Reader repair memory 先写 memory intent，经 consolidation 后才能作为 skill candidate seed。
- `business/research` import boundary 测试必须禁止 `business.boards.paper_radar`、`interfaces` 和 `infrastructure`。

## 旧系统和 UI 排除确认

阶段 5A 的所有场景都明确排除以下依赖：

```text
business/boards/paper_radar
interfaces/api/routers/papers.py
interfaces/services/paper_*.py
旧 paper cache payload
旧 reader payload compatibility adapter
frontend paper UI
Next.js paper API compatibility routes
```

若阶段 5 发现必须使用旧资产中的经验，只能把可复用规则重新表达为 `business/research` 的模型、service、gate 或测试夹具，不能从 `business/research` 反向 import 旧模块。
