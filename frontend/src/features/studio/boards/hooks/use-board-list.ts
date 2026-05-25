"use client"

import { useMemo } from "react"
import { adaptBoardList } from "@/features/studio/boards/lib/board-adapter"
import type { StudioBoardListViewModel } from "@/types/board"

export function useBoardList(initialData?: StudioBoardListViewModel) {
  const data = useMemo(() => initialData ?? adaptBoardList(undefined), [initialData])

  return {
    data,
    isLoading: false,
    isError: false,
    refetch: () => undefined
  }
}
