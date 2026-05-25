import { BoardCenterPage } from "@/features/studio/boards/components/board-center-page"
import { listBoardDefinitions } from "@/features/studio/boards/api/board-center-server-api"

export default async function StudioBoardsPage() {
  const boardList = await listBoardDefinitions()
  return <BoardCenterPage initialData={boardList} />
}
