"use client"

import { Command as CommandPrimitive } from "cmdk"
import { Search } from "lucide-react"
import { cn } from "@/lib/utils"

export function Command({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive>) {
  return <CommandPrimitive className={cn("flex size-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground", className)} {...props} />
}

export function CommandInput({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>) {
  return (
    <div className="flex items-center border-b border-border px-3">
      <Search className="mr-2 size-4 shrink-0 opacity-50" />
      <CommandPrimitive.Input className={cn("h-11 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground", className)} {...props} />
    </div>
  )
}

export const CommandList = CommandPrimitive.List
export const CommandEmpty = CommandPrimitive.Empty
export const CommandGroup = CommandPrimitive.Group
export const CommandItem = CommandPrimitive.Item
