import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import {
  BoardCenterPage,
  BoardDetailPage
} from "@/features/studio/boards/components/board-center-page"
import { adaptBoardList, buildBoardDetailViewModel } from "@/features/studio/boards/lib/board-adapter"
import { fallbackOutputForBoard } from "@/features/studio/boards/lib/board-fallback-data"

vi.mock("@/features/studio/boards/api/board-center-api", () => ({
  buildBoardOutput: vi.fn()
}))

describe("BoardCenterPage", () => {
  it("renders five board entries with detail links", () => {
    const list = adaptBoardList(undefined)
    render(<BoardCenterPage initialData={list} />)

    expect(screen.getByRole("heading", { name: "业务板中心" })).toBeInTheDocument()
    expect(screen.getByText("AI News")).toBeInTheDocument()
    expect(screen.getByText("Project Radar")).toBeInTheDocument()
    expect(screen.getByText("Paper Radar")).toBeInTheDocument()
    expect(screen.getByText("Community Pulse")).toBeInTheDocument()
    expect(screen.getByText("Cross Board")).toBeInTheDocument()
    expect(screen.getByRole("link", { name: /AI News/i })).toHaveAttribute("href", "/studio/boards/ai_news")
  })

  it("renders Cross Board with a distinct cross-board panel", () => {
    const list = adaptBoardList(undefined)
    const detail = buildBoardDetailViewModel("cross_board", list, fallbackOutputForBoard("cross_board"))
    render(<BoardDetailPage detail={detail} />)

    expect(screen.getByText("Cross-board associations")).toBeInTheDocument()
    expect(screen.getByText("Trend paths")).toBeInTheDocument()
    expect(screen.getByText("Shared entities")).toBeInTheDocument()
    expect(screen.getByText("Conflict signals")).toBeInTheDocument()
    expect(screen.getByText("Integrated report entry")).toBeInTheDocument()
  })

  it("shows validation error for invalid sample JSON", () => {
    const list = adaptBoardList(undefined)
    const detail = buildBoardDetailViewModel("ai_news", list, fallbackOutputForBoard("ai_news"))
    render(<BoardDetailPage detail={detail} />)

    fireEvent.change(screen.getByLabelText("样例条目 JSON"), { target: { value: "{nope" } })
    fireEvent.click(screen.getByRole("button", { name: /构建输出/ }))

    expect(screen.getByRole("alert")).toHaveTextContent(/Expected property name|JSON/i)
  })
})
