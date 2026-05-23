import type { Metadata } from "next"
import "@/app/globals.css"
import "reactflow/dist/style.css"
import { AppShell } from "@/components/layout/app-shell"
import { Providers } from "@/components/providers"

export const metadata: Metadata = {
  title: "NewsRoom 情报工作台",
  description: "AI 技术情报、证据质量、智能体运行与新闻分析工作台。"
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="h-full" data-theme="light">
      <body className="min-h-full font-sans">
        <Providers>
          <AppShell>{children}</AppShell>
        </Providers>
      </body>
    </html>
  )
}
