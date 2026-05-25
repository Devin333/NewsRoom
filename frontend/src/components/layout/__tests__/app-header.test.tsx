import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AppHeader } from "@/components/layout/AppHeader"
import { TooltipProvider } from "@/components/ui/tooltip"
import { useUiStore } from "@/stores/ui-store"

vi.mock("next/navigation", () => ({
  usePathname: () => "/papers"
}))

vi.mock("@/components/auth/account-menu", () => ({
  AccountMenu: () => null
}))

describe("AppHeader", () => {
  beforeEach(() => {
    useUiStore.setState({ locale: "en", theme: "light" })
  })

  it("renders the reduced Portal navigation without Studio management links", () => {
    render(
      <TooltipProvider>
        <AppHeader />
      </TooltipProvider>
    )

    expect(screen.getByRole("link", { name: "Papers" })).toHaveAttribute("href", "/papers")
    expect(screen.getByRole("link", { name: "Today" })).toHaveAttribute("href", "/news")
    expect(screen.getByRole("link", { name: "Trends" })).toHaveAttribute("href", "/topics")
    expect(screen.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports")
    expect(screen.getByRole("link", { name: "Search" })).toHaveAttribute("href", "/search")
    expect(screen.queryByText("Studio")).not.toBeInTheDocument()
    expect(screen.queryByText("Research")).not.toBeInTheDocument()
    expect(screen.queryByText("Topics")).not.toBeInTheDocument()
  })
})
