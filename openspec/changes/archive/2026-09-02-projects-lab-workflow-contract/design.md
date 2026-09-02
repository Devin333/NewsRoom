# Design

## Context and observed drift

当前后端在 backend/projects/lab.py 中使用 clarifying_requirements、solution_ready、solution_generated 等字符串；answer 会在找到指定 question 后直接将 current_stage 设置为 solution_ready。与此同时，frontend/src/features/projects/components/projects-product-page.tsx 总是展示 Generate Solution，frontend/src/types/projects.ts 把 current_stage 声明为任意 string，测试夹具还使用 clarifying 和 ready_to_generate。

这不是单纯的视觉问题。它属于领域 workflow contract：服务端必须决定下一动作和生成资格，前端只能呈现结果。这样才能满足 Harness 作为流程控制者、LLM 作为内容 worker 的边界。

## Canonical contract

### Stage

v1 使用以下稳定值：

- clarifying_requirements：session 已创建，至少存在一个未回答的必答问题。
- ready_to_generate：所有 v1 澄清问题已回答，允许请求生成方案。
- solution_generated：方案已生成但尚未保存为用户状态。
- solution_saved：用户已保存方案。
- solution_adopted：用户已标记采用方案。
- solution_archived：用户已归档方案。

未知 stage 在客户端必须被视为 unknown，不得自动映射为可生成状态。

### Next action

响应增加 next_action，取值为：

- answer_question
- generate_solution
- review_solution
- save_solution
- none

next_action 是服务端根据 session 状态计算的可执行建议，不代表前端可以绕过 endpoint 权限或质量门。

### Generation readiness

响应增加：

- can_generate_solution: boolean
- unanswered_question_ids: string[]

v1 的 _questions(session)_ 返回的每个问题都是 required。未来如果引入 optional question，应由后端模型显式返回 required 字段；客户端不能通过问题文案或 answered_value 以外的启发式推断必答性。

规则如下：

- 新 session：can_generate_solution=false，unanswered_question_ids 包含全部问题。
- answer 成功但仍有未答问题：stage=clarifying_requirements，next_action=answer_question。
- 最后一个问题回答成功：stage=ready_to_generate，next_action=generate_solution，can_generate_solution=true。
- 已生成方案：stage=solution_generated，next_action=review_solution，can_generate_solution=false。
- saved、adopted、archived：next_action=none。

## Endpoint behavior

### Start

保持 POST /api/v1/projects/lab/sessions 的输入和真实 case selection 规则不变。响应补充上述派生字段。问题列表必须稳定排序，以便键盘焦点和客户端恢复一致。

### Answer

- question_id 不存在返回 404。
- answer 去除首尾空白；空值返回 422。
- 只更新目标问题，保留同一 session 中其他问题的 answered_value。
- 允许对已回答问题重新回答，但重新计算 stage 和 unanswered_question_ids。
- 写入现有 graph_state feedback node，继续使用现有 stable_id 和 durable local state repository。

### Generate

- 服务端重新读取 session 并计算 readiness，不信任请求体或客户端状态。
- can_generate_solution=false 时返回 409，错误 code 固定为 lab_session_not_ready，并带 unanswered_question_ids。
- 通过校验后复用现有确定性 _solution 逻辑，写入 generated_solution、solution_json 和 solution graph node。
- 生成成功返回 stage=solution_generated、next_action=review_solution。

### Save

- session 不存在返回 404。
- solution_json 和 generated_solution 都为空时返回 409，错误 code 为 lab_solution_missing。
- status 只能使用现有 LabSessionStatus 值。
- 状态更新后重新计算 current_stage 和 next_action；保存只是持久化状态，不代表质量门通过或已发布。

### Explain node

保持 explain-node endpoint 的输入输出和 404 行为。未知 node 不得被包装成成功的空解释。

## Layer ownership

- business/projects：定义 LabSession 的阶段派生、问题完整性和状态迁移。
- interfaces/services/project_service.py：继续作为应用服务边界，负责调用领域服务和统一错误对象。
- interfaces/api/routers/projects.py：只做请求解析、权限、HTTP 状态和标准 envelope 映射。
- frontend/src/types/projects.ts：使用 union type 表达已知值，同时保留未知值的安全解析路径。
- frontend/src/features/projects：根据 next_action 和 can_generate_solution 呈现按钮，不复制领域计算。

任何 agent 或 LLM 都不能决定 current_stage、can_generate_solution、API retry policy 或 session save status。

## Compatibility and rollout

这是一个需要同步发布前后端的契约变更。响应新增字段是向后兼容的，但 answer 的阶段语义和 generate 的 409 gate 属于行为变更，因此交付顺序为：

1. 更新 backend domain、API schema 和 backend tests。
2. 更新 frontend types、API client mocks 和 Lab 页面使用方。
3. 运行 backend tests、frontend tests、typecheck、compile、smoke。
4. 观察 lab_session_not_ready、lab_solution_missing 和 unknown stage 的计数。

回滚时可以先恢复前端展示版本，但不能让新前端把 unknown 或 409 当成成功；如果必须回滚服务端，应同时回滚 client 依赖的契约版本。

## Test strategy

- domain unit tests：每个 stage 的派生、最后一个问题、重复回答、空回答、未知问题。
- service tests：未准备好时 generate 不调用 _solution，真实 case selection 不变。
- API tests：404、409、422 和成功 envelope。
- frontend contract tests：已知 stage、未知 stage、can_generate_solution=false、unanswered_question_ids。
- regression：保留现有 start -> answer -> generate 流程，但 fixture 必须回答全部问题后再生成。
