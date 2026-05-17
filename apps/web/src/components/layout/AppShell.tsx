import Link from "next/link"

const navItems = [
  { href: "/", label: "Dashboard" },
  { href: "/runs", label: "Runs" },
  { href: "/reports", label: "Reports" },
  { href: "/sources", label: "Sources" },
  { href: "/workers", label: "Workers" },
  { href: "/memory", label: "Memory" },
  { href: "/approvals", label: "Approvals" },
  { href: "/settings", label: "Settings" }
]

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-surface text-ink">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-line bg-white px-4 py-5 lg:block">
        <div className="mb-8">
          <p className="text-lg font-semibold tracking-normal">NewsRoom</p>
          <p className="text-xs text-muted">Interface Console</p>
        </div>
        <nav className="space-y-1">
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="block rounded-md px-3 py-2 text-sm font-medium text-muted hover:bg-surface hover:text-ink"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </aside>

      <div className="lg:pl-64">
        <header className="border-b border-line bg-white px-4 py-3 lg:hidden">
          <p className="text-base font-semibold">NewsRoom</p>
        </header>
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">{children}</div>
      </div>
    </div>
  )
}
