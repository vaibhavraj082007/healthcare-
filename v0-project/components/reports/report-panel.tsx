"use client"

/**
 * Universal explainable screening report (Phase-4-A fixes).
 *
 * The same clinical structure is rendered for the patient and the doctor:
 *   Header snapshot -> Findings -> Observations -> Recommendation -> Disclaimer
 * which mirrors the generated `report_text` byte-for-byte in structure. The
 * patient layout keeps plain-language wording; the clinical variant additionally
 * surfaces the structured model details (flag reason, engine, region clusters).
 *
 * Fix 1 also applies here: the image area uses the shared in-tab
 * ScanImageViewer (zoom/pan + Fundus/Heatmap toggle) rather than a static
 * heatmap image.
 */

import * as React from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { ScanImageViewer } from "@/components/reports/image-viewer"
import {
  type ScreeningReport,
  reportsApi,
} from "@/lib/api"
import { findingBadgeTone } from "@/lib/consistency"
import { cn } from "cn"
import { Info, TriangleAlert } from "lucide-react"

type Lang = "en" | "hi"

function pick(lang: Lang, en: string, hi: string): string {
  return lang === "hi" ? hi : en
}

const LESION_LABELS: Record<string, string> = {
  microaneurysm: "Microaneurysms",
  hemorrhage: "Hemorrhages",
  hard_exudate: "Hard exudates",
  soft_exudate: "Soft exudates / cotton-wool spots",
}

const GRADE_LABELS: Record<number, string> = {
  0: "No DR",
  1: "Mild NPDR",
  2: "Moderate NPDR",
  3: "Severe NPDR",
  4: "Proliferative DR",
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—"
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "numeric" })
}

function ReportHeader({ report, lang }: { report: ScreeningReport; lang: Lang }) {
  const h = report.header
  if (!h || (!h.patient_name && !h.scan_date)) return null
  const eyeValue =
    lang === "hi"
      ? (report.structured_findings.hi?.eye ?? "दर्ज नहीं")
      : (h.eye_laterality ?? "not captured")
  return (
    <div className="rounded-lg border bg-muted/30 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="font-semibold">{h.patient_name ?? pick(lang, "Patient", "रोगी")}</span>
        {h.patient_age != null && (
          <span className="text-muted-foreground">
            {h.patient_age} {pick(lang, "yrs", "वर्ष")}
            {h.patient_gender ? `, ${h.patient_gender}` : ""}
          </span>
        )}
        <span className="text-muted-foreground">
          {pick(lang, `Scan #${report.image_id.slice(0, 8)}`, `स्कैन #${report.image_id.slice(0, 8)}`)}
        </span>
        <span className="text-muted-foreground">
          {pick(lang, "Scanned ", "स्कैन ")}
          {formatDate(h.scan_date)}
        </span>
        {h.referring_phc && (
          <span className="text-muted-foreground">PHC {h.referring_phc}</span>
        )}
        {h.submitting_worker && (
          <span className="text-muted-foreground">
            {pick(lang, "via ", "द्वारा ")}
            {h.submitting_worker}
          </span>
        )}
        <span className="text-muted-foreground">
          {pick(lang, "Eye: ", "आँख: ")}
          {eyeValue}
        </span>
      </div>
    </div>
  )
}

function FindingsGrid({ report, lang }: { report: ScreeningReport; lang: Lang }) {
  const sf = report.structured_findings
  const breakdown = sf.lesion_breakdown?.length
    ? sf.lesion_breakdown
    : sf.lesion_summary.map((l) => ({ type: l.type, count: l.count }))
  const region = report.region_notes ?? sf.region_notes ?? null
  const gradeLabel =
    lang === "hi"
      ? (sf.hi?.grade_label ?? sf.icdr_grade_label)
      : sf.icdr_grade != null
        ? (GRADE_LABELS[sf.icdr_grade] ?? sf.icdr_grade_label)
        : sf.icdr_grade_label
  const lesionLabel = (type: string) =>
    lang === "hi"
      ? (sf.hi?.lesion_labels?.[type] ?? LESION_LABELS[type] ?? type.replace(/_/g, " "))
      : (LESION_LABELS[type] ?? type.replace(/_/g, " "))
  const regionNote =
    lang === "hi"
      ? (sf.hi?.region_notes ?? region ?? "क्षेत्र विश्लेषण उपलब्ध नहीं।")
      : (region ?? "Region analysis unavailable.")
  const basisNote =
    lang === "hi"
      ? (sf.hi?.grade_basis ?? sf.grade_basis ?? "नीचे सादा-भाषा सारांश देखें।")
      : (sf.grade_basis ?? "See the plain-language summary below.")

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="rounded-lg bg-muted/60 p-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {pick(lang, "DR severity", "डीआर गंभीरता")}
        </p>
        <p className="mt-1 font-heading text-lg font-bold">
          {gradeLabel}
          {sf.icdr_grade != null && (
            <span className="ml-1.5 text-sm font-normal text-muted-foreground">
              {lang === "hi" ? "ग्रेड" : "grade"} {sf.icdr_grade}
            </span>
          )}
        </p>
        <Badge tone={findingBadgeTone(sf.consistency_status)} className="mt-1">
          {lang === "hi" ? (sf.hi?.consistency_status ?? sf.consistency_status) : sf.consistency_status}
        </Badge>
      </div>

      <div className="rounded-lg bg-muted/60 p-3">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {pick(lang, "Lesion breakdown", "घाव विवरण")}
        </p>
        <ul className="mt-1 grid gap-1">
          {breakdown.length === 0 ? (
            <li className="text-sm text-muted-foreground">
              {pick(lang, "Not available", "उपलब्ध नहीं")}
            </li>
          ) : (
            breakdown.map((l) => (
              <li key={l.type} className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{lesionLabel(l.type)}</span>
                <span className="font-medium tabular-nums">{l.count}</span>
              </li>
            ))
          )}
        </ul>
      </div>

      <div className="rounded-lg bg-muted/60 p-3 sm:col-span-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {pick(lang, "Region of AI attention", "AI ध्यान क्षेत्र")}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{regionNote}</p>
      </div>

      <div className="rounded-lg bg-muted/60 p-3 sm:col-span-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {pick(lang, "Basis for this grade", "इस ग्रेड का आधार")}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{basisNote}</p>
      </div>
    </div>
  )
}

function ObservationsBlock({ report, lang }: { report: ScreeningReport; lang: Lang }) {
  const observations = report.observations?.length
    ? (lang === "hi" ? report.structured_findings.hi?.observations ?? report.observations : report.observations)
    : (lang === "hi" ? report.structured_findings.hi?.observations ?? report.structured_findings.observations : report.structured_findings.observations)
  if (!observations?.length) return null
  const heading = pick(lang, "Observations", "अवलोकन")
  return (
    <div className="rounded-lg border border-amber-300/60 bg-amber-50 p-3 dark:border-amber-500/30 dark:bg-amber-500/10">
      <div className="flex items-start gap-2">
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-semibold text-foreground">{heading}</p>
          <ul className="list-inside space-y-1 text-sm text-muted-foreground">
            {observations.map((o, i) => (
              <li key={i} className="flex gap-2">
                <span className="select-none">•</span>
                <span>{o}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}

function RecommendationBlock({ report, lang }: { report: ScreeningReport; lang: Lang }) {
  const recommendation =
    lang === "hi"
      ? (report.structured_findings.hi?.recommendation ?? report.recommendation ?? report.structured_findings.recommendation)
      : (report.recommendation ?? report.structured_findings.recommendation)
  if (!recommendation) return null
  return (
    <div className="rounded-lg border border-primary/25 bg-primary/10 p-3">
      <div className="flex items-start gap-2">
        <Info className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
        <div className="min-w-0">
          <p className="text-sm font-semibold text-foreground">
            {pick(lang, "Recommended next step", "अनुशंसित अगला कदम")}
          </p>
          <p className="mt-0.5 text-sm text-muted-foreground">{recommendation}</p>
        </div>
      </div>
    </div>
  )
}

function FundusImageAnalysis({ report, imageId, token, lang }: { report: ScreeningReport; imageId: string; token: string; lang: Lang }) {
  // Server truth: the report only advertises a heatmap when one actually exists
  // for this exact image (see API image_urls / gradcam_path). If none exists we
  // render an explicit notice — never a placeholder or another patient's image.
  const heatmapAvailable =
    Boolean(report.gradcam_path) || Boolean(report.heatmap_image_url)
  const scanLabel =
    lang === "hi"
      ? report.header?.patient_name
        ? `${report.header.patient_name} — रेटिना स्कैन`
        : "रेटिना स्कैन"
      : report.header?.patient_name
        ? `${report.header.patient_name} — retina scan`
        : "Retina scan"

  return (
    <section className="rounded-lg border bg-muted/10 p-3">
      <h3 className="font-heading text-sm font-semibold uppercase tracking-wide">
        {pick(lang, "Fundus Image Analysis", "फंडस छवि विश्लेषण")}
      </h3>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="min-w-0 space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">
            {pick(lang, "Original Fundus Image", "मूल फंडस छवि")}
          </p>
          <ScanImageViewer
            imageId={imageId}
            token={token}
            showHeatmap={false}
            label={scanLabel}
          />
        </div>
        <div className="min-w-0 space-y-1.5">
          <p className="text-xs font-medium text-muted-foreground">
            {pick(lang, "AI Explainability Heatmap", "AI व्याख्या हीटमैप")}
          </p>
          {heatmapAvailable ? (
            <>
              <ScanImageViewer
                imageId={imageId}
                token={token}
                showHeatmap
                defaultMode="heatmap"
                thumbnailSource="heatmap"
                label={lang === "hi" ? "AI व्याख्या हीटमैप" : "AI Explainability Heatmap"}
              />
              <p className="text-xs leading-relaxed text-muted-foreground">
                {pick(
                  lang,
                  "Highlighted regions indicate areas of the fundus image that contributed to the AI model's prediction. The heatmap is intended for explainability and does not independently establish a clinical diagnosis.",
                  "हाइलाइट किए गए क्षेत्र फंडस छवि के उन हिस्सों को दर्शाते हैं जिन्होंने AI मॉडल की भविष्यवाणी में योगदान दिया। हीटमैप केवल व्याख्या के लिए है और यह स्वतंत्र रूप से चिकित्सकीय निदान स्थापित नहीं करता।",
                )}
              </p>
            </>
          ) : (
            <div className="flex items-center gap-2 rounded-md border border-dashed bg-muted/40 p-3 text-sm text-muted-foreground">
              <TriangleAlert className="size-4 shrink-0 text-amber-600 dark:text-amber-400" aria-hidden />
              <span>
                {pick(
                  lang,
                  "Heatmap not available for this scan — the AI explainability map could not be generated for this image.",
                  "इस स्कैन के लिए हीटमैप उपलब्ध नहीं है — इस छवि के लिए AI व्याख्या मानचित्र उत्पन्न नहीं हो सका।",
                )}
              </span>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function DisclaimerBlock({ report, lang }: { report: ScreeningReport; lang: Lang }) {
  const disclaimer =
    lang === "hi"
      ? (report.structured_findings.hi?.disclaimer ?? report.disclaimer ?? report.structured_findings.disclaimer ?? null)
      : (report.disclaimer ?? report.structured_findings.disclaimer ?? null)
  if (!disclaimer) return null
  return (
    <p className="rounded-lg border bg-muted/20 p-3 text-xs leading-relaxed text-muted-foreground">
      {disclaimer}
    </p>
  )
}

function ClinicalDetails({ report }: { report: ScreeningReport }) {
  const sf = report.structured_findings
  const region = sf.region_analysis
  return (
    <details className="rounded-lg border bg-muted/20 p-3">
      <summary className="cursor-pointer text-sm font-medium">
        Structured clinical findings (for review)
      </summary>
      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2">
        <div className="rounded-md bg-muted/40 p-3">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Consistency</p>
          <Badge tone={findingBadgeTone(sf.consistency_status)}>{sf.consistency_status}</Badge>
          {sf.flagged_reason && (
            <p className="mt-2 text-xs text-muted-foreground">{sf.flagged_reason}</p>
          )}
        </div>
        {sf.possible_macular_edema && (
          <div className="rounded-md bg-muted/40 p-3">
            <p className="text-xs uppercase tracking-wide text-muted-foreground">
              Macular edema risk
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {sf.macular_edema_note ?? "Heavy exudation — assess clinically."}
            </p>
          </div>
        )}
        <div className="rounded-md bg-muted/40 p-3">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Region analysis</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {region
              ? `${region.description ?? "—"} (${region.cluster_count ?? 0} hotspots, disc ${region.used_optic_disc ? "detected" : "not detected"})`
              : report.region_notes ?? "Not available"}
          </p>
        </div>
        <div className="rounded-md bg-muted/40 p-3">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">Engine</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {report.model_version ?? "unknown"} · {report.generation_method}
          </p>
        </div>
      </div>
    </details>
  )
}

export function ScreeningReportPanel({
  imageId,
  token,
  variant = "patient",
}: {
  imageId: string
  token: string
  variant?: "patient" | "clinical"
}) {
  const [report, setReport] = React.useState<ScreeningReport | null>(null)
  const [failed, setFailed] = React.useState(false)
  const [lang, setLang] = React.useState<Lang>("en")

  React.useEffect(() => {
    let active = true
    reportsApi
      .get(token, imageId)
      .then((r) => {
        if (active) setReport(r)
      })
      .catch(() => {
        if (active) setFailed(true)
      })
    return () => {
      active = false
    }
  }, [imageId, token])

  if (failed) {
    return (
      <p className="text-sm text-muted-foreground">
        The explainable report is not available yet — please try again in a few
        minutes.
      </p>
    )
  }

  if (!report) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner size="sm" /> Preparing&hellip;
      </div>
    )
  }

  return (
    <div className="report-area space-y-4">
      {variant === "clinical" && (
        <div className="flex items-center justify-between gap-3 no-print">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Generating model v
            {report.model_version ? report.model_version.split(":")[1] ?? report.model_version : "—"}
          </p>
          <Button variant="outline" size="sm" onClick={() => window.print()}>
            Print report
          </Button>
        </div>
      )}

      {variant === "patient" && (
        <div className="flex items-center justify-end gap-2 no-print">
          <p className="text-xs text-muted-foreground">
            {pick(lang, "Language", "भाषा")}
          </p>
          <div className="flex overflow-hidden rounded-full border">
            {(["en", "hi"] as const).map((code) => (
              <button
                key={code}
                type="button"
                onClick={() => setLang(code)}
                className={cn(
                  "px-3 py-1 text-xs font-medium transition-colors",
                  lang === code
                    ? "bg-primary text-primary-foreground"
                    : "bg-background text-muted-foreground hover:text-foreground",
                )}
              >
                {code === "en" ? "English" : "हिंदी"}
              </button>
            ))}
          </div>
        </div>
      )}

      <ReportHeader report={report} lang={lang} />

      <FundusImageAnalysis report={report} imageId={imageId} token={token} lang={lang} />

      <FindingsGrid report={report} lang={lang} />

      <ObservationsBlock report={report} lang={lang} />

      <RecommendationBlock report={report} lang={lang} />

      <DisclaimerBlock report={report} lang={lang} />

      {variant === "clinical" && <ClinicalDetails report={report} />}

      {variant === "patient" && (
        <details className="rounded-lg border bg-muted/20 p-3">
          <summary className="cursor-pointer text-sm font-medium">
            {lang === "hi"
              ? report.structured_findings.hi?.patient_report
                ? "पूरा सादा-भाषा पाठ"
                : "Full plain-language text"
              : "Full plain-language text"}
          </summary>
          <pre className="mt-3 whitespace-pre-wrap rounded-md bg-muted/40 p-4 font-sans text-sm leading-relaxed text-muted-foreground">
            {lang === "hi"
              ? (report.structured_findings.hi?.patient_report ?? report.report_text)
              : report.report_text}
          </pre>
        </details>
      )}
    </div>
  )
}