import { BookOpenText, Code2, Component, Sparkles } from "lucide-react"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import type { TechRadarItem } from "@/types/dashboard"

const categoryIcon = {
  paper: BookOpenText,
  project: Code2,
  framework: Component,
  model: Sparkles,
  tool: Component,
  community: Sparkles
}

const categoryLabels: Record<TechRadarItem["category"], string> = {
  paper: "论文",
  project: "项目",
  framework: "框架",
  model: "模型",
  tool: "工具",
  community: "社区"
}

export function TechRadarPreview({ radar }: { radar: TechRadarItem[] }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-foreground">技术雷达预览</h2>
        <Link href="/projects" className="text-sm text-accent hover:text-foreground">
          打开雷达
        </Link>
      </div>
      <div className="grid gap-3 md:grid-cols-3">
        {radar.slice(0, 6).map((item) => {
          const Icon = categoryIcon[item.category] ?? Component
          const card = (
            <Card className="h-full p-4 transition hover:border-accent/50 hover:bg-secondary/35">
              <span className="flex h-9 w-9 items-center justify-center rounded-md bg-secondary text-accent">
                <Icon className="h-4 w-4" />
              </span>
              <div className="mt-4 flex flex-wrap gap-2">
                <Badge variant="accent">{categoryLabels[item.category]}</Badge>
                {item.score !== undefined ? <Badge variant="muted">评分 {item.score}</Badge> : null}
              </div>
              <h3 className="mt-3 text-sm font-semibold leading-5 text-foreground">{item.name}</h3>
              <p className="mt-2 line-clamp-3 text-sm leading-5 text-muted-foreground">{item.summary}</p>
            </Card>
          )
          return item.href ? (
            <Link key={item.id} href={item.href} className="block">
              {card}
            </Link>
          ) : (
            <div key={item.id}>{card}</div>
          )
        })}
      </div>
    </section>
  )
}
