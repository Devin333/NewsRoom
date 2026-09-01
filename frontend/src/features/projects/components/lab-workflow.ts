import type { ProjectsLabSession, ProjectsLabStageValue, ProjectsLabNextActionValue } from "@/types/projects"

export type LabWorkflowPresentation = {
  stageLabel: string
  actionLabel: string
  statusTone: "neutral" | "warning" | "success"
  canGenerate: boolean
  unansweredCount: number
  isUnknown: boolean
}

const stageLabels: Record<Exclude<ProjectsLabStageValue, "unknown">, string> = {
  clarifying_requirements: "Clarifying requirements",
  ready_to_generate: "Ready to generate",
  solution_generated: "Solution ready for review",
  solution_saved: "Session saved",
  solution_adopted: "Solution adopted",
  solution_archived: "Solution archived",
}

const actionLabels: Record<Exclude<ProjectsLabNextActionValue, "unknown">, string> = {
  answer_question: "Answer the next clarification",
  generate_solution: "Generate the solution",
  review_solution: "Review the generated solution",
  save_solution: "Save the session",
  none: "No action available",
}

export function presentLabWorkflow(session: ProjectsLabSession): LabWorkflowPresentation {
  const isUnknown = session.current_stage === "unknown" || session.next_action === "unknown"
  const canGenerate = Boolean(
    !isUnknown &&
      session.current_stage === "ready_to_generate" &&
      session.next_action === "generate_solution" &&
      session.can_generate_solution === true &&
      session.unanswered_question_ids.length === 0
  )
  const stageLabel = isUnknown
    ? `Unsupported stage${session.raw_current_stage ? `: ${session.raw_current_stage}` : ""}`
    : stageLabels[session.current_stage as Exclude<ProjectsLabStageValue, "unknown">]
  const actionLabel = isUnknown
    ? "Refresh the session or return to Lab"
    : actionLabels[session.next_action as Exclude<ProjectsLabNextActionValue, "unknown">]
  return {
    stageLabel,
    actionLabel,
    statusTone: isUnknown ? "warning" : canGenerate ? "success" : "neutral",
    canGenerate,
    unansweredCount: session.unanswered_question_ids.length,
    isUnknown,
  }
}

export function labQuestionAnswered(value: unknown): boolean {
  if (value === null || value === undefined) return false
  if (typeof value === "string") return value.trim().length > 0
  if (Array.isArray(value)) return value.length > 0
  return true
}

export function labSolutionValue(session: ProjectsLabSession): Record<string, unknown> | null {
  if (session.solution_json && typeof session.solution_json === "object") return session.solution_json
  return null
}
