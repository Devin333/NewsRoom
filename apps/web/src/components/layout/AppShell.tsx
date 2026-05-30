"use client"

import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"

const navItems = [
  { href: "/", label: "Dashboard", icon: "⊞" },
  { href: "/runs", label: "Runs", icon: "▷" },
  { href: "/reports", label: "Reports", icon: "≡" },
  { href: "/sources", label: "Sources", icon: "◎" },
  { href: "/workers", label: "Workers", icon: "⚙" },
  { href: "/memory", label: "Memory", icon: "◈" },
  { href: "/approvals", label: "Approvals", icon: "✓" },
  { href: "/settings", label: "Settings", icon: "⊙" }
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()

  async function handleLogout() {
    await fetch("/api/auth/logout", { method: "POST" })
    router.push("/login")
    router.refresh()
  }

  return (
    <div className="min-h-screen bg-surface text-ink">
      {/* Sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-56 flex-col border-r border-line bg-white lg:flex">
        {/* Logo */}
        <div className="flex h-14 items-center gap-2.5 border-b border-line px-4">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-xs font-bold text-white">N</div>
          <span className="text-sm font-semibold text-ink">NewsRoom</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-2 py-3">
          {navItems.map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors mb-0.5 ${
                  active
                    ? "bg-accent/8 text-accent font-medium"
                    : "text-muted hover:bg-surface hover:text-ink"
                }`}
              >
                <span className="text-base leading-none opacity-70">{item.icon}</span>
                {item.label}
              </Link>
            )
          })}
        </nav>

        {/* Footer */}
        <div className="border-t border-line p-2">
          <button
            onClick={handleLogout}
            className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm text-muted transition-colors hover:bg-surface hover:text-ink"
          >
            <span className="text-base leading-none opacity-70">→</span>
            Sign out
          </button>
        </div>
      </aside>

      {/* Mobile header */}
      <header className="sticky top-0 z-10 flex h-14 items-center border-b border-line bg-white px-4 lg:hidden">
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-xs font-bold text-white">N</div>
        <span className="ml-2.5 text-sm font-semibold">NewsRoom</span>
      </header>

      {/* Main */}
      <div className="lg:pl-56">
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </div>
    </div>
  )
}
