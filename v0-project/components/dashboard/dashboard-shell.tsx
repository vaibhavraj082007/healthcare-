"use client"

import * as React from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { Bell, CheckCircle2, LayoutDashboard, LogOut, ScanEye } from "lucide-react"

import { Button } from "@/components/ui/button"
import { telemedApi } from "@/lib/api"
import { useSession } from "@/lib/session"
import { cn } from "cn"

const roleLabel: Record<string, string> = {
  patient: "Patient",
  health_worker: "Health Worker",
  doctor: "Doctor",
  ophthalmologist: "Ophthalmologist",
  admin: "Administrator",
}

const QUEUE_POLL_MS = 20000

interface NavItem {
  label: string
  href: string
  badge?: number
  flagged?: number
}

interface DashboardShellProps {
  children: React.ReactNode
  title: string
  description?: string
  sidebar?: boolean
}

export function DashboardShell({
  children,
  title,
  description,
  sidebar = true,
}: DashboardShellProps) {
  const { user, token, signOut } = useSession()
  const router = useRouter()

  const [queueCount, setQueueCount] = React.useState(0)
  const [queueFlagged, setQueueFlagged] = React.useState(0)
  const [toast, setToast] = React.useState<string | null>(null)

  const isReviewer = user?.role === "doctor" || user?.role === "ophthalmologist"
  const lastCountRef = React.useRef<number | null>(null)

  // Phase 4 — polling notifications (§5): badge + toast when new cases land.
  React.useEffect(() => {
    if (!isReviewer || !token) return
    const t = token
    let cancelled = false

    async function poll() {
      try {
        const count = await telemedApi.queueCount(t)
        if (cancelled) return
        setQueueCount(count.unseen)
        setQueueFlagged(count.unseen_flagged)
        const prev = lastCountRef.current
        if (prev !== null && count.unseen > prev) {
          const delta = count.unseen - prev
          setToast(
            `${delta} new case${delta === 1 ? "" : "s"} awaiting review${
              count.unseen_flagged > 0 ? " — flagged for priority" : ""
            }`,
          )
        }
        lastCountRef.current = count.unseen
      } catch {
        // backend offline — keep the last known counts; next poll recovers
      }
    }

    poll()
    const id = window.setInterval(poll, QUEUE_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(id)
    }
  }, [token, isReviewer])

  React.useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), 6000)
    return () => window.clearTimeout(id)
  }, [toast])

  const navItems = (() => {
    if (!user) return [] as NavItem[]
    switch (user.role) {
      case "patient":
        return [{ label: "My scans", href: "/dashboard/patient" }]
      case "health_worker":
        return [{ label: "Patients & scans", href: "/dashboard/worker" }]
      case "doctor":
      case "ophthalmologist":
        return [
          {
            label: "Cases",
            href: "/doctor/dashboard",
          },
          {
            label: "Ophthalmology review",
            href: "/dashboard/doctor",
            badge: queueCount,
            flagged: queueFlagged,
          },
        ]
      case "admin":
        return [
          { label: "Overview", href: "/admin" },
          { label: "Model info", href: "/admin/models" },
        ]
      default:
        return []
    }
  })()

  function handleSignOut() {
    signOut()
    router.push("/login")
  }

  return (
    <div className="flex min-h-dvh w-full flex-col bg-background">
      <header className="sticky top-0 z-20 border-b bg-background/90 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4">
          <div className="flex items-center gap-2">
            <ScanEye className="size-5 text-primary" aria-hidden />
            <Link
              href="/"
              className="font-heading text-base font-bold tracking-tight"
            >
              NetraScan
            </Link>
            <span className="ml-1 hidden rounded-full bg-secondary px-2.5 py-0.5 text-xs font-medium text-secondary-foreground sm:inline-block">
              {user ? roleLabel[user.role] ?? user.role : ""}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {user && (
              <span className="hidden text-sm text-muted-foreground md:inline-block">
                {user.full_name}
              </span>
            )}
            <Button variant="ghost" size="sm" onClick={handleSignOut}>
              <LogOut />
              Sign out
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-6 md:flex-row">
        {sidebar && navItems.length > 0 && (
          <nav
            aria-label="Dashboard"
            className="flex shrink-0 gap-1 md:w-56 md:flex-col"
          >
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                <LayoutDashboard className="size-4" aria-hidden />
                {item.label}
                {item.badge != null && item.badge > 0 && (
                  <span
                    className={cn(
                      "ml-auto inline-flex min-w-5 items-center justify-center rounded-full px-1.5 py-0.5 text-xs font-semibold",
                      (item.flagged ?? 0) > 0
                        ? "bg-destructive text-destructive-foreground"
                        : "bg-primary text-primary-foreground",
                    )}
                  >
                    {item.badge}
                  </span>
                )}
              </Link>
            ))}
          </nav>
        )}

        <main className="min-w-0 flex-1">
          <div className="mb-6 flex flex-col gap-1">
            <h1 className="font-heading text-2xl font-bold tracking-tight">
              {title}
            </h1>
            {description && (
              <p className="text-sm text-muted-foreground">{description}</p>
            )}
          </div>
          {children}
        </main>
      </div>

      {/* Phase 4 — in-app polling notification toast */}
      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 right-4 z-50 flex max-w-sm items-start gap-3 rounded-xl border bg-background p-4 shadow-lg"
        >
          <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-primary" />
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
              <Bell className="size-3.5" aria-hidden />
              New review cases
            </span>
            <p className="text-sm text-muted-foreground">{toast}</p>
          </div>
          <button
            type="button"
            onClick={() => setToast(null)}
            aria-label="Dismiss notification"
            className="ml-1 shrink-0 rounded-md p-1 text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}