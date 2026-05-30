import type { Metadata } from "next"
import "@/styles/globals.css"

export const metadata: Metadata = {
  title: "NewsRoom Console",
  description: "Operational console for NewsRoom"
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
