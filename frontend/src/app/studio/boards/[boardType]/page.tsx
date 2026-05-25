import { BoardDetailPage } from "@/features/studio/boards/components/board-center-page"
import { listBoardDefinitions } from "@/features/studio/boards/api/board-center-server-api"
import { buildBoardDetailViewModel } from "@/features/studio/boards/lib/board-adapter"

export default async function StudioBoardDetailRoute({ params }: { params: { boardType: string } }) {
  const boardList = await listBoardDefinitions()
  const detail = buildBoardDetailViewModel(params.boardType, boardList)
  return <BoardDetailPage detail={detail} />
}
