import { cn } from "cn"

function Spinner({
  className,
  size = "default",
  ...props
}: React.SVGProps<SVGSVGElement> & {
  size?: "sm" | "default" | "lg"
}) {
  return (
    <svg
      role="img"
      aria-label="Loading"
      className={cn(
        "animate-spin text-current",
        {
          "size-4": size === "sm",
          "size-5": size === "default",
          "size-8": size === "lg",
        },
        className
      )}
      viewBox="0 0 24 24"
      fill="none"
      {...props}
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  )
}

export { Spinner }
