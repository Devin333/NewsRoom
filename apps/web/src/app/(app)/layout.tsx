import { AppShell } from "@/components/layout/AppShell"
import { ToastProvider } from "@/components/common/Toast"

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <AppShell>{children}</AppShell>
    </ToastProvider>
  )
}
