import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AppShell } from "@/components/layout/app-shell"
import { comicSansFontFamily } from "@/lib/fonts"
import { useUiStore } from "@/stores/ui-store"

const navigationState = vi.hoisted(() => ({
  pathname: "/"
}))

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname
}))

vi.mock("@/components/auth/account-menu", () => ({
  AccountMenu: () => null
}))

describe("AppShell", () => {
  beforeEach(() => {
    navigationState.pathname = "/"
    useUiStore.setState({ locale: "en", theme: "light" })
  })

  it.each(["/", "/news", "/community", "/reports", "/search", "/papers", "/papers/tasks/agents", "/papers/methods/tool-use"])("renders the Research header on portal route %s", (pathname) => {
    navigationState.pathname = pathname

    render(
      <AppShell>
        <div>Portal content</div>
      </AppShell>
    )

    expect(screen.getByRole("link", { name: "NewsRoom Research" })).toHaveAttribute("href", "/papers")
    expect(screen.getByRole("button", { name: "Research" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Today" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Trends" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Reports" })).toBeInTheDocument()
    expect(screen.getByRole("navigation", { name: "Portal modules" })).toHaveStyle({ fontFamily: comicSansFontFamily })
    expect(screen.getByPlaceholderText(/search papers/i)).toHaveStyle({ fontFamily: comicSansFontFamily })
    expect(screen.getByPlaceholderText(/search papers/i)).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "Today" })).not.toBeInTheDocument()
  })

  it.each(["/admin", "/studio", "/studio/runs"])("keeps management route %s outside the portal Research header", (pathname) => {
    navigationState.pathname = pathname

    render(
      <AppShell>
        <div>Management content</div>
      </AppShell>
    )

    expect(screen.getByText("Management content")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "NewsRoom Research" })).not.toBeInTheDocument()
  })

  it.each(["/papers/reader-paper", "/papers/reader-paper/read"])("keeps paper reader route %s outside the portal Research header and frame", (pathname) => {
    navigationState.pathname = pathname

    const { container } = render(
      <AppShell>
        <div>Open Reader content</div>
      </AppShell>
    )

    expect(screen.getByText("Open Reader content")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "NewsRoom Research" })).not.toBeInTheDocument()
    expect(container.querySelector("main")).toBeNull()
  })

  it("keeps the admin surface outside the portal Research header", () => {
    navigationState.pathname = "/news"

    render(
      <AppShell surface="admin">
        <div>Admin surface content</div>
      </AppShell>
    )

    expect(screen.getByText("Admin surface content")).toBeInTheDocument()
    expect(screen.queryByRole("link", { name: "NewsRoom Research" })).not.toBeInTheDocument()
  })
})
