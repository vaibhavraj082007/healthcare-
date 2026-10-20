import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "cn"

const badgeVariants = cva(
  "inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        default: "border-transparent bg-secondary text-secondary-foreground",
        accent: "border-transparent bg-primary/10 text-primary",
        success: "border-transparent bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
        destructive:
          "border-transparent bg-destructive/10 text-destructive",
        outline: "border-border text-muted-foreground",
        warning: "border-transparent bg-amber-500/15 text-amber-700 dark:text-amber-400",
      },
    },
    defaultVariants: {
      tone: "default",
    },
  },
)

function Badge({
  className,
  tone = "default",
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return (
    <span
      data-slot="badge"
      className={cn(badgeVariants({ tone }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }