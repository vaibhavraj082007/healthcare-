# NetraScan — Automated DR Analysis & Explainable Diagnostic Platform

AI-powered diabetic retinopathy (DR) screening prototype for rural Primary Health
Centres. **Phase 1** (capture + quality gate + role auth), **Phase 2** (real
trained models + dual-engine analysis + provenance), **Phase 3** (real
Grad-CAM explainability + structured findings + plain-language reports) and
**Phase 4** (telemedicine store-and-forward sync, ophthalmologist sign-off
portal, patient status stages, local-language + voice summaries) are all
implemented. Remaining polish is listed under *Future work*.

---

## Quick start

Requirements: **Python 3.13.1**, **Node 20+ (developed on v25.8.2)**.

```bash
# 1. Frontend
npm install
npm run build

# 2. Backend (from backend/)
python -m venv .venv  # outside backend/, at repo root
pip install -r backend/requirements.txt -r backend/requirements-ml.txt
python -m app.seed                      # demo users, patients, demo scans
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. Run
npm start            # http://localhost:3000  (API at :8000)
```

## Demo accounts

| Role | Email | Password |
|---|---|---|
| Admin | `admin@netrascan.in` | `Admin123!` |
| Patient (Anita Sharma) | `patient@example.org` | `Patient123!` |
| Patient (Mohammed Faizal) | `mo.faizal@example.org` | `Faizal123!` |
| Patient (Lakshmi Devi) | `lakshmi@example.org` | `Lakshmi123!` |
| Patient (Aapti Vishwakarma) | `aapti@example.org` | `Aapti123!` |
| Health worker | `worker@example.org` | `Worker123!` |
| Doctor | `doctor@example.org` | `Doctor123!` |
| Ophthalmologist | `ophthalmologist@netrascan.in` | `Doctor123!` |

> Each patient account is tied to exactly one `patients` row (`own_user_id`); the
> patient dashboard and report/status/summary endpoints resolve records through
> that link, so every patient sees **only their own scans**.

> Auth note: Phase 1's prompt specified phone + mocked-OTP login. NetraScan v2
> ships email + password with bcrypt hashing and an in-memory login rate limiter
> (10 attempts / 15 min per IP). The mocked-OTP flow was intentionally *not*
> implemented — the UI and API are honest about this rather than faking SMS.

## Quality gate

Real checks, tuned on the APTOS 2019 training set:

- **Blur**: variance-of-Laplacian, computed on a fixed **500 px** downscale so the
  metric is resolution-independent. Threshold **15.0** — APTOS sharp fundus
  photos median ~30 (p25 ≈ 21), deliberately blurred captures score < 15.
- **Fundus plausibility**: red-channel dominance (`< 0.32` → "may not be fundus")
  and dark-periphery fraction (`< 0.24` → "no dark periphery") produce warnings.
- **Recapture flow**: failed captures increment `retake_count`; after 3
  consecutive failures the UI suggests checking the lens/camera setup.

## Datasets & models

- **Engine B — DR severity (0–4 ICDR)**: `EfficientNet-B0` fine-tuned on
  **APTOS 2019 Blindness Detection** (3,662 images), weighted CrossEntropyLoss
  (inverse class frequency), stratified 85/15 validation split seeded at 42,
  checkpoint selected on **Quadratic Weighted Kappa**. Confidence = softmax
  probability of the predicted grade. Tensor preprocessing (center-crop 380 →
  CLAHE → denoise → ImageNet normalize) is shared byte-for-byte between
  training and inference (`verify_preprocessing_parity.py` proves it).
- **Engine A — lesion detection**: `YOLOv8n` fine-tuned on **IDRiD**
  (microaneurysms / haemorrhages / hard & soft exudates), 11,378 boxes across
  54 training images. When weights are unavailable the pipeline degrades
  honestly to classifier-only (`detector_ready: false` in `/health`).
- **Dual-engine consistency**: lesion load → expected grade band vs classifier
  grade → `Consistent` / `Flagged for Review` / `Review - Low Lesion Evidence`
  (zero lesions but grade ≥ 2).

Model weights are **not committed** to git. Generated artifacts live in
`backend/models/` (`efficientnet_b0_dr.pt` + `efficientnet_b0_dr_meta.json` with
epoch, val QWK, training date and git commit) and `backend/models/weights`.
Re-train or download as needed.

## Demo samples

`backend/demo_samples/` holds a curated, pre-verified set: **2 clean fundus
images per severity grade (0–4)** plus **2 deliberately blurred/dark captures**
that exercise the recapture flow. Regenerate with:

```bash
python backend/prepare_demo_samples.py --data-dir path/to/aptos2019
```

`python -m app.seed` also populates demo patients/scans/findings so the admin
dashboard and doctor review queue are never empty on first load.

## Phase 3 — Explainable AI & screening reports

Every completed Phase 2 analysis automatically produces (and caches in the
`screening_reports` table):

- **Real Grad-CAM heatmap** computed against the actual trained
  `efficientnet_b0_dr.pt` checkpoint (manual forward/backward hooks on
  `features[-1]`; 5-class head targets the predicted grade, ordinal head the
  raw severity score). The CAM is overlaid pixel-for-pixel on the preprocessed
  image the model actually saw. Generated once, then served from storage
  (`uploads/reports/{image_id}_gradcam.png`) — never regenerated per page view.
  **Failure handling**: OOM / hook / checkpoint errors are caught; the pipeline
  continues with `gradcam_path = null` and the UI shows "Heatmap unavailable".
  Backfill/re-verify a batch with `python backend/generate_reports.py --force`
  (this also runs automatically after classifier training finishes).
- **Structured clinical findings** — a restructuring of the `ai_findings` row
  (ICDR grade + label, lesion summary, total count, consistency status,
  flagged reason, engine `model_version`), served to the admin/clinical view.
- **Plain-language report (template NLG)** — deterministic, fully offline
  (Option A in the spec), patient-friendly wording with a severity-appropriate
  next step. Follow-up recommendation thresholds follow the ICDR severity scale
  and the AAO Diabetic Retinopathy Preferred Practice Pattern (2019): No DR →
  ~12 months, Mild → 6–12 months, Moderate → ~6 months, Severe → prompt
  referral, Proliferative → urgent referral. A clinical disclaimer is embedded
  **in the report text itself** so it survives printing/sharing.

**Invalidation**: reports are keyed to the engine `model_version`
(`efficientnet_b0_dr:<validation_qwk>`). If an image is re-analyzed or the
checkpoint is updated, the stored report is regenerated rather than left stale.

**Limitations disclosed**: Phase 1's capture flow does not record the eye
(OD/OS), so `region_notes` uses *image-relative* quadrants ("upper-left region
of the image"), never anatomical terms — noted in the admin Model Info panel.
The clinical report templates are English; Phase 4's patient summaries add
Hindi + voice on top of the template engine, decoupled from it.

**Report export**: copy/print from the browser via the in-report print button
and a print stylesheet; the dedicated medical report adds an A4 PDF output
(Save as PDF) with nav/shell hidden.

## Phase 4 — Telemedicine & the ophthalmologist review loop

The closed loop: **PHC captures → query quality gate → two-engine analysis →
report + heatmap → store-and-forward sync queue → ophthalmologist review →
sign-off → patient summary in their language, with voice.**

- **Store-and-forward queue** (`sync_queue`, idempotent by `image_id`): every
  generated report is enqueued automatically. A background worker re-checks
  bandwidth (`telemedicine_base_url` /health, >3 s ⇒ low) and transmits with
  exponential backoff (30 s → 60 s → 120 s → 240 s, capped at 5 min). Low
  bandwidth keeps the case *queued* with "Waiting for connection"; transmission
  failures are recorded as `failed` and retried, never dropped. Auto-resumes
  when connectivity returns.
  - **Prototype simplification (stated here honestly)**: the PHC-facing instance
    and the *telemedicine server* are the **same backend**, so a successful
    transmission is an internal state transition (`queued → syncing → synced`).
    The retry/backoff/bandwidth semantics are fully real; only the network hop
    is elided. A real two-server deployment is listed under *Future work*.
  - **Admin demo switch** (`POST /api/sync/offline-sim`): forces the bandwidth
    probe down so the low-bandwidth state can be demonstrated live — the UI
    keeps working and drains the queue when the switch is flipped back.
- **Ophthalmologist role** — a third clinical role (own `/doctor/login` route,
  seeded `ophthalmologist@netrascan.in`). Server-side `require_roles` guards
  every endpoint; the queue never trusts the client.
- **Review portal** (`/dashboard/doctor`): synced cases with the full Phase 3
  evidence (scan, heatmap, structured findings, report), sorted flagged-first,
  filterable (All / Flagged / Awaiting), sync-state chips, and **sign-off**
  (Approved / Revised / Rejected) stored in the auditable `sign_offs` table —
  a revision keeps the AI grade *and* the doctor's `revised_grade` (a natural
  future retraining signal). Opening a case records `viewed_at`.
- **Notifications (§5, polling)**: the dashboard shell polls
  `GET /api/doctor/queue/count` every 20 s, shows a persistent **Queue (N)**
  badge (red when any are `Flagged for Review`) and a toast when new cases
  arrive. Push/email/SMS are explicitly out of scope (Future work).
- **Patient status stages (§6)**: server-derived (no duplicate status column)
  on the patient scan page — *Scan received → Analysis in progress → Awaiting
  doctor review → Reviewed*. Plain language, icon-paired, no fake ETA. The AI
  report and heatmap are **only shown to the patient after sign-off**; before
  that the page says the scan is with the doctor.
- **Local-language + voice summaries (§6–§7)**: after sign-off, a
  doctor-summary is generated into `patient_summaries` in **English + Hindi**
  from per-language templates (never machine translation), using the
  doctor's `revised_grade` when a case was Revised. Voice is **offline** —
  pre-generated Windows SAPI (System.Speech) WAVs per case/language, served
  via an access-controlled endpoint with an in-page play button. No live TTS
  call, no new packages. Hindi audio is generated with **Microsoft Edge TTS**
  (`hi-IN-SwaraNeural`, via the `edge-tts` package) and cached as an `.mp3` per
  case; English uses the offline Windows SAPI WAV path. Audio is generated once
  and cached, so playback after that is fully offline. If no audio can be
  produced, the patient dashboard falls back to the browser's Web Speech API.
  - **Translations note**: the Hindi template copy was authored by a non-native
    writer and should be reviewed by a fluent Hindi speaker before any
    production use (flagged in the code too).
- **Demo data**: `python -m app.seed` pre-syncs the demo cases into the doctor
  queue and pre-signs one case (summary + voice included) so every patient
  stage is demonstrable immediately. A full closed-loop run: log in as
  worker → upload → analyze → the case appears (badge + toast) for
  ophthalmologist → sign off → patient sees *Reviewed* + summary + voice.

### Phase 4 Part A — Dedicated doctor portal & ASHA care bridge

The `/dashboard/doctor` review loop stays, but the **primary doctor landing** is
now the purpose-built **`/doctor` portal** (doctors and ophthalmologists land
here after login):

- **Case queue** (`GET /api/doctor/cases`): every report automatically gets a
  `case_tracking` row (`ensure_case_tracking`, backfilled at startup) with a
  **severity band** derived from the AI grade + consistency flag
  (grade 0–1 Low, 2 Medium, 3–4 High; "Flagged for Review" ⇒ High). The queue
  sorts unflagged-non-urgent last and **flagged-unhandled cases first**, then
  by band, then by status progress. Filters: `severity`, `status`, `phc`,
  `consistency`, `from`, `to`. Summary endpoint drives the dashboard cards
  (Awaiting review / Flagged pending / Claimed by me / Reported today).
- **Natural-language search** (`POST /api/doctor/cases/search`): a constrained
  NL query over the same filter schema (`severity_band`, `status`, `consistency`,
  `phc`, `from_date`, `to_date`). When `ANTHROPIC_API_KEY` is present an
  Anthropic model parses the query; otherwise a deterministic keyword parser
  produces the identical validated schema. Unknown queries return
  `matched: false` with a friendly message (never a silent empty table).
- **Closed-loop follow-up**: a case runs **New → Claimed → Contacted → Reviewed**
  with per-step timestamps (`assigned_doctor_id`, `claimed_at`, `contacted_at`,
  `reviewed_at`). Any case detail page lets the doctor claim it, advance the
  stage, and post **append-only `case_notes`** (never editable). Contact info
  stays masked until the doctor explicitly reveals it (with WhatsApp/Call
  links). Progress bar + timeline show **live** status back to the ASHA worker.
- **ASHA worker bridge**: the worker dashboard now shows a **live case status**
  column per patient (band + stage, auto-refreshing) and a read-only window into
  the doctor's notes thread — plus the ability to post notes back to the doctor
  (e.g. "patient arrived", "transport arranged"), closing the loop without a
  phone call.
- **Existing endpoints are unchanged and additive**: every role still has the
  strict `require_roles` guards, and the old `/dashboard/doctor` sign-off flow
  remains intact (linked from the new case page for direct report sign-off).

New tables: `sync_queue`, `sign_offs`, `patient_summaries`, plus
`case_tracking`/`case_notes` (Phase 4 Part A); new modules:
`app/sync.py` (worker + bandwidth probe), `app/ml/summaries.py` (templates +
SAPI voice), `app/routers/telemedicine.py` (queue/sign-off/summaries APIs),
`app/cases.py` + `app/nl_search.py` + `app/routers/cases.py` (Phase 4 Part A),
the frontend `app/doctor/**` route tree,
`components/reports/report-panel.tsx`, Phase 4 sections in the admin overview
and dashboards.

### Phase 4 Part A fixes — Universal report & in-tab viewer

A follow-up fix cycle that changed **only** report generation and the image
viewer (auth, upload, quality gate, engines, consistency check and the
claim/contact/notes workflow are untouched):

- **In-tab zoom/pan viewer** — `components/reports/image-viewer.tsx` is a shared
  `react-zoom-pan-pinch` lightbox used everywhere a scan is shown (patient
  dashboard, doctor case detail, review-queue rows, ASHA worker preview, and
  inside the report panel). Wheel/pinch zoom, drag pan, Esc/backdrop close, and
  a **Fundus / Heatmap** toggle when a Grad-CAM exists — no more static `<img>`
  or `target="_blank"` jumps.
- **Region description reflects the real heatmap** — `ml/gradcam.py` now
  computes the description from the actual Grad-CAM: threshold at the top 20% of
  activations, `connectedComponentsWithStats` cluster detection, cluster-centre
  classification against the optic disc (best-effort bright-circular detection;
  fallback when absent) and type/key note of whether each hotspot overlaps
  detected lesion boxes. The old hand-written-ish `region_notes_from_cam` shim
  is retained only for backwards compatibility.
- **Full lesion breakdown + grade justification** — every report names all four
  lesion types including explicit zeros, states which lesions actually drive the
  ICDR grade (and which grade-3/4 features the engine *cannot* see), and adds a
  separate, honestly-worded **possible macular edema** flag when heavy hard
  exudation coincides with macula attention (or exudate boxes in the macular
  zone).
- **Universal report format** — patient and doctor views share the same report
  layout (Header snapshot → Findings → Observations → Recommendation →
  standardized closing disclaimer). Demographics are frozen at generation time
  into new `screening_reports` columns (`patient_id/name/age/gender`,
  `referring_phc`, `submitting_worker`, `scan_date`, `eye_laterality`), so a
  later patient-profile edit never rewrites a printed report. `ReportOut` now
  carries the header, observations, recommendation and disclaimer, and the
  frontend renders the same sectioned component for both variants (the patient
  layout hides only the structured-review `<details>` block).
- Detection boxes are persisted (normalized 0–1) on new analyses so the overlap
  and macula signals are computed from real detections; a one-shot
  `app/refresh_reports.py` backfills boxes and regenerates every existing report.

### Phase 4 Part B — Professional medical report

The doctor case detail now renders a **single-page professional medical report**
(document section layout, not a dashboard) built strictly from real AI output:

- **13 numbered sections** on one printable page: Patient Information →
  Examination (Scan ID, date, eye laterality, modality, quality gate result) →
  Fundus Image Review (labelled **Figure 1** original + **Figure 2** AI
  explainability) → Findings (optic disc / macula / vasculature / background,
  lesion lines, region attention) → Detected Lesions table (per-type counts +
  mean confidence) → ICDR Classification (grade, label, classifier confidence,
  basis) → Dual-engine Consistency Check → Impression → Observations →
  Recommendation → AI Analysis Summary → Report Status (Report ID
  `NS-<scan>`, Generated timestamp, generation method, clinical sign-off) →
  AI Disclaimer text embedded in the report itself.
- **Report ID + generated timestamp** are part of the report bundle, and the
  screening quality snapshot (`image_quality`, `quality_score`) is persisted on
  the report row so the printed document never changes retroactively.
- **Visual severity grade scale (0–4)** opens every report as section
  **0. AI Screening Result** — a green→yellow→orange→red ICDR scale with
  live markers snapped to the exact stored grades: the **classifier** grade
  (`ai_findings.icdr_grade`) and the **lesion-based estimate** (derived with
  `lesion_grade_estimate`, the same `lesion_severity_band` mapping the
  dual-engine consistency check uses, so the scale can never disagree with it).
  The render mode is driven by the consistency status itself
  (`severity_scale.mode`): concordant grades collapse into one **AI assessment**
  marker, disagreements show both markers labeled with grade + text name, and
  classifier-only scans show the classifier marker without a lesion estimate.
  Readable in colour-blind and B/W/PDF output. Data is served via
  `structured_findings.medical_report.severity_scale` — a visualization of
  existing rows, no new tables or fields.
- **Heatmap-aware figures**: Figure 2 renders the in-tab Grad-CAM viewer when a
  heatmap exists; when the overlay could not be generated the report shows an
  explicit **"Heatmap unavailable"** placeholder (never a silent duplicate of
  Figure 1), driven by `medical_report.heatmap_available` (= stored
  `gradcam_path` truthiness), and the region-analysis text says so explicitly.
- **Figure 2 heatmap thumbnail on load**: the inline thumbnail is the real
  Grad-CAM overlay (blob fetch, `thumbnailSource="heatmap"`), requested before
  the lightbox opens — the plain fundus photo is never shown where the heatmap
  belongs (pre-demo regression check samples the two thumbnails on canvas).
- **Confidence framing**: classifier / detector scores are labeled as model
  output confidence **"not equivalent to probability of disease"** in the
  classification box and the lesion-table footnote.
- **Interpretation consistency**: the plain-language impression aligns with the
  engines that actually ran — analyzer-only scans say "only the severity
  classifier was available", concordant scans "no discrepancy flagged". A
  flagged/mismatched scan never states the predicted grade as a flat fact: the
  impression reads "the severity classifier predicted X, but this was not
  independently confirmed by the lesion detector (lesion-based estimate: grade
  Y)". Section 13 is headed **AI Disclaimer & Limitations**.
- **2-3 concrete Observations**: the highlighted Observations block always lists
  at least two distinct, data-backed points — the finding in plain terms, the
  specific lesion evidence (exact counts, or the all-zero statement), and the
  consistency outcome (agreed / flagged for review / classifier-only).
- **Eye laterality captured at scan time**: the Phase 1 upload flow asks for the
  eye being scanned (Right OD / Left OS / Both OU / Unknown) and stores it on
  `image_uploads.eye_laterality` (validated on `POST /uploads`); the report
  `examination.eye` shows the captured value and only falls back to "Not
  captured (laterality was not recorded at image capture)" when the field is
  genuinely empty (pre-capture rows).
- **Optic-disc / macula visibility**: every report carries structured
  `optic_disc_visible` / `macula_visible` flags (Yes | Partially | No) in
  section 2 (Examination) — derived purely from the existing heatmap region
  analysis (detected disc centroid + its 2-disc-diameter temporal fovea
  estimate vs the frame edge), never from new detection, and mirrored in the
  patient plain-text report.
- **Hindi (Devanagari) patient report**: every generated report ships a full
  Hindi bundle at `structured_findings.hi` with the same fields the English
  report uses — `grade_label`, `consistency_status`, `flagged_reason`,
  `lesion_labels`, `region_notes`, `grade_basis`, `observations`,
  `recommendation`, `macular_edema_note`, `eye`, `disclaimer`, and a complete
  `patient_report` plain-text render. The Hindi copy is **authored in
  `reports.py`, never machine-translated** (same non-native-writer caveat as the
  voice templates). The patient panel on `/dashboard/patient` shows an
  **English / हिंदी toggle** that swaps the whole panel (headings, findings,
  plain-text section) — a pure data lookup, `variant="patient"` only, so the
  clinical view stays English-only.
- **Print / PDF report**: a toolbar button invokes an A4 print stylesheet that
  hides the entire app shell and outputs only the medical report (clean margins,
  no-nav, section-safe page breaks). Browser "Save as PDF" gives a file directly.
- **In-page figures**: both figures open the shared in-tab lightbox (zoom / pan
  / reset / fullscreen via the Fullscreen API, Esc closes) — never a new tab.
- The review workflow (claim → contact → sign-off, notes thread) remains on the
  same page in a collapsible section hidden from print output.

The structured bundle is served at `structured_findings.medical_report` in the
existing report API; the patient-visible report panel (Phase 4 Part A universal
format) is unchanged.

## Provenance & clinical disclaimer

Every result view shows exactly what was run (model, training source, val QWK,
detector status) plus:

> *NetraScan is a decision-support prototype, not a certified diagnostic device.
> Results must be reviewed by a qualified ophthalmologist before any clinical
> decision.*

The quality gate warns when an image looks non-fundus; however the classifier
has no built-in "is this a retina" check — a non-fundus photo will still produce
a numeric grade, which is disclosed in the UI/README. A binary fundus-vs-non
gate is a listed stretch goal.

## Known constraints & next steps

- **Rural/low-connectivity**: lightweight UI, large touch targets, upload
  progress states, and a store-and-forward sync queue with bandwidth-gated
  backoff and automatic resume. A full PWA offline queue (local capture buffer
  that syncs later) is Future work.
- **Prototype deployments**: one backend hosts both the PHC-facing API and the
  telemedicine role (see Phase 4 notes); reports and heatmaps are regenerated
  after classifier retraining completes via the watchdog script.
- **CPU-only**: the reference machine has no discrete GPU; inference/training
  run on CPU (documented CPU-only fallback, must not crash).

## Future work

- **Real two-server deployment**: PHC instance ↔ telemedicine server over HTTPS,
  with signed payloads replacing the internal-state transition.
- **ABDM integration** (Ayushman Bharat Digital Mission): patient consent,
  ABHA identity linking and record sync to the ABDM ecosystem.
- **PWA offline queue**: buffer captures on-device and batch-sync when
  connectivity returns (the backend queue semantics already support this).
- **Fundus-vs-non-fundus binary gate** so non-retinal photos are rejected early
  rather than graded.
- **More languages & voices**: the template engine and SAPI pipeline are
  table-driven, so extra template languages/voices drop in without new code.
- **Native-speaker review** of the Hindi templates before any real use.
- **Retraining feedback loop**: `Revised` sign-offs are preserved as labels and
  are the intended signal for classifier fine-tuning.
- **Notifications**: push / email / SMS out of band (polling covers the demo).

## Project layout

```
backend/                FastAPI (auth, uploads, quality gate, analyze,
                        dashboard, telemedicine, ML registry, trainers, seed,
                        sync worker, parity script)
  app/ml/               preprocessing | quality_gate | classifier | detector |
                        consistency | registry | gradcam | reports | summaries
  app/routers/          auth | patients | uploads | analyze | dashboard |
                        reports | telemedicine
  demo_samples/         curated pre-verified fundus + poor captures
app/  components/  lib/ Next.js (React + Tailwind): patient/worker/doctor/admin
                        (+ report-panel, review portal, login variants)
```