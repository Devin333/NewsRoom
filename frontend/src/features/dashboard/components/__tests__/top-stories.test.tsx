import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { TopStories } from "@/features/dashboard/components/top-stories"
import type { TopStory } from "@/types/dashboard"

describe("TopStories", () => {
  it("links stories to their board detail routes", () => {
    render(<TopStories stories={stories} />)

    expect(screen.getByRole("link", { name: /News story/ })).toHaveAttribute("href", "/news/news-1")
    expect(screen.getByRole("link", { name: /Paper story/ })).toHaveAttribute("href", "/papers/paper-1")
    expect(screen.getByRole("link", { name: /Project story/ })).toHaveAttribute("href", "/projects/project-1")
    expect(screen.getByRole("link", { name: /Community story/ })).toHaveAttribute("href", "/community/community-1")
    expect(screen.getByText("AI 新闻")).toBeInTheDocument()
    expect(screen.getAllByText("继续阅读")).toHaveLength(4)
  })
})

const stories: TopStory[] = [
  story("news", "News story", "/news/news-1"),
  story("paper", "Paper story", "/papers/paper-1"),
  story("project", "Project story", "/projects/project-1"),
  story("community", "Community story", "/community/community-1")
]

function story(board: TopStory["board"], title: string, href: string): TopStory {
  return {
    id: title.toLowerCase().replace(/\s+/g, "-"),
    title,
    summary: `${title} summary`,
    board,
    href
  }
}
