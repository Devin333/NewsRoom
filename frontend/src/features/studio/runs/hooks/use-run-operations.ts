"use client"

import { useState } from "react"
import { postRunOperation } from "@/features/studio/runs/api/run-center-operations-api"
import type { RunOperationPayload, RunOperationResult, RunOperationType } from "@/types/agent"

export function useRunOperations(runId: string) {
  const [isPending, setIsPending] = useState(false)
  const [result, setResult] = useState<RunOperationResult>()

  async function execute(operation: RunOperationType, payload: RunOperationPayload) {
    setIsPending(true)
    const nextResult = await postRunOperation(runId, operation, payload)
    setResult(nextResult)
    setIsPending(false)
    return nextResult
  }

  return {
    execute,
    isPending,
    result,
    clearResult: () => setResult(undefined)
  }
}
