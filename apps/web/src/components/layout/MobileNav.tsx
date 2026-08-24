"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"

const items = [
  { href: "/", label: "Home", icon: "⊞" },
  { href: "/runs", label: "Runs", icon: "▷" },
  { href: "/reports", label: "Reports", icon: "≡" },
  { href: "/waits", label: "Waits", icon: "✓" },
  { href: "/sources", label: "Sources", icon: "◎" },
]

export function MobileNav() {
  const pathname = usePathname()
  return (
    <nav className="fixed bottom-0 inset-x-0 z-40 flex border-t border-line bg-white lg:hidden">
      {items.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)
        return (
          <Link
            key={item.href}
            href={item.href}
            className={`flex flex-1 flex-col items-center gap-0.5 py-2.5 text-center transition-colors ${
              active ? "text-accent" : "text-muted"
            }`}
          >
            <span className="text-base leading-none">{item.icon}</span>
            <span className="text-[10px] font-medium">{item.label}</span>
          </Link>
        )
      })}
    </nav>
  )
}
