# 阶段 3A：Skills 自进化

## 阶段目标

在 Harness 控制平面下加入可审计、可回滚、可单测的 skills 自进化能力。目标不是让 LLM 自己修改并发布 skill，而是让 Harness 把运行经验转成候选 skill，再用确定性 gate、离线 eval、版本发布和回滚机制决定是否晋升。

本阶段放在七层端口之后、Trace / Checkpoint / Replay 之前执行。原因是：skills 自进化依赖 `SkillWorkerPort`、`ArtifactPort`、`QualityGatePort` 和 event/transcript 模型，但必须先确定端口边界，避免把进化逻辑写成业务层或 LLM 自控流程。

## 参考思想

- `SkillOpt: Executive Strategy for Self-Evolving Agent Skills`，论文链接：https://arxiv.org/html/2605.23904v2
  - 把 skill 文档当作 frozen agent 的外部可训练状态。
  - 由独立 optimizer 根据 rollout 和评分提出有限 add/delete/replace 编辑。
  - 候选只有在 held-out validation 上严格改进才被接受。
- `From Raw Experience to Skill Consumption: A Systematic Study of Model-Generated Agent Skills`，论文链接：https://arxiv.org/html/2605.23899v1
  - skill 生命周期要覆盖 experience generation、skill extraction、skill consumption。
  - 模型生成 skill 平均有收益，但存在 negative transfer。
  - 必须做效用导向评测，不能默认新 skill 一定更好。

落到 NewsRoom 的原则：

```text
LLM can propose skill candidates.
Harness decides whether candidates are valid.
Harness decides whether candidates are evaluated.
Harness decides whether candidates are promoted.
Harness decides whether active skill versions change.
```

## 核心边界

| 对象 | 允许做什么 | 禁止做什么 |
| --- | --- | --- |
| LLM optimizer worker | 根据 transcript、eval result、rejected buffer 生成 skill candidate 或 patch。 | 直接写生产 `SKILL.md`，直接修改 registry，直接宣布通过。 |
| Skill candidate | 存在候选仓，可被静态校验、eval replay、sandbox trial。 | 覆盖 active skill，绕过 eval 上线。 |
| Harness | 选择经验、触发优化、执行 gate、发布版本、回滚版本。 | 把发布决策交给 LLM 或业务层。 |
| Business Research | 声明需要哪些 skill 能力和评测任务。 | 直接操作 skill registry 或修改框架层 skill 包。 |

## 新增目录

```text
framework/harness/skills/evolution/
  __init__.py
  models.py
  ports.py
  experience.py
  candidate.py
  patching.py
  gates.py
  evaluator.py
  promotion.py
  release.py
  fake.py
```

继续复用：

```text
framework/skills/package/
framework/skills/runtime/
framework/skills/validation/
framework/skills/quality/
business/foundation/skills/
```

约束：

- `framework/harness/skills/evolution` 只做控制平面和进化生命周期。
- `framework/skills` 继续做 skill package、manifest、schema、executor、quality gate 等底层能力。
- 不把 Research 领域逻辑写进 `framework/harness/skills/evolution`。
- 不复制一套新的 skill registry，除非现有 registry 无法满足版本化发布；优先通过 adapter 扩展。

## 核心模型

新增模型建议：

```text
SkillVersionRef
SkillExperience
SkillExperiencePool
SkillEvolutionRunSpec
SkillEvolutionState
SkillPatchOperation
SkillPatchSet
SkillCandidate
SkillCandidateStatus
SkillEvaluationCase
SkillEvaluationRun
SkillEvaluationResult
SkillPromotionDecision
SkillRelease
SkillRollbackPlan
RejectedSkillCandidate
```

### SkillVersionRef

字段：

```text
skill_name
version
package_hash
source_root
status
created_at
metadata
```

要求：

- active skill 必须能定位到不可变版本。
- 发布新版本时不覆盖旧版本。
- rollback 使用 `SkillVersionRef`，不能靠文件名猜测。

### SkillExperience

字段：

```text
experience_id
run_id
step_id
skill_name
skill_version
domain
task_type
input_refs
output_refs
transcript_refs
gate_results
score
outcome
failure_tags
created_at
metadata
```

要求：

- 来自真实 Harness transcript、trace、artifact ref 或 eval result。
- 大 payload 只保存 ref，不直接塞进 experience。
- 必须支持 successful 和 failed 两类经验，不能只从成功样本抽 skill。
- 进入 optimizer 前要做 redaction，不能把 secrets、用户隐私、凭据写入 skill candidate。

### SkillPatchSet

字段：

```text
candidate_id
base_skill
operations
patch_budget
changed_files
changed_sections
optimizer_worker_ref
reasoning_summary
created_at
```

允许的 operation：

```text
add_section
replace_section
delete_section
update_frontmatter_field
update_prompt_file
update_reference_file
update_schema_file
update_eval_case
```

禁止：

```text
write_arbitrary_file
delete_package
change_allowed_tools_to_high_risk_without_approval
remove_required_quality_gate
disable_schema_validation
```

### SkillCandidate

字段：

```text
candidate_id
base_skill
candidate_version
patch_set
manifest_snapshot
package_ref
static_gate_results
evaluation_results
promotion_decision
status
created_at
```

状态：

```text
draft
static_validating
static_rejected
eval_ready
evaluating
eval_rejected
sandbox_ready
sandbox_rejected
promotion_pending
promoted
rejected
rolled_back
```

## 端口定义

### SkillExperienceStorePort

能力：

```text
append_experience(experience)
query_experiences(request)
build_pool(request)
```

约束：

- store 不决定哪些经验用于进化。
- Harness 根据 workflow、domain、score、failure_tags 和 budget 选择 pool。

### SkillCandidateStorePort

能力：

```text
save_candidate(candidate)
get_candidate(candidate_id)
list_candidates(filter)
save_rejected(candidate, reason)
list_rejected(filter)
```

约束：

- rejected candidate 必须可追踪，不能静默丢弃。
- rejected buffer 可供后续 optimizer 参考，但不能直接晋升。

### SkillOptimizerWorkerPort

能力：

```text
propose_patch(request) -> HarnessWorkerResult
```

约束：

- 输出只能是 `SkillPatchSet` candidate。
- 不能返回 `promote=true`、`active=true`、`next_step` 这类流程字段。
- patch 必须受 `patch_budget` 限制。

### SkillEvaluationPort

能力：

```text
run_static_validation(candidate)
run_eval_suite(candidate, eval_request)
run_sandbox_trial(candidate, sandbox_request)
```

约束：

- eval suite 必须含 baseline active version 对照。
- eval case 必须分 train/eval/held-out，不允许用生成候选的同一批经验直接判定晋升。
- eval 不允许产生生产 side effect。

### SkillPromotionPort

能力：

```text
prepare_release(candidate)
publish_release(release)
rollback(rollback_plan)
get_active_version(skill_name)
```

约束：

- publish 必须由 Harness promotion decision 驱动。
- medium/high risk skill 需要 approval record。
- rollback 必须保留 rollback transcript。

## 生命周期

```text
collect_experience
-> curate_experience_pool
-> propose_skill_patch
-> apply_patch_to_candidate
-> static_validate_candidate
-> eval_replay_candidate
-> sandbox_trial_candidate
-> promotion_gate
-> publish_versioned_skill
-> monitor_and_rollback
```

### collect_experience

来源：

```text
harness transcript
harness trace
worker result
quality gate result
artifact ref
eval result
human review record
```

处理：

- 只收集与 skill 改进相关的摘要和 refs。
- 记录失败类型：schema failure、evidence missing、tool misuse、low score、duplicate output、hallucination risk。
- 进行 redaction。

### curate_experience_pool

Harness 选择经验池：

```text
domain
skill_name
task_type
time_window
success_failure_ratio
minimum_score_gap
max_pool_size
held_out_split
```

要求：

- success 和 failure 都要有。
- held-out eval 不得泄漏进 optimizer prompt。
- pool 生成要可复现，使用稳定 seed 或稳定排序。

### propose_skill_patch

LLM optimizer worker 输入：

```text
base skill manifest
base skill selected sections
experience summaries
failure tags
rejected candidate summaries
patch budget
meta skill guidance
```

输出：

```text
SkillPatchSet
```

要求：

- patch 是有限编辑，不允许整包重写。
- patch 必须解释每个 edit 对应的 failure pattern 或 improvement target。
- 如果无法提出高置信改进，应返回 empty patch candidate，由 Harness 记录并 halted/succeeded_noop。

### static_validate_candidate

纯函数 gate：

| Gate | 校验内容 |
| --- | --- |
| `SkillPackageStructureGate` | `SKILL.md`、schemas、prompts、references、examples、evals 路径完整。 |
| `SkillManifestGate` | frontmatter 字段合法，name/category/risk/owner/quality_gates 合法。 |
| `SkillSchemaCompatibilityGate` | input/output schema 可解析，必要字段未被破坏。 |
| `SkillAllowedToolsGate` | allowed_tools 不越权，高风险工具需要 approval。 |
| `SkillPatchBudgetGate` | 修改文件数、section 数、token 预算不超限。 |
| `SkillNoSecretGate` | candidate 不包含密钥、cookie、token、私有凭据。 |
| `SkillDomainBoundaryGate` | framework skill 不包含 Research 私有业务规则；Research skill 不泄漏旧 paper_radar。 |
| `SkillQualityGateRetentionGate` | 不允许删除 schema/evidence/no_empty 等必需质量门。 |

### eval_replay_candidate

eval 设计：

```text
baseline_active_version
candidate_version
eval_cases
held_out_cases
metrics
minimum_improvement
regression_tolerance
```

指标建议：

```text
schema_pass_rate
evidence_coverage
claim_precision
reader_answer_groundedness
tool_policy_violations
quality_gate_pass_rate
average_score
failure_reduction_rate
latency_budget
cost_budget
```

要求：

- candidate 必须与 active version 在同一 eval suite 上对比。
- 默认晋升规则是 held-out 分数严格改进，且关键指标无不可接受回退。
- 如果新 skill 提升平均分但 evidence coverage 回退，不能晋升。
- eval replay 不重新调用真实外部 side effect 工具。

### sandbox_trial_candidate

用途：

- 用非生产 run 验证 candidate 在真实 workflow 形态下可消费。
- 不发布 artifact 到用户可见位置。
- 不写长期 memory。

要求：

- sandbox run 仍然走 `PLAN -> EXECUTE -> VERIFY`。
- 所有结果写 transcript。
- sandbox 失败进入 rejected buffer。

### promotion_gate

Promotion decision 必须由 Harness gate 产出：

```text
promote
reject
needs_more_eval
needs_human_approval
halted
```

晋升条件：

- static gates 全部通过。
- held-out eval 达到 minimum_improvement。
- 关键指标不超过 regression_tolerance。
- patch budget 合法。
- risk level 没有未审批升级。
- candidate package hash 可复现。
- release note 和 rollback plan 已生成。

### publish_versioned_skill

发布要求：

- 新版本写入 versioned registry。
- active alias 指向新版本。
- 旧版本保留。
- release event、promotion decision、eval result、rollback plan 写 transcript/artifact。
- 发布后 smoke eval 失败必须自动 rollback 或进入 halted。

### monitor_and_rollback

上线后监控：

```text
post_release_eval_score
runtime_gate_failure_rate
schema_failure_rate
manual_rejection_rate
rollback_signal
```

rollback 条件：

- post-release smoke eval 失败。
- gate failure rate 超过阈值。
- 人工审批撤回。
- 发现 candidate 包含敏感信息或越权工具。

## 与 PLAN / EXECUTE / VERIFY 的关系

每个 evolution step 必须纳入有界状态机：

| 相位 | 示例 |
| --- | --- |
| PLAN | Harness 选择 skill、experience pool、eval suite、patch budget。 |
| EXECUTE | 调用 optimizer worker、candidate patcher、eval runner、publisher。 |
| VERIFY | 运行 static gates、eval gates、promotion gates、budget gates。 |

新增预算：

```text
max_evolution_epochs
max_candidates_per_run
max_patch_operations
max_changed_files
max_rejected_candidates_to_load
max_eval_cases
max_sandbox_runs
```

预算耗尽必须进入：

```text
halted
succeeded_noop
rejected
```

不允许无限优化同一个 skill。

## Research 初期接入策略

阶段 6 的 Research 单篇论文闭环可以消费 versioned skills，但不在用户分析 run 中自动晋升 skill。

建议 Research 先声明这些 skill 能力：

```text
research-document-structure
research-claim-extraction
research-evidence-checking
research-contribution-analysis
research-experiment-analysis
research-reader-answering
```

初期策略：

- 使用 active skill version。
- Research run 只产生 SkillExperience。
- Reader repair run 只产生 ReaderRepairCase、ReaderRepairStrategy 或 SkillExperience seed。
- skill evolution 作为离线或显式 admin workflow 运行。
- promotion 后新的 Research run 才消费新 active version。

禁止：

- 用户触发普通论文分析时直接修改 skill。
- Research application service 直接 publish skill。
- 为了让单篇论文通过而临时改 skill。
- Reader repair 成功一次就直接修改 reader repair skill。

## Reader Repair 输入

阶段 6A 的 Reader Repair Memory 可以作为 skill evolution 的输入，但必须先经过业务记忆固化：

```text
ReaderIssue
-> ReaderRepairCase
-> ReaderRepairStrategy
-> SkillExperience / SkillPatchSet seed
-> SkillCandidate
```

要求：

- 只有 promoted procedural repair strategy 可以进入 skill evolution。
- failed repair case 可以作为 rejected/avoid pattern 输入，不能作为正向规则直接写入 skill。
- reader repair skill candidate 必须在 held-out reader repair eval 上超过 active version。
- table、formula、citation、source lineage 等关键指标不得回退。

可能生成的 skill：

```text
research-reader-repair
research-table-repair
research-citation-repair
research-formula-repair
```

## 测试要求

新增：

```text
tests/framework/harness/skills/evolution/test_models.py
tests/framework/harness/skills/evolution/test_experience_store.py
tests/framework/harness/skills/evolution/test_candidate_store.py
tests/framework/harness/skills/evolution/test_static_gates.py
tests/framework/harness/skills/evolution/test_eval_replay.py
tests/framework/harness/skills/evolution/test_promotion_gate.py
tests/framework/harness/skills/evolution/test_release_and_rollback.py
tests/framework/harness/skills/evolution/test_bounded_evolution_state_machine.py
```

必须覆盖：

- LLM optimizer 返回 `promote=true` 不影响发布决策。
- candidate 不会直接覆盖 active skill。
- patch budget 超限会被拒绝。
- 删除必需 quality gate 会被拒绝。
- allowed_tools 越权会被拒绝。
- held-out eval 没有严格改进时不会晋升。
- candidate 平均分提高但 evidence coverage 回退时不会晋升。
- rejected candidate 会进入 rejected buffer。
- promotion 会生成 release 和 rollback plan。
- rollback 能恢复旧 active version。
- evolution run 超过预算会受控 halted。
- transcript 能复盘 candidate、eval、promotion、rollback。

## 验收命令

```powershell
python -m scripts.dev compile
python -m pytest tests/framework/harness -q
openspec validate harness-research-runtime --strict
```

## 完成标准

- Harness skills evolution 契约、端口、模型、gate、fake store 完整。
- candidate、eval、promotion、rollback 全流程可单测。
- LLM 只能生成 patch candidate，不能发布。
- active skill 版本化且可回滚。
- Research 只消费 active skill version，不直接控制进化。
- 完成后提交。

## 可复制给 Codex 的任务提示

```text
请执行 docs/prd/harness-research-runtime/03a-skill-evolution.md。
要求：
1. 在 Harness 控制平面下实现 skills 自进化生命周期，不允许 LLM 直接修改或发布生产 skill。
2. 新增 framework/harness/skills/evolution 包，定义 SkillVersionRef、SkillExperience、SkillEvolutionRunSpec、SkillPatchSet、SkillCandidate、SkillEvaluationResult、SkillPromotionDecision、SkillRelease、SkillRollbackPlan 等模型。
3. 定义 SkillExperienceStorePort、SkillCandidateStorePort、SkillOptimizerWorkerPort、SkillEvaluationPort、SkillPromotionPort，并提供 fake implementation。
4. 复用 framework/skills/package、runtime、validation、quality，不复制旧 skill registry。
5. 实现 collect_experience、curate_experience_pool、propose_skill_patch、static_validate_candidate、eval_replay_candidate、sandbox_trial_candidate、promotion_gate、publish_versioned_skill、monitor_and_rollback 的 Harness 流程。
6. 所有 evolution step 必须走 PLAN/EXECUTE/VERIFY，有 max_evolution_epochs、max_candidates_per_run、max_patch_operations、max_changed_files、max_eval_cases、max_sandbox_runs 等预算。
7. 实现 SkillPackageStructureGate、SkillManifestGate、SkillSchemaCompatibilityGate、SkillAllowedToolsGate、SkillPatchBudgetGate、SkillNoSecretGate、SkillDomainBoundaryGate、SkillQualityGateRetentionGate、SkillEvalImprovementGate、SkillRegressionGate。
8. held-out eval 没有严格改进不得晋升；关键指标回退不得晋升；medium/high risk skill 晋升需要 approval record。
9. candidate 必须版本化发布，旧 active version 必须可 rollback。
10. 添加 models、store、static gates、eval replay、promotion、release/rollback、有界状态机测试。
11. 运行 python -m scripts.dev compile、python -m pytest tests/framework/harness -q、openspec validate harness-research-runtime --strict。
12. 修改完成后提交。
全部回复和问题用中文。
```
