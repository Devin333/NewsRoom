"use client"

import { ErrorState } from "@/components/common/error-state"

export default function ProjectDetailError({ error, reset }: { error: Error; reset: () => void }) {
  return <ErrorState title="项目详情异常" message={error.message} onRetry={reset} />
}
