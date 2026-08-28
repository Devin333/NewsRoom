"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  Archive,
  BarChart3,
  Database,
  FileText,
  Gauge,
  Layers3,
  MemoryStick,
  Newspaper,
  Search,
  ShieldCheck,
  Sparkles,
  Target,
  Workflow
} from "lucide-react"
import { cn } from "@/lib/utils"

type NavItem = {
  href: string
  label: string
  icon: React.ComponentType<{ className?: string }>
}

const mainNav: NavItem[] = [
  { href: "/", label: "仪表盘", icon: Gauge },
  { href: "/news", label: "新闻", icon: Newspaper },
  { href: "/topics", label: "主题", icon: Target },
  { href: "/tech", label: "技术雷达", icon: BarChart3 },
  { href: "/reports", label: "报告", icon: FileText },
  { href: "/search", label: "搜索", icon: Search }
]

const studioNav: NavItem[] = [
  { href: "/studio", label: "总览", icon: Sparkles },
  { href: "/studio/runs", label: "智能体运行", icon: Workflow },
  { href: "/studio/sources", label: "数据源", icon: Database },
  { href: "/studio/memory", label: "记忆", icon: MemoryStick },
  { href: "/studio/quality", label: "质量", icon: ShieldCheck },
  { href: "/studio/artifacts", label: "产物", icon: Archive }
]

export function Sidebar({ collapsed }: { collapsed: boolean }) {
  return (
    <aside
      className={cn(
        "hidden min-h-screen shrink-0 border-r border-border bg-card xl:block",
        collapsed ? "w-[68px]" : "w-60"
      )}
    >
      <div className="flex h-14 items-center gap-3 border-b border-border px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md border border-border bg-secondary text-primary">
          <Layers3 className="size-5" />
        </div>
        {!collapsed ? (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">Agora Hub</p>
            <p className="truncate text-xs text-muted-foreground">情报后台</p>
          </div>
        ) : null}
      </div>

      <nav className="space-y-5 px-3 py-4">
        <NavGroup collapsed={collapsed} title="主工作区" items={mainNav} />
        <NavGroup collapsed={collapsed} title="Studio 运营" items={studioNav} />
      </nav>
    </aside>
  )
}

function NavGroup({ title, items, collapsed }: { title: string; items: NavItem[]; collapsed: boolean }) {
  return (
    <div className="space-y-2">
      {!collapsed ? <p className="px-2 text-[11px] font-semibold uppercase tracking-normal text-muted-foreground">{title}</p> : null}
      <div className="space-y-1">
        {items.map((item) => (
          <NavLink key={item.href} item={item} collapsed={collapsed} />
        ))}
      </div>
    </div>
  )
}

function NavLink({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const pathname = usePathname()
  const active = item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`)
  const Icon = item.icon

  return (
    <Link
      href={item.href}
      aria-label={item.label}
      className={cn(
        "flex h-9 items-center gap-3 rounded-md border border-transparent px-3 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground",
        active && "border-border bg-secondary text-foreground shadow-sm",
        collapsed && "justify-center px-0"
      )}
      title={collapsed ? item.label : undefined}
    >
      <Icon className="size-4 shrink-0" />
      {!collapsed ? <span className="truncate">{item.label}</span> : null}
    </Link>
  )
}
