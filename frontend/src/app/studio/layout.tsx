import type { ReactNode } from "react"
import { StudioShell } from "@/features/studio/shared/components/studio-shell"

export default function StudioLayout({ children }: { children: ReactNode }) {
  return <StudioShell>{children}</StudioShell>
}
