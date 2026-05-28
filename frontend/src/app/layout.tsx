import type { Metadata } from "next"
import "@/app/globals.css"
import "katex/dist/katex.min.css"
import "reactflow/dist/style.css"
import { AppShell } from "@/components/layout/app-shell"
import { Providers } from "@/components/providers"
import { getFrontendSurface } from "@/lib/frontend-surface"

export const metadata: Metadata = {
  title: "NewsRoom 情报工作台",
  description: "AI 技术情报、证据质量、智能体运行与新闻分析工作台。"
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const surface = getFrontendSurface()

  return (
    <html lang="zh-CN" className="h-full" data-theme="light" data-newsroom-surface={surface}>
      <body className="min-h-full font-sans">
        <Providers>
          <AppShell surface={surface}>{children}</AppShell>
        </Providers>
      </body>
    </html>
  )
}
