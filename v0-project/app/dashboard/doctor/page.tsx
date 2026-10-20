"use client"

import * as React from "react"
import { CheckCircle2, ClipboardCheck, Info, Radio } from "lucide-react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { RequireRole } from "@/components/dashboard/route-guard"
import { ScreeningReportPanel } from "@/components/reports/report-panel"
import { ScanImageViewer } from "@/components/reports/image-viewer"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import {
  type DoctorQueueItem,
  type RoleStats,
  type SignOffInput,
  dashboardApi,
  telemedApi,
} from "@/lib/api"
import { useSession } from "@/lib/session"
import { findingBadgeTone, isReviewItem } from "@/lib/consistency"
import { cn } from "cn"

const gradeLabels = ["No DR", "Mild", "Moderate", "Severe", "Proliferative"]
const SYNC_TONE: Record<string, "success" | "warning" | "destructive" | "accent"> =
  {
    synced: "success",
    syncing: "accent",
    queued: "warning",
    failed: "destructive",
  }

type Filter = "all" | "flagged" | "awaiting"

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

/* ------------------------------------------------------------------ */
/* Sign-off form                                                       */
/* ------------------------------------------------------------------ */

function SignOffForm({
  item,
  token,
  onDone,
}: {
  item: DoctorQueueItem
  token: string
  onDone: (result: { image_id: string; decision: string }) => void
}) {
  const [decision, setDecision] = React.useState<SignOffInput["decision"]>("Approved")
  const [grade, setGrade] = React.useState("0")
  const [notes, setNotes] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      if (decision === "Revised" && !grade) {
        setError("Select the revised severity grade.")
        setBusy(false)
        return
      }
      const result = await telemedApi.signOff(token, {
        image_id: item.image_id,
        decision,
        revised_grade: decision === "Revised" ? Number(grade) : null,
        doctor_notes: notes.trim() || undefined,
      })
      onDone({ image_id: result.image_id, decision: result.decision })
    } catch (err) {
      const message = err instanceof Error ? err.message : "Sign-off failed"
      // Sign-off summarises the backend detail inside the message when present.
      setError(message)
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border bg-muted/20 p-3">
      <p className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <ClipboardCheck className="size-4 text-primary" aria-hidden />
        Sign off this case
      </p>

      <RadioGroup
        className="mt-3 grid gap-1.5 sm:grid-cols-3"
        value={decision}
        onValueChange={(value) => setDecision(value as SignOffInput["decision"])}
      >
        <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm data-[checked=true]:border-primary data-[checked=true]:bg-primary/5">
          <RadioGroupItem value="Approved" />
          Approve
        </label>
        <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm data-[checked=true]:border-primary data-[checked=true]:bg-primary/5">
          <RadioGroupItem value="Revised" />
          Revise grade
        </label>
        <label className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm data-[checked=true]:border-primary data-[checked=true]:bg-primary/5">
          <RadioGroupItem value="Rejected" />
          Reject
        </label>
      </RadioGroup>

      {decision === "Revised" && (
        <div className="mt-3 flex items-center gap-3">
          <label htmlFor="revised-grade" className="text-sm text-muted-foreground">
            Revised severity
          </label>
          <select
            id="revised-grade"
            value={grade}
            onChange={(e) => setGrade(e.target.value)}
            className="rounded-md border bg-background px-2 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {gradeLabels.map((label, i) => (
              <option key={i} value={i}>
                {label} (grade {i})
              </option>
            ))}
          </select>
          {item.icdr_grade != null && (
            <span className="text-xs text-muted-foreground">
              AI said: {gradeLabels[item.icdr_grade] ?? item.icdr_grade} (grade{" "}
              {item.icdr_grade})
            </span>
          )}
        </div>
      )}

      <div className="mt-3">
        <label
          htmlFor={`notes-${item.image_id}`}
          className="text-sm text-muted-foreground"
        >
          Doctor&apos;s notes{" "}
          <span className="text-xs">
            (required when rejecting; optional otherwise)
          </span>
        </label>
        <textarea
          id={`notes-${item.image_id}`}
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Clinical note for the patient record…"
          className="mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>

      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}

      <Button
        type="button"
        size="sm"
        onClick={submit}
        disabled={busy}
        className="mt-3"
      >
        {busy ? <Spinner size="sm" /> : <CheckCircle2 className="size-4" />}
        {busy ? "Submitting…" : "Submit sign-off"}
      </Button>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Queue item                                                          */
/* ------------------------------------------------------------------ */

function ReviewCase({
  item,
  token,
  onSigned,
}: {
  item: DoctorQueueItem
  token: string
  onSigned: (imageId: string) => void
}) {
  const [open, setOpen] = React.useState(false)
  const seenRef = React.useRef(false)

  React.useEffect(() => {
    if (open && !seenRef.current && !item.signed_off) {
      seenRef.current = true
      telemedApi.markSeen(token, item.image_id).catch(() => {
        // non-fatal: seen tracking is best-effort
      })
    }
  }, [open, item.signed_off, item.image_id, token])

  const flagged = isReviewItem(item.consistency_status)

  return (
    <Card className={cn("overflow-hidden", flagged && !item.signed_off && "border-destructive/40")}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left outline-none transition-colors hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
      >
        <div className="min-w-0">
          <p className="font-heading text-sm font-bold text-foreground">
            {item.patient_name}
            <span className="ml-2 font-normal text-muted-foreground">
              scan #{item.image_id.slice(0, 6)}
            </span>
          </p>
          <p className="text-xs text-muted-foreground">
            {item.analyzed_at
              ? new Date(item.analyzed_at).toLocaleString()
              : "Not yet analyzed"}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {!item.viewed && !item.signed_off && (
            <span className="size-2 rounded-full bg-destructive" title="Unseen" />
          )}
          <Badge tone={findingBadgeTone(item.consistency_status)}>
            {item.consistency_status}
          </Badge>
          <Badge tone={SYNC_TONE[item.sync_status] ?? "accent"}>
            {item.sync_status}
          </Badge>
          {item.signed_off && (
            <Badge tone="success">{item.signed_decision ?? "Signed"}</Badge>
          )}
          <Radio
            className={cn(
              "size-4 text-muted-foreground transition-transform",
              open && "rotate-90",
            )}
            aria-hidden
          />
        </div>
      </button>

      {open && (
        <CardContent className="space-y-4 border-t pt-4">
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="rounded-lg bg-muted/60 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                AI severity
              </p>
              <p className="mt-1 font-heading text-base font-bold">
                {item.icdr_grade !== null
                  ? `${gradeLabels[item.icdr_grade] ?? item.icdr_grade} (${item.icdr_grade})`
                  : "—"}
              </p>
            </div>
            <div className="rounded-lg bg-muted/60 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Confidence
              </p>
              <p className="mt-1 text-sm">
                {item.icdr_confidence !== null
                  ? `${Math.round(item.icdr_confidence * 100)}%`
                  : "—"}
              </p>
            </div>
            <div className="rounded-lg bg-muted/60 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Review priority
              </p>
              <p className="mt-1 text-sm capitalize">
                {flagged ? "Flagged — review first" : "Standard"}
              </p>
            </div>
          </div>

          <ScanImageViewer
            imageId={item.image_id}
            token={token}
            label={`${item.patient_name} — retina scan`}
          />

          <ScreeningReportPanel imageId={item.image_id} token={token} variant="clinical" />

          {item.signed_off ? (
            <p className="rounded-md bg-muted/40 p-3 text-sm text-muted-foreground">
              <strong className="text-foreground">
                {item.signed_decision ?? "Signed off"}
              </strong>{" "}
              — this case has already been handled.
            </p>
          ) : item.sync_status === "failed" ? (
            <p className="text-sm text-muted-foreground">
              Transmission to the telemedicine server failed and will be retried
              automatically.
            </p>
          ) : item.sync_status === "queued" ? (
            <p className="text-sm text-muted-foreground">
              This case has not fully synced (waiting for connection). Review it
              while it syncs in the background.
            </p>
          ) : (
            <SignOffForm
              item={item}
              token={token}
              onDone={() => onSigned(item.image_id)}
            />
          )}
        </CardContent>
      )}
    </Card>
  )
}

/* ------------------------------------------------------------------ */
/* Dashboard page                                                      */
/* ------------------------------------------------------------------ */

function ReviewPortal() {
  const { token } = useSession()
  const [queue, setQueue] = React.useState<DoctorQueueItem[] | null>(null)
  const [stats, setStats] = React.useState<RoleStats | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [retry, setRetry] = React.useState(0)
  const [filter, setFilter] = React.useState<Filter>("all")
  const [flash, setFlash] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)

  React.useEffect(() => {
    if (!token) return
    const t = token
    let active = true

    function refresh() {
      Promise.all([telemedApi.queue(t), dashboardApi.stats(t)])
        .then(([q, s]) => {
          if (active) {
            setQueue(q)
            setStats(s)
            setError(null)
          }
        })
        .catch((err: Error) => {
          if (active) setError(err.message)
        })
    }

    refresh()
    const id = window.setInterval(refresh, 30000)
    return () => {
      active = false
      window.clearInterval(id)
    }
  }, [token, retry])

  React.useEffect(() => {
    if (!flash) return
    const id = window.setTimeout(() => setFlash(null), 5000)
    return () => window.clearTimeout(id)
  }, [flash])

  const visible = React.useMemo(() => {
    if (!queue) return null
    if (filter === "flagged") return queue.filter((i) => isReviewItem(i.consistency_status))
    if (filter === "awaiting") return queue.filter((i) => !i.signed_off)
    return queue
  }, [queue, filter])

  async function handleRefresh() {
    if (!token) return
    setBusy(true)
    try {
      const [q, s] = await Promise.all([
        telemedApi.queue(token),
        dashboardApi.stats(token),
      ])
      setQueue(q)
      setStats(s)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the queue")
    } finally {
      setBusy(false)
    }
  }

  const awaiting = queue?.filter((i) => !i.signed_off) ?? []
  const flaggedCount = queue?.filter((i) => isReviewItem(i.consistency_status)).length ?? 0

  return (
    <DashboardShell
      title="Ophthalmology review"
      description="Sign off AI-screened cases. Flagged cases land at the top for priority review."
    >
      {error && (
        <Alert variant="destructive">
          <Info />
          <AlertTitle>Could not load the review queue</AlertTitle>
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
        <StatCard label="Awaiting sign-off" value={awaiting.length} />
        <StatCard label="Flagged for review" value={flaggedCount} tone="warning" />
        <StatCard label="Scans analyzed" value={stats?.scans_analyzed ?? "—"} />
        <StatCard label="Patients registered" value={stats?.total_patients ?? "—"} />
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-1">
          {(
            [
              ["all", `All (${queue?.length ?? "…"})`],
              ["flagged", `Flagged (${flaggedCount})`],
              ["awaiting", `Awaiting (${awaiting.length})`],
            ] as [Filter, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFilter(key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-sm font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring",
                filter === key
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <Button variant="outline" size="sm" onClick={handleRefresh} disabled={busy}>
          {busy && <Spinner size="sm" />}
          Refresh
        </Button>
      </div>

      {flash && (
        <Alert className="mt-3 border-primary/30 bg-primary/5">
          <CheckCircle2 className="text-primary" />
          <AlertTitle>Sign-off recorded</AlertTitle>
          <AlertDescription>{flash}</AlertDescription>
        </Alert>
      )}

      <div className="mt-4 space-y-3">
        {queue === null ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Spinner size="sm" /> Scanning the queue&hellip;
          </div>
        ) : visible && visible.length > 0 ? (
          visible.map((item) => (
            <ReviewCase
              key={item.image_id}
              item={item}
              token={token ?? ""}
              onSigned={(imageId) => {
                setFlash(`Case ${imageId.slice(0, 8)} signed off; the patient summary is now live.`)
                handleRefresh()
              }}
            />
          ))
        ) : (
          <p className="text-sm text-muted-foreground">
            No cases match this view. New synced cases will appear here when
            they arrive &mdash; you&apos;ll get a notification in the top menu.
          </p>
        )}
      </div>
    </DashboardShell>
  )
}

export default function DoctorDashboardPage() {
  return (
    <RequireRole roles={["doctor", "ophthalmologist"]}>
      <ReviewPortal />
    </RequireRole>
  )
}