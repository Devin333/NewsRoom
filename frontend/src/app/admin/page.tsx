import type { Metadata } from "next"
import { AdminConsole } from "@/features/admin/components/admin-console"

export const metadata: Metadata = {
  title: "NewsRoom 情报控制台",
  description: "NewsRoom admin intelligence console for ingestion, review, pipeline, agent runtime, quality gates, and publishing control."
}

export default function AdminPage() {
  return <AdminConsole />
}
