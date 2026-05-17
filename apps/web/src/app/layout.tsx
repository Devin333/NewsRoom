import type { Metadata } from "next"
import "@/styles/globals.css"
import { AppShell } from "@/components/layout/AppShell"

export const metadata: Metadata = {
  title: "NewsRoom Console",
  description: "Operational console for NewsRoom"
}

export default function RootLayout({
  children
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  )
}
