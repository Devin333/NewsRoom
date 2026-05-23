import { BookOpenText, Code2, Component } from "lucide-react"
import Link from "next/link"
import type { DashboardOverview } from "@/types/dashboard"

const items = [
  { key: "paper", label: "论文", href: "/tech/papers", icon: BookOpenText },
  { key: "repo", label: "仓库", href: "/tech/repos", icon: Code2 },
  { key: "framework", label: "框架", href: "/tech/frameworks", icon: Component }
] as const

export function TechRadarPreview({ radar }: { radar: DashboardOverview["techRadar"] }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">技术雷达预览</h2>
        <Link href="/tech" className="text-sm text-accent hover:text-foreground">
          打开雷达
        </Link>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {items.map((item) => {
          const Icon = item.icon
          return (
            <Link key={item.key} href={item.href} className="rounded-lg border border-border bg-card p-4 hover:border-accent/50">
              <span className="flex h-9 w-9 items-center justify-center rounded-md bg-secondary text-accent">
                <Icon className="h-4 w-4" />
              </span>
              <p className="mt-4 text-xs font-medium uppercase text-muted-foreground">{item.label}</p>
              <h3 className="mt-2 text-sm font-semibold leading-5 text-foreground">{radar[item.key]}</h3>
            </Link>
          )
        })}
      </div>
    </section>
  )
}
