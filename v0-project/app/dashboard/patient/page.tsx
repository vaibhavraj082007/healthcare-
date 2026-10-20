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
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { Badge } from "@/components/ui/badge"
import {
  type FindingOut,
  type PatientOut,
  type PatientStatus,
  type PatientSummary,
  type UploadOut,
  fetchSummaryAudioUrl,
  patientsApi,
  telemedApi,
} from "@/lib/api"
import { useSession } from "@/lib/session"
import { findingBadgeTone } from "@/lib/consistency"
import { ScreeningReportPanel } from "@/components/reports/report-panel"
import { ScanImageViewer } from "@/components/reports/image-viewer"
import {
  CheckCircle2,
  Hourglass,
  Info,
  Loader2,
  ScanLine,
  Volume2,
} from "lucide-react"
import { cn } from "cn"

const gradeLabels = ["No DR", "Mild", "Moderate", "Severe", "Proliferative"]

/* Phase 4 — plain-language patient stage machine (no fake ETA, §6). */
const STAGE_META: Record<
  PatientStatus["state"],
  { icon: React.ComponentType<React.SVGProps<SVGSVGElement>>; spin?: boolean }
> = {
  scan_received: { icon: ScanLine },
  analysis_in_progress: { icon: Loader2, spin: true },
  awaiting_review: { icon: Hourglass },
  reviewed: { icon: CheckCircle2 },
}

function SummariesSection({
  imageId,
  token,
}: {
  imageId: string
  token: string
}) {
  const [summaries, setSummaries] = React.useState<PatientSummary[] | null>(null)
  const [lang, setLang] = React.useState("en")
  const [audioUrls, setAudioUrls] = React.useState<Record<string, string>>({})
  const [playing, setPlaying] = React.useState(false)
  const [browserSpeaking, setBrowserSpeaking] = React.useState(false)
  const audioRef = React.useRef<HTMLAudioElement | null>(null)
  const synthRef = React.useRef<SpeechSynthesisUtterance | null>(null)

  React.useEffect(() => {
    let active = true
    telemedApi
      .summaries(token, imageId)
      .then((rows) => {
        if (!active) return
        setSummaries(rows)
        if (rows[0]) setLang(rows[0].language)
      })
      .catch(() => {
        if (active) setSummaries([])
      })
    return () => {
      active = false
    }
  }, [token, imageId])

  React.useEffect(
    () => () => {
      audioRef.current?.pause()
      window.speechSynthesis?.cancel()
    },
    [],
  )

  function switchLang(next: string) {
    if (next === lang) return
    audioRef.current?.pause()
    window.speechSynthesis?.cancel()
    setPlaying(false)
    setBrowserSpeaking(false)
    setLang(next)
  }

  function play(url: string) {
    audioRef.current?.pause()
    window.speechSynthesis?.cancel()
    const audio = new Audio(url)
    audioRef.current = audio
    audio.onended = () => setPlaying(false)
    audio.onerror = () => setPlaying(false)
    setPlaying(true)
    setBrowserSpeaking(false)
    void audio.play().catch(() => setPlaying(false))
  }

  function speakBrowser(text: string, language: string) {
    window.speechSynthesis?.cancel()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = language === "hi" ? "hi-IN" : "en-US"
    utterance.rate = 0.9
    utterance.onend = () => setBrowserSpeaking(false)
    utterance.onerror = () => setBrowserSpeaking(false)
    synthRef.current = utterance
    setBrowserSpeaking(true)
    setPlaying(true)
    window.speechSynthesis?.speak(utterance)
  }

  async function toggleVoice() {
    if (playing) {
      audioRef.current?.pause()
      window.speechSynthesis?.cancel()
      setPlaying(false)
      setBrowserSpeaking(false)
      return
    }
    const cached = audioUrls[lang]
    if (cached) {
      play(cached)
      return
    }
    const url = await fetchSummaryAudioUrl(
      imageId,
      lang,
      token,
      active.content_version,
    )
    setAudioUrls((m) => ({ ...m, [lang]: url }))
    play(url)
  }

  if (!summaries || summaries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        Your plain-language result is not ready yet — check back shortly.
      </p>
    )
  }

  const active = summaries.find((s) => s.language === lang) ?? summaries[0]

  return (
    <div className="rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Doctor&apos;s summary — your result
        </p>
        <div className="flex items-center gap-1">
          {summaries.map((s) => (
            <button
              key={s.language}
              type="button"
              onClick={() => switchLang(s.language)}
              className={cn(
                "rounded-md px-2.5 py-1 text-xs font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                s.language === active.language
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {s.language === "hi" ? "हिन्दी" : "English"}
            </button>
          ))}
          {active.has_audio ? (
            <Button
              variant="outline"
              size="sm"
              onClick={toggleVoice}
              aria-pressed={playing}
            >
              <Volume2 className="size-4" />
              {playing ? "Stop" : "Listen"}
            </Button>
          ) : typeof window !== "undefined" && "speechSynthesis" in window ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                if (browserSpeaking) {
                  window.speechSynthesis?.cancel()
                  setBrowserSpeaking(false)
                  setPlaying(false)
                } else {
                  speakBrowser(active.summary_text, active.language)
                }
              }}
              aria-pressed={browserSpeaking}
            >
              <Volume2 className="size-4" />
              {browserSpeaking ? "Stop" : "Listen (browser)"}
            </Button>
          ) : null}
        </div>
      </div>
      {!active.has_audio && typeof window !== "undefined" && !("speechSynthesis" in window) && (
        <p className="text-xs text-muted-foreground">
          A voice version isn&apos;t available for this language yet.
        </p>
      )}
      <p className="mt-3 text-sm leading-relaxed">{active.summary_text}</p>
    </div>
  )
}

interface ProvenanceShape {
  classifier?: { model?: string; trained_on?: string; validation_qwk?: number | null }
  detector?: string
}

function ModelProvenanceNote({ raw }: { raw: string }) {
  let data: ProvenanceShape = {}
  try {
    data = JSON.parse(raw) as ProvenanceShape
  } catch {
    data = {}
  }
  const clf = data.classifier
  return (
    <div className="mt-3 rounded-lg border bg-muted/40 p-3 text-xs text-muted-foreground">
      <p className="font-medium uppercase tracking-wide">Model &amp; limits</p>
      <ul className="mt-1.5 list-disc space-y-1 pl-4">
        <li>
          Severity model: {clf?.model ?? "EfficientNet-B0"}
          {clf?.trained_on ? ` · trained on ${clf.trained_on}` : ""}
          {clf?.validation_qwk != null ? ` · validation QWK ${clf.validation_qwk}` : ""}
        </li>
        <li>
          {typeof data.detector === "string" && data.detector.length > 0
            ? data.detector
            : "Lesion detection was not available for this scan"}
        </li>
        <li>
          This is an AI screening aid for retinal fundus photographs only.
          Results are not a clinical diagnosis — please follow up with an
          eye-care professional.
        </li>
      </ul>
      <p className="mt-3 border-t pt-2 font-medium">
        NetraScan is a decision-support prototype, not a certified diagnostic
        device. Results must be reviewed by a qualified ophthalmologist before
        any clinical decision.
      </p>
    </div>
  )
}

function FindingPanel({ finding, token }: { finding: FindingOut; token: string }) {
  const [status, setStatus] = React.useState<PatientStatus | null>(null)

  // Phase 4 — patient status is server-derived; poll until reviewed so the
  // page updates without a manual refresh when the doctor signs off.
  React.useEffect(() => {
    if (!token) return
    let stopped = false
    async function poll() {
      try {
        const next = await telemedApi.scanStatus(token, finding.image_id)
        if (!stopped) setStatus(next)
      } catch {
        // scan not ready yet — keep polling
      }
    }
    poll()
    const id = window.setInterval(poll, 25000)
    return () => {
      stopped = true
      window.clearInterval(id)
    }
  }, [token, finding.image_id])

  const stage = status ? STAGE_META[status.state] : null

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <CardTitle className="text-base">Scan&nbsp;#{finding.image_id.slice(0, 6)}</CardTitle>
            <CardDescription>
              Analyzed {finding.analyzed_at ? new Date(finding.analyzed_at).toLocaleString() : "—"}
            </CardDescription>
          </div>
          {status ? (
            <Badge
              tone={
                status.state === "reviewed"
                  ? "success"
                  : status.state === "awaiting_review"
                    ? "warning"
                    : "accent"
              }
            >
              {status.stage_label}
            </Badge>
          ) : (
            <Badge tone="accent">
              {finding.analysis_status === "completed" ? "Processing" : finding.analysis_status}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {finding.analysis_status === "failed" && (
          <Alert variant="destructive">
            <Info />
            <AlertTitle>Analysis did not complete</AlertTitle>
            <AlertDescription>
              The screening result is unavailable. Please contact your health
              centre for a new scan.
            </AlertDescription>
          </Alert>
        )}

        {status && (
          <div className="mb-4 flex items-start gap-3 rounded-lg border p-4">
            {stage &&
              React.createElement(stage.icon, {
                className: cn(
                  "mt-0.5 size-5 shrink-0 text-primary",
                  stage.spin && "animate-spin",
                ),
                "aria-hidden": true,
              })}
            <div className="flex flex-col gap-0.5">
              <p className="font-heading text-base font-bold">{status.stage_label}</p>
              <p className="text-sm text-muted-foreground">{status.patient_text}</p>
              {status.state === "reviewed" && status.revised_grade != null && status.signed_decision === "Revised" && (
                <p className="mt-1 rounded-md bg-muted/60 px-2 py-1 text-sm">
                  The doctor revised the severity to{" "}
                  <strong>{gradeLabels[status.revised_grade] ?? status.revised_grade}</strong>{" "}
                  (grade {status.revised_grade}).
                </p>
              )}
            </div>
          </div>
        )}

        {finding.analysis_status === "completed" && finding.icdr_grade !== null && status?.state !== "reviewed" && (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg bg-muted/60 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                DR severity
              </p>
              <p className="mt-1 font-heading text-lg font-bold">
                {gradeLabels[finding.icdr_grade] ?? finding.icdr_grade}
                <span className="ml-1.5 text-sm font-normal text-muted-foreground">
                  grade {finding.icdr_grade}
                </span>
              </p>
            </div>
            <div className="rounded-lg bg-muted/60 p-3">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Consistency
              </p>
              <Badge tone={findingBadgeTone(finding.consistency_status)}>
                {finding.consistency_status}
              </Badge>
            </div>
          </div>
        )}

        {finding.analysis_status === "completed" && finding.model_provenance && (
          <ModelProvenanceNote raw={finding.model_provenance} />
        )}

        {finding.analysis_status === "completed" && status?.state === "reviewed" && (
          <div className="space-y-4">
            <SummariesSection imageId={finding.image_id} token={token} />
            <div>
              <h3 className="mb-2 font-heading text-sm font-semibold">
                Your explainable screening report
              </h3>
              <ScreeningReportPanel imageId={finding.image_id} token={token} variant="patient" />
            </div>
          </div>
        )}

        {finding.analysis_status === "queued" && (
          <p className="text-sm text-muted-foreground">
            This scan is queued and will move to &ldquo;Scan received&rdquo;
            shortly.
          </p>
        )}

        <ScanImageViewer imageId={finding.image_id} token={token} className="mt-4" />
      </CardContent>
    </Card>
  )
}

function PatientDashboard() {
  const { token } = useSession()
  const [record, setRecord] = React.useState<PatientOut | null>(null)
  const [scans, setScans] = React.useState<UploadOut[] | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [retry, setRetry] = React.useState(0)

  React.useEffect(() => {
    if (!token) return
    let active = true
    patientsApi
      .self(token)
      .then((self) => {
        if (!active) return
        setRecord(self)
        return patientsApi.scans(token, self.id)
      })
      .then((list) => {
        if (active) setScans(list ?? [])
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
  }, [token, retry])

  return (
    <DashboardShell
      title="My screenings"
      description="Your NetraScan screening history and AI findings."
    >
      {error && (
        <Alert variant="destructive">
          <Info />
          <AlertTitle>Could not load your records</AlertTitle>
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

      {!record && !error && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Loading your profile&hellip;
        </div>
      )}

      {record && (
        <Card>
          <CardHeader>
            <CardTitle>{record.full_name}</CardTitle>
            <CardDescription>
              {[record.gender, record.age ? `${record.age} yrs` : null]
                .filter(Boolean)
                .join(" · ") || "Demographics not recorded"}
            </CardDescription>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            {record.village || record.district
              ? `${[record.village, record.district].filter(Boolean).join(", ")}`
              : "Location not recorded"}
          </CardContent>
        </Card>
      )}

      <h2 className="mt-2 font-heading text-lg font-semibold">
        Screening results
      </h2>
      {scans === null ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner size="sm" /> Loading scans&hellip;
        </div>
      ) : scans.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          You don&apos;t have any screenings yet. A health worker will create
          one during your next community camp.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {scans.map((scan) => {
            const finding = scan.findings?.[0]
            return finding ? (
              <FindingPanel key={scan.image_id} finding={finding} token={token ?? ""} />
            ) : (
              <Card key={scan.image_id}>
                <CardHeader>
                  <CardTitle className="text-base">Scan</CardTitle>
                  <CardDescription>
                    {new Date(scan.uploaded_at).toLocaleString()}
                  </CardDescription>
                </CardHeader>
                <CardContent className="text-sm text-muted-foreground">
                  This scan has no analysis result yet.
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
    </DashboardShell>
  )
}

export default function PatientDashboardPage() {
  return (
    <RequireRole roles={["patient"]}>
      <PatientDashboard />
    </RequireRole>
  )
}