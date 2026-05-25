import { redirect } from "next/navigation"
import { StudioHomePageClient } from "@/app/studio/studio-page-client"
import { StudioShell } from "@/features/studio/shared/components/studio-shell"
import { getFrontendSurface } from "@/lib/frontend-surface"

export const dynamic = "force-dynamic"

export default function HomePage() {
  if (getFrontendSurface() !== "admin") {
    redirect("/papers")
  }

  return (
    <StudioShell>
      <StudioHomePageClient />
    </StudioShell>
  )
}
