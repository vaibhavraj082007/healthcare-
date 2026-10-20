"use client"

import * as React from "react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { RequireRole } from "@/components/dashboard/route-guard"
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
import { findingBadgeTone, isReviewItem } from "@/lib/consistency"
import {
  type ReviewQueueItem,
  type RoleStats,
  type SyncStatus,
  dashboardApi,
  telemedApi,
} from "@/lib/api"
import { useSession } from "@/lib/session"
import { ScreeningReportPanel } from "@/components/reports/report-panel"
import { Info } from "lucide-react"

const gradeLabels = ["No DR", "Mild", "Moderate", "Severe", "Proliferative"]

function AdminOverview() {
  const { token } = useSession()
  const [stats, setStats] = React.useState<RoleStats | null>(null)
  const [queue, setQueue] = React.useState<ReviewQueueItem[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [retry, setRetry] = React.useState(0)
  const [sync, setSync] = React.useState<SyncStatus | null>(null)
  const [syncBusy, setSyncBusy] = React.useState(false)

  React.useEffect(() => {
    if (!token) return
    let active = true
    Promise.all([
      dashboardApi.stats(token),
      dashboardApi.reviewQueue(token),
      telemedApi.syncStatus(token),
    ])
      .then(([stats, queue, sync]) => {
        if (active) {
          setStats(stats)
          setQueue(queue)
          setSync(sync)
        }
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
  }, [token, retry])

  const flagged = queue?.filter((item) => isReviewItem(item.consistency_status))
  const gradeDist = stats?.grade_distribution ?? {}

  return (
    <DashboardShell
      title="Operations overview"
      description="Platform-wide screening volume, queue health, and flagged cases."
    >
      {error && (
        <Alert variant="destructive">
          <Info />
          <AlertTitle>Could not load overview</AlertTitle>
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

      {stats ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {[
            { label: "Patients", value: stats.total_patients },
            { label: "Total scans", value: stats.total_scans },
            { label: "Analyzed", value: stats.scans_analyzed },
            { label: "Pending", value: stats.scans_pending },
            { label: "Flagged", value: stats.flagged_for_review },
          ].map((stat) => (
            <Card key={stat.label} className="gap-1">
              <CardHeader>
                <CardDescription>{stat.label}</CardDescription>
                <CardTitle>{stat.value}</CardTitle>
              </CardHeader>
            </Card>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Loading overview&hellip;
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Grade distribution</CardTitle>
            <CardDescription>
              ICDR severity bands among completed scans (0 = no DR).
            </CardDescription>
          </CardHeader>
          <CardContent>
            {Object.keys(gradeDist).length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No completed analyses yet.
              </p>
            ) : (
              <div className="flex flex-col gap-2">
                {Object.entries(gradeDist)
                  .sort(([a], [b]) => Number(a) - Number(b))
                  .map(([grade, count]) => (
                    <div key={grade} className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
                      <span className="text-sm text-muted-foreground">
                        {gradeLabels[Number(grade)] ?? `Grade ${grade}`}
                      </span>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                        <div
                          className="h-full rounded-full bg-primary"
                          style={{
                            width: `${(count / (stats?.scans_analyzed || 1)) * 100}%`,
                          }}
                        />
                      </div>
                      <span className="text-right text-sm tabular-nums">{count}</span>
                    </div>
                  ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Flagged cases</CardTitle>
            <CardDescription>
              Scans where the two engines disagree.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {!flagged ? (
              <Spinner size="sm" />
            ) : flagged.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nothing flagged right now.
              </p>
            ) : (
              <ul className="flex flex-col gap-2">
                {flagged.map((item) => (
                  <li
                    key={item.image_id}
                    className="flex items-center justify-between gap-3 rounded-lg bg-muted/60 px-3 py-2 text-sm"
                  >
                    <span>
                      <strong>{item.patient_name}</strong>{" "}
                      <span className="text-muted-foreground">
                        grade {item.icdr_grade ?? "—"}
                      </span>
                    </span>
                    <Badge tone="destructive">
                      #{item.image_id.slice(0, 6)}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <h2 className="mt-2 font-heading text-lg font-semibold">Recent scans</h2>
      {queue && queue.length === 0 && (
        <p className="text-sm text-muted-foreground">No scans uploaded yet.</p>
      )}

      <h2 className="mt-6 font-heading text-lg font-semibold">
        Telemedicine sync (Phase 4)
      </h2>
      <Card className="mt-2">
        <CardHeader>
          <CardTitle>Store-and-forward queue</CardTitle>
          <CardDescription>
            Cases flow PHC &rarr; sync queue &rarr; telemedicine review. The
            prototype runs both sides on one backend, so transmission is an
            internal state transition. Low bandwidth &mdash; or the demo
            switch below &mdash; keeps cases queued with &ldquo;Waiting for
            connection&rdquo;.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {sync ? (
            <div className="flex flex-wrap items-center gap-3">
              {[
                { label: "Synced", value: sync.synced, tone: "success" as const },
                { label: "Pending", value: sync.pending, tone: "warning" as const },
                { label: "Syncing", value: sync.syncing, tone: "accent" as const },
                { label: "Failed", value: sync.failed, tone: "destructive" as const },
              ].map((s) => (
                <div key={s.label} className="flex items-center gap-2 rounded-lg bg-muted/60 px-3 py-2 text-sm">
                  <span className="text-muted-foreground">{s.label}</span>
                  <Badge tone={s.tone}>{s.value}</Badge>
                </div>
              ))}
              <div className="ml-auto flex items-center gap-2">
                <span className="text-sm font-medium">
                  Offline simulation:{" "}
                  <span className={sync.offline_sim ? "text-destructive" : "text-muted-foreground"}>
                    {sync.offline_sim ? "ON" : "OFF"}
                  </span>
                </span>
                <Button
                  variant={sync.offline_sim ? "destructive" : "outline"}
                  size="sm"
                  disabled={syncBusy}
                  onClick={async () => {
                    if (!token) return
                    setSyncBusy(true)
                    try {
                      setSync(await telemedApi.setOfflineSim(token, !sync.offline_sim))
                    } catch {
                      /* keep last known state */
                    } finally {
                      setSyncBusy(false)
                    }
                  }}
                >
                  {syncBusy ? <Spinner size="sm" /> : null}
                  {sync.offline_sim ? "Restore connection" : "Simulate offline"}
                </Button>
              </div>
              <p className="w-full text-xs text-muted-foreground">
                With the switch ON, the bandwidth probe fails and queued cases
                stay pending &mdash; the patient and doctor UIs keep working and
                auto-resume when the connection returns (or the switch is
                turned off).
              </p>
            </div>
          ) : (
            <Spinner size="sm" />
          )}
        </CardContent>
      </Card>

      <h2 className="mt-6 font-heading text-lg font-semibold">
        Clinical reports (Phase 3)
      </h2>
      <p className="mb-3 text-sm text-muted-foreground">
        Full explainable screening reports for recent scans — plain-language
        text, the Grad-CAM heatmap, and the underlying structured findings for
        review. Printable via the in-report button.
      </p>
      {queue === null ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Loading reports&hellip;
        </div>
      ) : queue.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No completed analyses yet.
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          {queue.map((item) => (
            <details
              key={item.image_id}
              className="rounded-lg border bg-card p-3"
            >
              <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm">
                <span>
                  <strong>{item.patient_name}</strong>{" "}
                  <span className="text-muted-foreground">
                    grade {item.icdr_grade ?? "—"} · #{item.image_id.slice(0, 6)}
                  </span>
                </span>
                <Badge tone={findingBadgeTone(item.consistency_status)}>
                  {item.consistency_status}
                </Badge>
              </summary>
              <div className="mt-3">
                <ScreeningReportPanel
                  imageId={item.image_id}
                  token={token ?? ""}
                  variant="clinical"
                />
              </div>
            </details>
          ))}
        </div>
      )}
    </DashboardShell>
  )
}

export default function AdminOverviewPage() {
  return (
    <RequireRole roles={["admin"]}>
      <AdminOverview />
    </RequireRole>
  )
}