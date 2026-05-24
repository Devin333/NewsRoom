import Link from "next/link"
import { Search } from "lucide-react"
import { cn } from "@/lib/utils"

export function SearchButton({ className }: { className?: string }) {
  return (
    <Link
      href="/search"
      aria-label="Search"
      className={cn(
        "inline-flex h-9 items-center justify-center gap-2 rounded-md border border-border bg-card px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
    >
      <Search className="size-4" />
      <span className="hidden sm:inline">Search</span>
    </Link>
  )
}
