"use client"

import * as React from "react"
import Link from "next/link"
import { useParams } from "next/navigation"
import {
  ArrowLeft,
  CheckCircle2,
  ClipboardList,
  Compass,
  MessageSquareText,
  Phone,
  Printer,
  Send,
  Stethoscope,
} from "lucide-react"

import { DashboardShell } from "@/components/dashboard/dashboard-shell"
import { RequireRole } from "@/components/dashboard/route-guard"
import { MedicalReportPrint } from "@/components/reports/medical-report"
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
import {
  type CaseDetail,
  type CaseNote,
  type CaseStatus,
  doctorApi,
} from "@/lib/api"
import { useSession } from "@/lib/session"
import { cn } from "cn"

const STATUS_ORDER: CaseStatus[] = ["New", "Claimed", "Contacted", "Reviewed"]

const BAND_TONE: Record<string, "destructive" | "warning" | "success"> = {
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

function formatStamp(value: string | null): string | null {
  if (!value) return null
  return new Date(value).toLocaleString()
}

function StatusTimeline({ detail }: { detail: CaseDetail }) {
  const reached = STATUS_ORDER.indexOf(detail.status)
  const stamps: Record<CaseStatus, string | null> = {
    New: detail.created_at,
    Claimed: detail.claimed_at,
    Contacted: detail.contacted_at,
    Reviewed: detail.reviewed_at,
  }
  return (
    <ol className="flex flex-wrap items-center gap-1.5">
      {STATUS_ORDER.map((stage, index) => {
        const active = index <= reached
        const isNow = index === reached
        return (
          <li
            key={stage}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium",
              isNow
                ? "border-primary/40 bg-primary/5 text-foreground"
                : active
                  ? "border-border bg-muted/40 text-muted-foreground"
                  : "border-border text-muted-foreground/50",
            )}
          >
            {active && <CheckCircle2 className="size-3 text-emerald-600" aria-hidden />}
            {stage}
            {isNow && formatStamp(stamps[stage]) && (
              <span className="text-[10px] text-muted-foreground">
                {formatStamp(stamps[stage])}
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

function ContactPanel({ phone }: { phone: string | null }) {
  const [revealed, setRevealed] = React.useState(false)
  const digits = (phone ?? "").replace(/\D/g, "")

  return (
    <Card className="gap-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Phone className="size-4 text-primary" aria-hidden />
          Contact
        </CardTitle>
        <CardDescription>
          Patient details for the follow-up call. Hidden until you need them.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!phone ? (
          <p className="text-sm text-muted-foreground">No phone number registered.</p>
        ) : revealed ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-sm">{phone}</span>
            {digits.length >= 10 && (
              <>
                <a
                  href={`https://wa.me/${digits}`}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white outline-none transition-opacity hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring"
                >
                  WhatsApp
                </a>
                <a
                  href={`tel:${digits}`}
                  className="rounded-md border px-3 py-1.5 text-xs font-medium text-foreground outline-none transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring"
                >
                  Call
                </a>
              </>
            )}
          </div>
        ) : (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setRevealed(true)}
          >
            Reveal contact
          </Button>
        )}
      </CardContent>
    </Card>
  )
}

function CaseActions({
  detail,
  onChanged,
}: {
  detail: CaseDetail
  onChanged: (next: CaseDetail) => void
}) {
  const { token } = useSession()
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  if (detail.status === "Reviewed") {
    return <p className="text-sm text-muted-foreground">This case is closed.</p>
  }

  async function run(action: () => Promise<CaseDetail>) {
    if (!token) return
    setBusy(true)
    setError(null)
    try {
      const next = await action()
      onChanged(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed")
    } finally {
      setBusy(false)
    }
  }

  const next: { status: CaseStatus; label: string } =
    detail.status === "New"
      ? { status: "Claimed", label: "Claim this case" }
      : detail.status === "Claimed"
        ? { status: "Contacted", label: "Mark as contacted" }
        : { status: "Reviewed", label: "Mark as reviewed" }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          disabled={busy}
          onClick={() =>
            run(() => doctorApi.setStatus(token!, detail.image_id, next.status))
          }
        >
          {busy && <Spinner size="sm" />}
          {detail.status === "New" ? <Stethoscope className="size-4" /> : <CheckCircle2 className="size-4" />}
          {next.label}
        </Button>
        {detail.status === "New" && detail.has_report && (
          <Link href="/dashboard/doctor" className="text-sm text-muted-foreground underline-offset-4 hover:underline">
            Clinical sign-off lives in the review portal →
          </Link>
        )}
      </div>
      {detail.assigned_doctor_name && (
        <p className="text-xs text-muted-foreground">
          Assigned to <span className="text-foreground">{detail.assigned_doctor_name}</span>
        </p>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  )
}

function NotesThread({
  detail,
  onNoteAdded,
}: {
  detail: CaseDetail
  onNoteAdded: (note: CaseNote) => void
}) {
  const { token } = useSession()
  const [draft, setDraft] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const body = draft.trim()
    if (!body || !token) return
    setBusy(true)
    setError(null)
    try {
      const note = await doctorApi.addNote(token, detail.image_id, body)
      onNoteAdded(note)
      setDraft("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post the note")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <MessageSquareText className="size-4 text-primary" aria-hidden />
          Case notes
        </CardTitle>
        <CardDescription>
          Shared thread for the doctor and the ASHA worker who registered the case.
          Notes are never edited or deleted.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {detail.notes.length === 0 ? (
          <p className="text-sm text-muted-foreground">No notes yet.</p>
        ) : (
          <ol className="space-y-3">
            {detail.notes.map((note) => (
              <li key={note.id} className="rounded-lg border bg-muted/30 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-sm font-semibold">{note.author_name}</span>
                  <span className="text-xs text-muted-foreground">
                    {formatStamp(note.created_at)}
                  </span>
                </div>
                <p className="mt-1 whitespace-pre-wrap text-sm text-foreground">
                  {note.body}
                </p>
              </li>
            ))}
          </ol>
        )}

        <form onSubmit={submit} className="flex flex-col gap-2">
          <textarea
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Add a note for the ASHA worker or the treating doctor…"
            className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" size="sm" disabled={busy || !draft.trim()} className="self-start">
            {busy ? <Spinner size="sm" /> : <Send className="size-4" />}
            Add note
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function CaseDetailView() {
  const params = useParams<{ image_id: string }>()
  const imageId = params?.image_id ?? ""
  const { token } = useSession()
  const [detail, setDetail] = React.useState<CaseDetail | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [retry, setRetry] = React.useState(0)

  React.useEffect(() => {
    if (!token || !imageId) return
    let active = true
    doctorApi
      .detail(token, imageId)
      .then((d) => {
        if (active) {
          setDetail(d)
          setError(null)
        }
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
  }, [token, imageId, retry])

  if (error && !detail) {
    return (
      <DashboardShell title="Case not found" description="">
        <Alert variant="destructive">
          <ClipboardList />
          <AlertTitle>Could not load the case</AlertTitle>
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
      </DashboardShell>
    )
  }

  return (
    <DashboardShell title="Case detail" description="">
      <Link
        href="/doctor/dashboard"
        className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft className="size-4" aria-hidden />
        Back to case queue
      </Link>

      {detail ? (
        <div className="flex flex-col gap-4">
          {/* Workflow toolbar — kept out of the printed report. */}
          <div className="no-print flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1.5">
              <Badge tone={BAND_TONE[detail.severity_band]}>{detail.severity_band}</Badge>
              <Badge tone={STATUS_TONE[detail.status]}>{detail.status}</Badge>
              {detail.flagged && <Badge tone="destructive">Flagged for review</Badge>}
            </div>
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer className="size-4" aria-hidden />
              Print / PDF report
            </Button>
          </div>

          {/* The professional medical report: primary content of the page. */}
          <div className="relative-block">
            <MedicalReportPrint
              imageId={detail.image_id}
              token={token ?? ""}
              signOff={detail.sign_off}
            />
          </div>

          {/* Review workflow controls — subsidiary, collapsible, no-print. */}
          <details
            className="no-print mt-2 rounded-lg border bg-muted/30 p-3"
            open={detail.status !== "Reviewed"}
          >
            <summary className="cursor-pointer text-sm font-medium">
              Review workflow &amp; collaboration
            </summary>
            <div className="mt-3 grid gap-4 lg:grid-cols-3">
              <ContactPanel phone={detail.phone} />
              <Card className="gap-0">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Compass className="size-4 text-primary" aria-hidden />
                    Progress
                  </CardTitle>
                  <CardDescription>
                    {detail.worker_name
                      ? `Registered by ASHA worker ${detail.worker_name}`
                      : "Registration worker unknown"}
                  </CardDescription>
                </CardHeader>
                <CardContent className="flex flex-col gap-3">
                  <StatusTimeline detail={detail} />
                  <CaseActions detail={detail} onChanged={(next) => setDetail(next)} />
                </CardContent>
              </Card>
              <div className="lg:col-span-1">
                <SignOffSummary detail={detail} />
              </div>
            </div>
            <div className="mt-4">
              <NotesThread
                detail={detail}
                onNoteAdded={(note) =>
                  setDetail((prev) => (prev ? { ...prev, notes: [...prev.notes, note] } : prev))
                }
              />
            </div>
          </details>
        </div>
      ) : (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Loading the case…
        </div>
      )}
    </DashboardShell>
  )
}

function SignOffSummary({ detail }: { detail: CaseDetail }) {
  const signOff = detail.sign_off
  if (!signOff) return null
  return (
    <Card className="gap-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <CheckCircle2 className="size-4 text-primary" aria-hidden />
          Clinical sign-off
        </CardTitle>
        <CardDescription>{signOff.decision}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 text-sm text-muted-foreground">
        {signOff.signed_at && (
          <p>
            Signed on {new Date(signOff.signed_at).toLocaleDateString()} by ophthalmologist #
            {signOff.ophthalmologist_id}
          </p>
        )}
        {signOff.revised_grade != null && (
          <p>Revised ICDR grade: {signOff.revised_grade}</p>
        )}
        {signOff.doctor_notes && (
          <p className="mt-1 whitespace-pre-wrap text-foreground">{signOff.doctor_notes}</p>
        )}
      </CardContent>
    </Card>
  )
}

export function CaseDetailClient() {
  return (
    <RequireRole roles={["doctor", "ophthalmologist"]}>
      <CaseDetailView />
    </RequireRole>
  )
}