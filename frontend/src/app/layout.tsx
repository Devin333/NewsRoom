import type { Metadata } from "next"
import "@/app/globals.css"
import "@/components/papers/open-reader/open-reader.module.css"
import "@/components/papers/paper-reader/paper-document-reader.module.css"
import "katex/dist/katex.min.css"
import "reactflow/dist/style.css"
import { AppShell } from "@/components/layout/app-shell"
import { Providers } from "@/components/providers"
import { getFrontendSurface } from "@/lib/frontend-surface"

export const metadata: Metadata = {
  title: "Agora Hub 情报工作台",
  description: "新闻、论文与项目的一体化情报、证据质量和智能体运行工作台。"
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
