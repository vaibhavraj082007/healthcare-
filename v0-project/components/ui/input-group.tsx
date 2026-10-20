import * as React from "react"
import { cn } from "cn"

function InputGroup({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="input-group"
      className={cn(
        "flex w-full items-center rounded-lg border border-input bg-transparent transition-colors",
        "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50",
        "*:data-[slot=input]:border-0 *:data-[slot=input]:bg-transparent *:data-[slot=input]:shadow-none",
        "*:data-[slot=input]:focus-visible:ring-0 *:data-[slot=input]:focus-visible:border-0",
        "[&_[data-slot=input]]:min-w-0",
        className
      )}
      {...props}
    />
  )
}

export { InputGroup }