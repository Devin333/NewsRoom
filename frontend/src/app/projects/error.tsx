"use client"

import { ErrorState } from "@/components/common/error-state"

export default function ProjectsError({ error, reset }: { error: Error; reset: () => void }) {
  return <ErrorState title="项目雷达异常" message={error.message} onRetry={reset} />
}
