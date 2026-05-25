import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import LoginPage from "@/app/login/page"
import { bootstrapAccount, fetchAuthSession, login } from "@/lib/auth/api"

const navigation = vi.hoisted(() => ({
  refresh: vi.fn(),
  replace: vi.fn(),
  searchParams: new URLSearchParams()
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: navigation.refresh,
    replace: navigation.replace
  }),
  useSearchParams: () => navigation.searchParams
}))

vi.mock("@/lib/auth/api", () => ({
  bootstrapAccount: vi.fn(),
  fetchAuthSession: vi.fn(),
  login: vi.fn()
}))

describe("LoginPage", () => {
  beforeEach(() => {
    navigation.refresh.mockReset()
    navigation.replace.mockReset()
    navigation.searchParams = new URLSearchParams()
    vi.mocked(bootstrapAccount).mockReset()
    vi.mocked(fetchAuthSession).mockReset()
    vi.mocked(login).mockReset()
  })

  it("shows first-admin bootstrap when auth is uninitialized", async () => {
    vi.mocked(fetchAuthSession).mockResolvedValue({ initialized: false, session: null })
    vi.mocked(bootstrapAccount).mockResolvedValue({
      user: { userId: "user-1", username: "admin", role: "admin" },
      sessionId: "sess-1",
      expiresAt: "2026-06-01T00:00:00Z"
    })

    render(<LoginPage />)

    expect(await screen.findByRole("heading", { name: "创建第一个 NewsRoom 账号" })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "correct horse" } })
    fireEvent.submit(screen.getByRole("button", { name: "创建账号" }).closest("form")!)

    await waitFor(() => {
      expect(bootstrapAccount).toHaveBeenCalledWith("admin", "correct horse")
    })
    expect(navigation.replace).toHaveBeenCalledWith("/papers")
    expect(navigation.refresh).toHaveBeenCalled()
  })

  it("shows login after initialization and respects safe next paths", async () => {
    navigation.searchParams = new URLSearchParams({ next: "/papers/reader-paper" })
    vi.mocked(fetchAuthSession).mockResolvedValue({ initialized: true, session: null })
    vi.mocked(login).mockResolvedValue({
      user: { userId: "user-1", username: "admin", role: "admin" },
      sessionId: "sess-1",
      expiresAt: "2026-06-01T00:00:00Z"
    })

    render(<LoginPage />)

    expect(await screen.findByRole("heading", { name: "登录 NewsRoom" })).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText("用户名"), { target: { value: "admin" } })
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "correct horse" } })
    fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!)

    await waitFor(() => {
      expect(login).toHaveBeenCalledWith("admin", "correct horse")
    })
    expect(navigation.replace).toHaveBeenCalledWith("/papers/reader-paper")
  })

  it("redirects an existing session away from login", async () => {
    navigation.searchParams = new URLSearchParams({ next: "//evil.example" })
    vi.mocked(fetchAuthSession).mockResolvedValue({
      initialized: true,
      session: {
        user: { userId: "user-1", username: "admin", role: "admin" },
        sessionId: "sess-1",
        expiresAt: "2026-06-01T00:00:00Z"
      }
    })

    render(<LoginPage />)

    await waitFor(() => {
      expect(navigation.replace).toHaveBeenCalledWith("/papers")
    })
  })
})
