# Projects Lab Workflow Contract

## Why

Projects Lab 当前已经具备 start、answer、generate-solution、fetch 和 save API，但 workflow 状态的表达还没有形成稳定契约。后端在任意一个问题回答后就把阶段设置为 solution_ready，前端测试却使用 clarifying 和 ready_to_generate，且生成按钮没有服务端可生成资格作为依据。这会让界面在仍有未回答问题时误导用户，也会使不同客户端各自维护一套不一致的状态机。

这项变更是 AI-native workspace 的前置条件。它把领域规则放回 ProjectLabService 和 API 契约，保证界面只负责呈现真实状态，不负责决定 workflow routing 或质量门。

## What Changes

- 定义 Projects Lab 的规范化 current_stage 值和 next_action 值。
- 在 Lab session 响应中增加 can_generate_solution 和 unanswered_question_ids。
- 将所有 v1 澄清问题视为生成方案前必须回答的问题；回答未完成时保持 clarifying_requirements，全部完成后进入 ready_to_generate。
- 生成方案接口在服务端执行可生成资格校验，未满足时返回可识别的 409 业务错误。
- 统一 answer、generate、save 的状态迁移、空值校验和未知资源错误。
- 同步 backend DTO、router、frontend projects types、API client 和现有测试夹具。
- 保留真实 Project Radar 数据政策、确定性生成逻辑和现有 source -> evidence -> analysis -> report -> quality gate -> artifacts/storage 运行路径。

## Scope

### In scope

- backend/projects/lab.py 及其领域模型和 service 测试。
- interfaces/api/routers/projects.py 的 Lab endpoint response 和错误映射。
- frontend/src/types/projects.ts、frontend/src/lib/projects/api.ts 及其契约测试。
- Projects Lab 相关的前端 happy path、pending、error、未完成问题和未知阶段测试。

### Out of scope

- 不引入 LLM streaming、自动追问、自动质量判定、自动 memory write 或自动发布。
- 不改变 Project Radar 的真实数据来源、artifact schema 或抓取策略。
- 不把生成资格交给 React 状态、文案、按钮 disabled 逻辑或 agent。
- 不合并 /studio、paper reader 或其他 Projects 页面。
- 不做数据库迁移；继续通过现有 state repository 持久化。

## Dependency and delivery order

1. 先交付并验证本变更，使所有 Lab client 都能消费稳定契约。
2. 再交付 research-lab-ai-native-workspace，把该契约用于研究工作区视觉和交互改造。
3. 如果产品决定暂时保留“未答完也可以生成”，必须在本变更中明确为领域规则，并通过同一字段表达，不能由界面临时放宽。

## Acceptance summary

- 相同输入在服务端始终得到相同的 stage、next_action、can_generate_solution 和 unanswered_question_ids。
- 未回答完 required questions 时，generate-solution 不会执行生成逻辑。
- answer 只更新指定问题，重复回答不会丢失其他答案。
- generate-solution 成功后返回 solution_generated 和 next_action=review_solution。
- save 只能在有方案的 session 上执行，并返回 solution_saved、solution_adopted 或 solution_archived 对应状态。
- 不存在的 session、question 或 node 使用现有 API error envelope，客户端可以区分 404、409 和 422。
- 现有真实数据、空数据和降级提示行为保持不变。
