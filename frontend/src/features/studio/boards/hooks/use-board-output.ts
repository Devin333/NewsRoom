"use client"

import { useState } from "react"
import { buildBoardOutput } from "@/features/studio/boards/api/board-center-api"
import type {
  StudioBoardBuildRequest,
  StudioBoardOutputViewModel,
  StudioBoardType
} from "@/types/board"

export function useBoardOutput(boardType: StudioBoardType, initialOutput: StudioBoardOutputViewModel) {
  const [data, setData] = useState(initialOutput)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<Error | undefined>()

  async function buildOutput(request: StudioBoardBuildRequest) {
    setIsLoading(true)
    setError(undefined)
    try {
      const output = await buildBoardOutput(boardType, request)
      setData(output)
      return output
    } catch (caught) {
      const nextError = caught instanceof Error ? caught : new Error("Board output request failed")
      setError(nextError)
      return undefined
    } finally {
      setIsLoading(false)
    }
  }

  return {
    data,
    isLoading,
    isError: Boolean(error),
    error,
    buildOutput,
    refetch: () => undefined
  }
}
