import { newsroomApiPost } from "@/lib/api/newsroom-api"
import { adaptBoardOutput } from "@/features/studio/boards/lib/board-adapter"
import type {
  StudioBoardBuildRequest,
  StudioBoardOutputViewModel,
  StudioBoardType
} from "@/types/board"

export async function buildBoardOutput(
  boardType: StudioBoardType,
  request: StudioBoardBuildRequest
): Promise<StudioBoardOutputViewModel> {
  const response = await newsroomApiPost<unknown>(`/api/v1/boards/${encodeURIComponent(boardType)}/output`, request)
  if (!response.ok) {
    return adaptBoardOutput(boardType, undefined, {
      fallbackReason: `Board output API unavailable: ${response.error.message}`
    })
  }
  return adaptBoardOutput(boardType, response.data)
}
