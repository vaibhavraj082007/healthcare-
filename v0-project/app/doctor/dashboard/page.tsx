"use client"

import * as React from "react"
import Link from "next/link"
import { ArrowUpRight, ClipboardList, Flag, Search, X } from "lucide-react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { RequireRole } from "@/components/dashboard/route-guard"
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Spinner } from "@/components/ui/spinner"
import {
  type CaseListItem,
  type CaseStatus,
  type CaseSummary,
  type NlSearchResult,
  type SeverityBand,
  doctorApi,
} from "@/lib/api"
import { useSession } from "@/lib/session"
import { cn } from "cn"

const BAND_TONE: Record<SeverityBand, "destructive" | "warning" | "success"> = {
  High: "destructive",
  Medium: "warning",
  Low: "success",
}

const STATUS_TONE: Record<CaseStatus, "accent" | "warning" | "outline" | "success"> = {
  New: "accent",
  Claimed: "warning",
  Contacted: "outline",
  Reviewed: "success",
}

const BANDS: (SeverityBand | "All")[] = ["All", "High", "Medium", "Low"]
const STATUSES: (CaseStatus | "All")[] = [
  "All",
  "New",
  "Claimed",
  "Contacted",
  "Reviewed",
]

function StatCard({
  label,
  value,
  tone,
}: {
  label: string
  value: string | number
  tone?: "default" | "warning" | "danger"
}) {
  return (
    <Card className="gap-1">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle
          className={
            tone === "danger"
              ? "text-destructive"
              : tone === "warning"
                ? "text-amber-600 dark:text-amber-400"
                : undefined
          }
        >
          {value}
        </CardTitle>
      </CardHeader>
    </Card>
  )
}

function CaseRow({ item }: { item: CaseListItem }) {
  return (
    <Link
      href={`/doctor/cases/${item.image_id}`}
      className="flex w-full flex-wrap items-center justify-between gap-2 rounded-xl border bg-background px-4 py-3 text-left outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="min-w-0">
        <p className="font-heading text-sm font-bold text-foreground">
          {item.patient_name}
          <span className="ml-2 font-normal text-muted-foreground">
            #{item.image_id.slice(0, 8)}
          </span>
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground">
          <span>{item.phc ?? "—"}</span>
          <span aria-hidden>·</span>
          <span>
            {item.analyzed_at ? new Date(item.analyzed_at).toLocaleString() : "Not analyzed"}
          </span>
          {item.worker_name && (
            <>
              <span aria-hidden>·</span>
              <span>ASHA {item.worker_name}</span>
            </>
          )}
          {item.assigned_doctor_name && (
            <>
              <span aria-hidden>·</span>
              <span className="text-foreground">{item.assigned_doctor_name}</span>
            </>
          )}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {item.flagged && (
          <Badge tone="destructive">
            <Flag className="size-3" aria-hidden />
            Flagged
          </Badge>
        )}
        <Badge tone={BAND_TONE[item.severity_band]}>{item.severity_band}</Badge>
        <Badge tone={STATUS_TONE[item.status]}>{item.status}</Badge>
        <ArrowUpRight className="size-4 text-muted-foreground" aria-hidden />
      </div>
    </Link>
  )
}

function DoctorPortal() {
  const { token } = useSession()
  const [summary, setSummary] = React.useState<CaseSummary | null>(null)
  const [items, setItems] = React.useState<CaseListItem[] | null>(null)
  const [search, setSearch] = React.useState<NlSearchResult | null>(null)
  const [query, setQuery] = React.useState("")
  const [band, setBand] = React.useState<SeverityBand | "All">("All")
  const [status, setStatus] = React.useState<CaseStatus | "All">("All")
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [retry, setRetry] = React.useState(0)

  const params = React.useMemo(() => {
    const p: Record<string, string> = {}
    if (band !== "All") p.severity = band
    if (status !== "All") p.status = status
    return p
  }, [band, status])

  React.useEffect(() => {
    if (!token) return
    let active = true
    const t = token

    function load() {
      doctorApi
        .cases(t, params)
        .then((list) => {
          if (active) {
            setItems(list)
            setError(null)
          }
        })
        .catch((err: Error) => {
          if (active) setError(err.message)
        })
      doctorApi
        .summary(t)
        .then((s) => {
          if (active) setSummary(s)
        })
        .catch(() => {
          // summary is secondary; queue errors already surfaced above
        })
    }

    load()
    const id = window.setInterval(load, 30000)
    return () => {
      active = false
      window.clearInterval(id)
    }
  }, [token, params, retry])

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = query.trim()
    if (!q || !token) return
    setBusy(true)
    setError(null)
    try {
      const result = await doctorApi.search(token, q)
      setSearch(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Search failed")
    } finally {
      setBusy(false)
    }
  }

  function clearSearch() {
    setSearch(null)
    setQuery("")
  }

  const visible = React.useMemo(() => {
    if (search) {
      return (search.items ?? []).filter((item) => {
        if (band !== "All" && item.severity_band !== band) return false
        if (status !== "All" && item.status !== status) return false
        return true
      })
    }
    return items
  }, [search, items, band, status])

  return (
    <DashboardShell
      title="Case queue"
      description="AI-screened cases across your PHC network, sorted by urgency. Flagged cases are pinned to the top."
    >
      {error && (
        <Alert variant="destructive">
          <ClipboardList />
          <AlertTitle>Could not load the case queue</AlertTitle>
          <AlertDescription>
            {error}{" "}
            <Button
              variant="link"
              className="h-auto p-0 text-destructive"
              onClick={() => setRetry((n) => n + 1)}
            >
              Try again
            </Button>
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Awaiting review" value={summary?.awaiting_review ?? "—"} />
        <StatCard
          label="Flagged pending"
          value={summary?.flagged_pending ?? "—"}
          tone="danger"
        />
        <StatCard
          label="Claimed by me"
          value={summary?.claimed_by_me ?? "—"}
          tone="warning"
        />
        <StatCard label="Reported today" value={summary?.today_reported ?? "—"} />
      </div>

      {/* Constrained natural-language search */}
      <div className="mt-5">
        <form
          onSubmit={handleSearch}
          className="flex flex-col gap-2 sm:flex-row sm:items-center"
        >
          <div className="relative flex-1">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g. high severity cases · new cases in Badlapur · flagged scans from this week"
              className="pl-9 pr-9"
              aria-label="Search the case queue in plain language"
            />
            {search && (
              <button
                type="button"
                onClick={clearSearch}
                aria-label="Clear search"
                className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded-md p-1 text-muted-foreground outline-none transition-colors hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
              >
                <X className="size-4" />
              </button>
            )}
          </div>
          <Button type="submit" disabled={busy} className="shrink-0">
            {busy && <Spinner size="sm" />}
            Search
          </Button>
        </form>
        <p className="mt-1.5 text-xs text-muted-foreground">
          The search only understands screening-queue concepts (severity, status,
          flagged, PHC/village, dates) — it never answers general questions.
        </p>
      </div>

      {search && (
        <Alert className="mt-3 border-accent/40 bg-secondary/40">
          <Search className="text-primary" aria-hidden />
          <AlertTitle>
            {search.matched ? `Matched ${visible?.length ?? 0} case(s)` : "No matching filter"}
          </AlertTitle>
          <AlertDescription>{search.message}</AlertDescription>
        </Alert>
      )}

      {/* Quick filters */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-center gap-1">
          <span className="mr-1 text-xs font-medium text-muted-foreground">Severity</span>
          {BANDS.map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => setBand(b)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                band === b
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {b}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          <span className="mr-1 text-xs font-medium text-muted-foreground">Status</span>
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                status === s
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 space-y-2">
        {items === null && !search ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner size="sm" /> Loading the queue…
          </div>
        ) : visible && visible.length > 0 ? (
          visible.map((item) => <CaseRow key={item.image_id} item={item} />)
        ) : (
          <p className="text-sm text-muted-foreground">
            No cases match this view. New synced cases will appear here when they
            arrive.
          </p>
        )}
      </div>
    </DashboardShell>
  )
}

export default function DoctorDashboardPage() {
  return (
    <RequireRole roles={["doctor", "ophthalmologist"]}>
      <DoctorPortal />
    </RequireRole>
  )
}