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
import { ScanImageViewer } from "@/components/reports/image-viewer"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FieldContent, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Spinner } from "@/components/ui/spinner"
import {
  type CaseNote,
  type FindingOut,
  type PatientCaseInfo,
  type PatientOut,
  type UploadOut,
  doctorApi,
  patientsApi,
  uploadsApi,
} from "@/lib/api"
import { useSession } from "@/lib/session"
import { cn } from "cn"
import { Info, MessageSquareText, ScanLine, Send, UploadCloud } from "lucide-react"
import { findingBadgeTone } from "@/lib/consistency"

const gradeLabels = ["No DR", "Mild", "Moderate", "Severe", "Proliferative"]

interface ProvenanceShape {
  classifier?: { model?: string; trained_on?: string; validation_qwk?: number | null }
  detector?: string
}

function ModelProvenanceNote({ finding }: { finding: FindingOut }) {
  let data: ProvenanceShape = {}
  if (finding.model_provenance) {
    try {
      data = JSON.parse(finding.model_provenance) as ProvenanceShape
    } catch {
      data = {}
    }
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
          AI screening aid for retinal fundus photographs only — not a clinical
          diagnosis.
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

function NewPatientForm({
  onCreated,
}: {
  onCreated: (patient: PatientOut) => void
}) {
  const { token } = useSession()
  const [values, setValues] = React.useState({
    full_name: "",
    age: "",
    gender: "",
    village: "",
    district: "",
    phone: "",
    email: "",
    password: "",
  })
  const [fieldError, setFieldError] = React.useState<string | null>(null)
  const [serverError, setServerError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const [createdLogin, setCreatedLogin] = React.useState<{
    name: string
    email: string
    password: string
  } | null>(null)

  function set(key: keyof typeof values, value: string) {
    setValues((prev) => ({ ...prev, [key]: value }))
    if (fieldError) setFieldError(null)
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!values.full_name.trim()) {
      setFieldError("Full name is required.")
      return
    }
    const email = values.email.trim()
    const password = values.password
    if (email && !password) {
      setFieldError("Enter a password for the patient account, or leave the email blank.")
      return
    }
    if (password && !email) {
      setFieldError("Enter an email for the patient account, or leave the password blank.")
      return
    }
    if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setFieldError("Enter a valid email address.")
      return
    }
    if (password && password.length < 8) {
      setFieldError("Password must be at least 8 characters.")
      return
    }
    if (!token) return
    setBusy(true)
    setServerError(null)
    try {
      const patient = await patientsApi.create(token, {
        full_name: values.full_name.trim(),
        age: values.age ? Number(values.age) : null,
        gender: values.gender || null,
        village: values.village || null,
        district: values.district || null,
        phone: values.phone || null,
        email: email || null,
        password: password || null,
      })
      onCreated(patient)
      setCreatedLogin(email ? { name: patient.full_name, email, password } : null)
      setValues({
        full_name: "",
        age: "",
        gender: "",
        village: "",
        district: "",
        phone: "",
        email: "",
        password: "",
      })
    } catch (err) {
      setServerError(err instanceof Error ? err.message : "Could not create patient.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="grid gap-3">
      <FieldGroup>
        <Field>
          <FieldLabel htmlFor="new-name">Full name *</FieldLabel>
          <FieldContent>
            <Input
              id="new-name"
              placeholder="Patient name"
              value={values.full_name}
              onChange={(e) => set("full_name", e.target.value)}
            />
            <FieldError>{fieldError}</FieldError>
          </FieldContent>
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field>
            <FieldLabel htmlFor="new-age">Age</FieldLabel>
            <FieldContent>
              <Input
                id="new-age"
                type="number"
                min={0}
                placeholder="Years"
                value={values.age}
                onChange={(e) => set("age", e.target.value)}
              />
            </FieldContent>
          </Field>
          <Field>
            <FieldLabel htmlFor="new-gender">Gender</FieldLabel>
            <FieldContent>
              <Input
                id="new-gender"
                placeholder="Female / Male / Other"
                value={values.gender}
                onChange={(e) => set("gender", e.target.value)}
              />
            </FieldContent>
          </Field>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field>
            <FieldLabel htmlFor="new-village">Village</FieldLabel>
            <FieldContent>
              <Input
                id="new-village"
                value={values.village}
                onChange={(e) => set("village", e.target.value)}
              />
            </FieldContent>
          </Field>
          <Field>
            <FieldLabel htmlFor="new-district">District</FieldLabel>
            <FieldContent>
              <Input
                id="new-district"
                value={values.district}
                onChange={(e) => set("district", e.target.value)}
              />
            </FieldContent>
          </Field>
        </div>
        <Field>
          <FieldLabel htmlFor="new-phone">Phone</FieldLabel>
          <FieldContent>
            <Input
              id="new-phone"
              placeholder="+91 …"
              value={values.phone}
              onChange={(e) => set("phone", e.target.value)}
            />
          </FieldContent>
        </Field>
        <div className="rounded-lg border bg-muted/40 p-3">
          <p className="text-sm font-medium">Patient login (optional)</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Set an email and password so this patient can sign in to their own
            dashboard. Leave blank if they won&apos;t use it online.
          </p>
          <div className="mt-3 grid gap-3">
            <Field>
              <FieldLabel htmlFor="new-email">Email</FieldLabel>
              <FieldContent>
                <Input
                  id="new-email"
                  type="email"
                  autoComplete="off"
                  placeholder="patient@example.org"
                  value={values.email}
                  onChange={(e) => set("email", e.target.value)}
                />
              </FieldContent>
            </Field>
            <Field>
              <FieldLabel htmlFor="new-password">Password</FieldLabel>
              <FieldContent>
                <Input
                  id="new-password"
                  type="text"
                  autoComplete="off"
                  placeholder="At least 8 characters"
                  value={values.password}
                  onChange={(e) => set("password", e.target.value)}
                />
              </FieldContent>
            </Field>
          </div>
        </div>
      </FieldGroup>

      {serverError && (
        <Alert variant="destructive">
          <Info />
          <AlertTitle>Could not add patient</AlertTitle>
          <AlertDescription>{serverError}</AlertDescription>
        </Alert>
      )}

      {createdLogin && (
        <Alert>
          <Info />
          <AlertTitle>Patient account created</AlertTitle>
          <AlertDescription>
            <p className="mt-1">
              Give these to <strong>{createdLogin.name}</strong> so they can sign
              in on the <strong>Patient</strong> tab:
            </p>
            <p className="mt-2 font-mono text-xs">
              Email: {createdLogin.email}
              <br />
              Password: {createdLogin.password}
            </p>
            <p className="mt-2 text-xs text-muted-foreground">
              The password is shown only once — note it down before leaving this
              page.
            </p>
          </AlertDescription>
        </Alert>
      )}

      <Button type="submit" disabled={busy} className="justify-self-start">
        {busy && <Spinner size="sm" />}
        Add patient
      </Button>
    </form>
  )
}

function PatientLoginPanel({
  patient,
  onLoginAdded,
}: {
  patient: PatientOut
  onLoginAdded: (patient: PatientOut) => void
}) {
  const { token } = useSession()
  const [open, setOpen] = React.useState(false)
  const [email, setEmail] = React.useState("")
  const [password, setPassword] = React.useState("")
  const [error, setError] = React.useState<string | null>(null)
  const [created, setCreated] = React.useState<{ email: string; password: string } | null>(null)
  const [busy, setBusy] = React.useState(false)

  if (patient.has_login) return null

  async function save(e: React.FormEvent) {
    e.preventDefault()
    const em = email.trim()
    if (!em) return setError("Email is required.")
    if (!password) return setError("Password is required.")
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)) return setError("Enter a valid email address.")
    if (password.length < 8) return setError("Password must be at least 8 characters.")
    if (!token) return
    setBusy(true)
    setError(null)
    setCreated(null)
    try {
      const updated = await patientsApi.addLogin(token, patient.id, em, password)
      onLoginAdded(updated)
      setCreated({ email: em, password })
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create login.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border bg-muted/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium">Patient login</p>
        {!open && (
          <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
            Enable login
          </Button>
        )}
      </div>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {open
          ? "Set an email and password so this patient can sign in to their own dashboard."
          : "No login set — this patient can&apos;t sign in yet."}
      </p>

      {open && !created && (
        <form onSubmit={save} className="mt-3 grid gap-3">
          <Field>
            <FieldLabel htmlFor="existing-email">Email</FieldLabel>
            <FieldContent>
              <Input
                id="existing-email"
                type="email"
                autoComplete="off"
                placeholder="patient@example.org"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </FieldContent>
          </Field>
          <Field>
            <FieldLabel htmlFor="existing-password">Password</FieldLabel>
            <FieldContent>
              <Input
                id="existing-password"
                type="text"
                autoComplete="off"
                placeholder="At least 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </FieldContent>
          </Field>
          {error && (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          )}
          <div className="flex items-center gap-2">
            <Button type="submit" size="sm" disabled={busy}>
              {busy && <Spinner size="sm" />}
              Save login
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setOpen(false)
                setError(null)
              }}
            >
              Cancel
            </Button>
          </div>
        </form>
      )}

      {created && (
        <div className="mt-3 rounded-md border bg-background p-3">
          <p className="text-sm font-medium">Login created — share these</p>
          <p className="mt-2 font-mono text-xs">
            Email: {created.email}
            <br />
            Password: {created.password}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            Shown once — note it down.{` `}
            They sign in under the <strong>Patient</strong> tab at
            &nbsp;netrascan/login.
          </p>
        </div>
      )}
    </div>
  )
}

function PatientCasePanel({ patient }: { patient: PatientOut }) {
  const { token } = useSession()
  const [info, setInfo] = React.useState<PatientCaseInfo | null>(null)
  const [notes, setNotes] = React.useState<CaseNote[] | null>(null)
  const [draft, setDraft] = React.useState("")
  const [busy, setBusy] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!token) return
    let active = true
    patientsApi
      .caseInfo(token, patient.id)
      .then((c) => {
        if (active) setInfo(c)
      })
      .catch(() => {
        // non-fatal: the panel shows "no tracking yet"
      })
    return () => {
      active = false
    }
  }, [token, patient.id])

  const imageId = info?.has_case ? info.image_id : null
  React.useEffect(() => {
    if (!token || !imageId) return
    let active = true
    doctorApi
      .notes(token, imageId)
      .then((n) => {
        if (active) setNotes(n)
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
  }, [token, imageId])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    const body = draft.trim()
    if (!body || !token || !imageId) return
    setBusy(true)
    setError(null)
    try {
      const note = await doctorApi.addNote(token, imageId, body)
      setNotes((prev) => [...(prev ?? []), note])
      setDraft("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not post the note.")
    } finally {
      setBusy(false)
    }
  }

  const statusTone =
    info?.status === "Reviewed"
      ? "success"
      : info?.status === "Contacted"
        ? "outline"
        : info?.status === "Claimed"
          ? "warning"
          : "accent"
  const bandTone =
    info?.severity_band === "High"
      ? "destructive"
      : info?.severity_band === "Medium"
        ? "warning"
        : "success"

  return (
    <div className="rounded-lg border bg-muted/40 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-sm font-medium">
          <MessageSquareText className="size-4 text-muted-foreground" aria-hidden />
          Case status
        </p>
        {info?.has_case ? (
          <div className="flex items-center gap-1.5">
            {info.flagged && <Badge tone="destructive">Flagged</Badge>}
            <Badge tone={bandTone as "destructive" | "warning" | "success"}>
              {info.severity_band ?? "—"}
            </Badge>
            <Badge tone={statusTone as "accent" | "warning" | "outline" | "success"}>
              {info.status}
            </Badge>
          </div>
        ) : (
          <span className="text-xs text-muted-foreground">No tracking yet</span>
        )}
      </div>

      {info?.updated_at && (
        <p className="mt-1 text-xs text-muted-foreground">
          Updated {new Date(info.updated_at).toLocaleString()}
        </p>
      )}

      {imageId && notes !== null && (
        <>
          <div className="mt-3 space-y-2">
            {notes.length === 0 ? (
              <p className="text-xs text-muted-foreground">No notes from the doctor yet.</p>
            ) : (
              <ol className="space-y-2">
                {notes.map((note) => (
                  <li key={note.id} className="rounded-md border bg-background p-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-semibold">{note.author_name}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {new Date(note.created_at).toLocaleString()}
                      </span>
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-xs text-foreground">
                      {note.body}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <form onSubmit={submit} className="mt-3 flex flex-col gap-2">
            <textarea
              rows={2}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Note for the treating doctor…"
              className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            {error && <p className="text-xs text-destructive">{error}</p>}
            <div className="flex items-center gap-2">
              <Button type="submit" size="sm" disabled={busy || !draft.trim()}>
                {busy && <Spinner size="sm" />}
                <Send className="size-4" />
                Add note
              </Button>
            </div>
          </form>
        </>
      )}
    </div>
  )
}

function ScanWorkflow({ patient }: { patient: PatientOut }) {
  const { token } = useSession()
  const [file, setFile] = React.useState<File | null>(null)
  const [upload, setUpload] = React.useState<UploadOut | null>(null)
  const [finding, setFinding] = React.useState<FindingOut | null>(null)
  const [eyeLaterality, setEyeLaterality] = React.useState<string>("unknown")
  const [busy, setBusy] = React.useState<"idle" | "uploading" | "analyzing">("idle")
  const [error, setError] = React.useState<string | null>(null)

  const inputRef = React.useRef<HTMLInputElement>(null)

  function pickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const next = e.target.files?.[0] ?? null
    setFile(next)
    setUpload(null)
    setFinding(null)
  }

  async function handleUpload() {
    if (!file || !token) return
    setBusy("uploading")
    try {
      const created = await uploadsApi.create(token, patient.id, file, eyeLaterality)
      setUpload(created)
      const result = await uploadsApi.analyze(token, created.image_id)
      setFinding(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.")
    } finally {
      setBusy("idle")
    }
  }

  const qualityPending = upload?.quality_status === "pending"
  const qualityOk = upload?.quality_status === "acceptable"

  return (
    <div className="flex flex-col gap-3">
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="hidden"
        onChange={pickFile}
      />

      {!upload && (
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">
              Eye being scanned:
            </span>
            {(
              [
                ["od", "Right (OD)"],
                ["os", "Left (OS)"],
                ["ou", "Both (OU)"],
                ["unknown", "Unknown"],
              ] as const
            ).map(([code, label]) => (
              <button
                key={code}
                type="button"
                onClick={() => setEyeLaterality(code)}
                className={cn(
                  "rounded-full border px-3 py-1 text-xs transition-colors",
                  eyeLaterality === code
                    ? "border-blue-600 bg-blue-600 text-white"
                    : "border-input bg-background text-muted-foreground hover:bg-muted",
                )}
              >
                {label}
              </button>
            ))}
          </div>
          <Button
            variant="outline"
            size="lg"
            onClick={() => inputRef.current?.click()}
            className="justify-start"
          >
            <UploadCloud />
            {file ? file.name : "Choose a retina scan image"}
          </Button>
        </div>
      )}

      {file && !upload && (
        <div className="flex items-center gap-2">
          <Button type="button" onClick={handleUpload} disabled={busy === "uploading"}>
            {busy === "uploading" && <Spinner size="sm" />}
            Upload &amp; analyze
          </Button>
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              setFile(null)
              if (inputRef.current) inputRef.current.value = ""
            }}
          >
            Discard
          </Button>
        </div>
      )}

      {upload && (
        <>
          <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/60 p-3 text-sm">
            <ScanLine className="size-4 text-muted-foreground" />
            <span>
              <strong>{upload.filename}</strong> uploaded at{" "}
              {new Date(upload.uploaded_at).toLocaleTimeString()}
            </span>
            <Badge
              tone={
                qualityOk
                  ? "success"
                  : qualityPending
                    ? "accent"
                    : "warning"
              }
            >
              {qualityPending
                ? "Quality pending"
                : qualityOk
                  ? "Clear capture"
                  : (upload.retake_count ?? 0) >= 3
                    ? "Retake #" + (upload.retake_count ?? 0) + " — check the lens/camera setup"
                    : "Poor quality — retake advised"}
            </Badge>
            {upload.quality_score !== null && (
              <span className="text-xs text-muted-foreground">
                clarity {Math.round(upload.quality_score * 100)}%
              </span>
            )}
          </div>

          <ScanImageViewer
            imageId={upload.image_id}
            token={token ?? ""}
            label="Captured retina scan"
          />

          {busy === "analyzing" && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Spinner size="sm" /> Running dual-engine analysis&hellip;
            </div>
          )}

          {finding && finding.analysis_status === "failed" && (
            <Alert variant="destructive">
              <Info />
              <AlertTitle>Analysis unavailable</AlertTitle>
              <AlertDescription>
                The AI engines are not deployed on the API server yet. The scan
                is saved and can be re-analyzed once the models are available.
                Add a health-worker note about the patient and continue.
              </AlertDescription>
            </Alert>
          )}

          {finding && finding.analysis_status === "completed" && (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-lg bg-muted/60 p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  DR severity
                </p>
                <p className="mt-1 font-heading text-lg font-bold">
                  {gradeLabels[finding.icdr_grade ?? 0] ?? "—"}
                </p>
              </div>
              <div className="rounded-lg bg-muted/60 p-3">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  Consistency
                </p>
                <Badge
                  tone={findingBadgeTone(finding.consistency_status)}
                >
                  {finding.consistency_status}
                </Badge>
              </div>
            </div>
              <ModelProvenanceNote finding={finding} />
            </>
          )}
        </>
      )}

      {error && (
        <Alert variant="destructive">
          <Info />
          <AlertTitle>Upload failed</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  )
}

function WorkerDashboard() {
  const { token } = useSession()
  const [patients, setPatients] = React.useState<PatientOut[] | null>(null)
  const [selected, setSelected] = React.useState<PatientOut | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [retry, setRetry] = React.useState(0)

  React.useEffect(() => {
    if (!token) return
    let active = true
    patientsApi
      .list(token)
      .then((list) => {
        if (!active) return
        setPatients(list)
        if (!selected && list.length > 0) setSelected(list[0])
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
    return () => {
      active = false
    }
    // selected intentionally omitted so initial load picks the first patient
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, retry])

  function handleCreated(patient: PatientOut) {
    setPatients((prev) => [...(prev ?? []), patient])
    setSelected(patient)
  }

  function handleLoginAdded(patient: PatientOut) {
    setPatients((prev) => (prev ?? []).map((p) => (p.id === patient.id ? patient : p)))
    setSelected(patient)
  }

  return (
    <DashboardShell
      title="Patients & screenings"
      description="Register village patients, upload their retina scans, and review AI findings."
    >
      {error && (
        <Alert variant="destructive">
          <Info />
          <AlertTitle>Could not load patients</AlertTitle>
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

      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Add patient</CardTitle>
            <CardDescription>
              Record someone at today&apos;s screening camp.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <NewPatientForm onCreated={handleCreated} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Screen a patient</CardTitle>
            <CardDescription>
              Pick a patient, then upload the capture from the fundus camera.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {patients === null ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Spinner size="sm" /> Loading patients&hellip;
              </div>
            ) : patients.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No patients yet. Add the first patient on the left.
              </p>
            ) : (
              <div className="flex flex-col gap-4">
                <div
                  role="listbox"
                  aria-label="Select patient"
                  className="flex max-h-48 flex-col gap-1 overflow-y-auto rounded-lg border p-1"
                >
                  {patients.map((patient) => {
                    const isSelected = selected?.id === patient.id
                    return (
                      <button
                        key={patient.id}
                        type="button"
                        role="option"
                        aria-selected={isSelected}
                        onClick={() => setSelected(patient)}
                        className={cn(
                          "flex items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors",
                          isSelected
                            ? "bg-primary text-primary-foreground"
                            : "hover:bg-muted",
                        )}
                      >
                        <span>
                          <strong>{patient.full_name}</strong>
                          {patient.age && (
                            <span className="opacity-80"> · {patient.age} yrs</span>
                          )}
                          {patient.has_login && (
                            <span className="ml-1 inline-block rounded bg-primary/10 px-1 text-[10px] leading-[18px] text-primary">
                              LOGIN
                            </span>
                          )}
                        </span>
                        <span className={cn("text-xs", isSelected ? "opacity-80" : "text-muted-foreground")}>
                          {patient.village || patient.district || "—"}
                        </span>
                      </button>
                    )
                  })}
                </div>
                {selected && (
                  <>
                    <PatientLoginPanel patient={selected} onLoginAdded={handleLoginAdded} />
                    <PatientCasePanel key={selected.id} patient={selected} />
                    <ScanWorkflow key={selected.id} patient={selected} />
                  </>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </DashboardShell>
  )
}

export default function WorkerDashboardPage() {
  return (
    <RequireRole roles={["health_worker"]}>
      <WorkerDashboard />
    </RequireRole>
  )
}