import { safeApiGet } from "@/lib/api/server"
import { adaptBoardList } from "@/features/studio/boards/lib/board-adapter"
import type { StudioBoardListViewModel } from "@/types/board"

export async function listBoardDefinitions(): Promise<StudioBoardListViewModel> {
  const response = await safeApiGet<unknown>("/api/v1/boards")
  if (!response.ok) {
    return adaptBoardList(undefined, {
      fallbackReason: `Board API unavailable: ${response.errorMessage}`
    })
  }
  return adaptBoardList(response.data)
}
