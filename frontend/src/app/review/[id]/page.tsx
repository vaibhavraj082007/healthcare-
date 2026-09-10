'use client';

/**
 * RetinaShield — Ophthalmologist Case Review Workspace
 *
 * Provides:
 *  - Layered image viewer: original | enhanced | Grad-CAM | vessel mask
 *  - AI findings sidebar (model probabilities, lesion counts, model versions)
 *  - Consistency and calibration panel
 *  - Quality findings panel
 *  - Clinician decision card (grade, ungradeable, recapture, referral, notes)
 *  - Optimistic-concurrency case locking
 *  - Amendment audit history viewer
 *  - Report generation with mandatory validation disclaimers
 *  - Three clear states: AI-generated | Awaiting review | Clinician-reviewed
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { reviewsApi, ClinicianReviewRead, ReviewAmendmentRead } from '@/lib/api';
import { screeningsApi } from '@/lib/api';
import { analysisApi } from '@/lib/api';
import type { Screening, AnalysisResult, GradCAMExplanation, ReportRead } from '@/lib/types';
import { ImageViewer } from '@/components/ImageViewer';
import { GradCAMOverlay } from '@/components/GradCAMOverlay';
import { ConsistencyPanel } from '@/components/ConsistencyPanel';
import ReportViewerModal from '@/components/ReportViewerModal';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DR_LABELS: Record<number, string> = {
  0: 'No DR',
  1: 'Mild NPDR',
  2: 'Moderate NPDR',
  3: 'Severe NPDR',
  4: 'Proliferative DR',
  [-1]: 'Ungradeable',
};

const DR_COLORS: Record<number, string> = {
  0: '#22c55e',
  1: '#eab308',
  2: '#f97316',
  3: '#ef4444',
  4: '#dc2626',
  [-1]: '#6b7280',
};

const URGENCY_CFG: Record<string, { color: string; bg: string; label: string }> = {
  urgent: { color: '#dc2626', bg: 'rgba(220,38,38,0.08)', label: 'Urgent (1 Week)' },
  priority: { color: '#f97316', bg: 'rgba(249,115,22,0.08)', label: 'Priority (3 Months)' },
  routine: { color: '#eab308', bg: 'rgba(234,179,8,0.08)', label: 'Routine (12 Months)' },
  none: { color: '#6b7280', bg: 'rgba(107,114,128,0.08)', label: 'No Referral' },
};

const VALIDATION_DISCLAIMER =
  'INDIVIDUAL CLINICIAN SIGN-OFF — This report has been reviewed and signed by the ' +
  'ophthalmologist identified above. This review reflects an individual clinician\'s ' +
  'assessment based on available images and clinical judgment.\n\n' +
  'IMPORTANT: Individual sign-off does NOT constitute regulatory or clinical validation ' +
  'of the AI model itself. The AI pipeline is a research screening tool and has not ' +
  'been independently validated for autonomous clinical diagnosis.';

// ---------------------------------------------------------------------------
// Small UI helpers
// ---------------------------------------------------------------------------

function StateBanner({ status }: { status: string }) {
  const cfg: Record<string, { label: string; color: string; bg: string; border: string; icon: string }> = {
    ai_generated: {
      label: 'AI-Generated — Awaiting clinician review',
      color: '#818cf8',
      bg: 'rgba(129,140,248,0.07)',
      border: 'rgba(129,140,248,0.25)',
      icon: '🤖',
    },
    awaiting_review: {
      label: 'Awaiting Review',
      color: '#f59e0b',
      bg: 'rgba(245,158,11,0.07)',
      border: 'rgba(245,158,11,0.25)',
      icon: '⏳',
    },
    in_review: {
      label: 'In Review (Draft)',
      color: '#06b6d4',
      bg: 'rgba(6,182,212,0.07)',
      border: 'rgba(6,182,212,0.25)',
      icon: '✏️',
    },
    clinician_reviewed: {
      label: 'Clinician-Reviewed',
      color: '#22c55e',
      bg: 'rgba(34,197,94,0.07)',
      border: 'rgba(34,197,94,0.25)',
      icon: '✅',
    },
    recapture_requested: {
      label: 'Recapture Requested',
      color: '#f97316',
      bg: 'rgba(249,115,22,0.07)',
      border: 'rgba(249,115,22,0.25)',
      icon: '📷',
    },
  };
  const c = cfg[status] ?? cfg.awaiting_review;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '5px 14px',
        borderRadius: '8px',
        background: c.bg,
        color: c.color,
        border: `1px solid ${c.border}`,
        fontWeight: 700,
        fontSize: '0.85rem',
      }}
    >
      {c.icon} {c.label}
    </span>
  );
}

function GradeChip({ grade }: { grade: number | null }) {
  if (grade === null) return <span style={{ color: 'var(--rs-text-muted)' }}>—</span>;
  const color = DR_COLORS[grade] ?? '#6b7280';
  const label = DR_LABELS[grade] ?? `Grade ${grade}`;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '3px 12px',
        borderRadius: '6px',
        background: `${color}18`,
        color,
        fontWeight: 700,
        fontSize: '0.85rem',
        border: `1px solid ${color}33`,
      }}
    >
      {label}
    </span>
  );
}

function SectionCard({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        background: 'var(--rs-bg-card)',
        borderRadius: '14px',
        border: '1px solid var(--rs-border)',
        overflow: 'hidden',
        boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
      }}
    >
      <div
        style={{
          padding: '14px 18px',
          borderBottom: '1px solid var(--rs-border)',
          background: 'var(--rs-bg-elevated)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '10px',
        }}
      >
        <span style={{ fontWeight: 700, fontSize: '0.92rem', color: 'var(--rs-text)' }}>{title}</span>
        {badge}
      </div>
      <div style={{ padding: '16px 18px' }}>{children}</div>
    </div>
  );
}

function Pill({ label, color = '#6b7280' }: { label: string; color?: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 9px',
        borderRadius: '999px',
        background: `${color}18`,
        color,
        border: `1px solid ${color}33`,
        fontSize: '0.75rem',
        fontWeight: 600,
      }}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Probability bar
// ---------------------------------------------------------------------------

function ProbabilityBar({ probs }: { probs: number[] | null }) {
  if (!probs || probs.length === 0) return null;
  const maxIdx = probs.indexOf(Math.max(...probs));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {probs.map((p, i) => (
        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              fontSize: '0.75rem',
              color: 'var(--rs-text-muted)',
              width: '110px',
              flexShrink: 0,
              textAlign: 'right',
            }}
          >
            {DR_LABELS[i] ?? `Grade ${i}`}
          </span>
          <div
            style={{
              flex: 1,
              height: '10px',
              borderRadius: '5px',
              background: 'var(--rs-border)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                height: '100%',
                width: `${Math.round(p * 100)}%`,
                borderRadius: '5px',
                background: i === maxIdx ? DR_COLORS[i] : `${DR_COLORS[i]}80`,
                transition: 'width 0.4s ease',
              }}
            />
          </div>
          <span
            style={{
              fontSize: '0.77rem',
              fontWeight: i === maxIdx ? 700 : 400,
              color: i === maxIdx ? DR_COLORS[i] : 'var(--rs-text-muted)',
              width: '36px',
              flexShrink: 0,
            }}
          >
            {(p * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Amendment history viewer
// ---------------------------------------------------------------------------

function AmendmentHistory({ amendments }: { amendments: ReviewAmendmentRead[] }) {
  if (amendments.length === 0) {
    return (
      <p style={{ fontSize: '0.85rem', color: 'var(--rs-text-muted)' }}>
        No amendments. This is the original review.
      </p>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      {amendments.map((a, idx) => (
        <div
          key={a.id}
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'var(--rs-bg-elevated)',
            border: '1px solid var(--rs-border)',
            fontSize: '0.82rem',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              marginBottom: '5px',
              color: 'var(--rs-text-muted)',
            }}
          >
            <span>Amendment #{idx + 1}</span>
            <span>{new Date(a.amended_at).toLocaleString()}</span>
          </div>
          {a.previous_grade !== a.new_grade && (
            <div style={{ marginBottom: '3px' }}>
              Grade: <GradeChip grade={a.previous_grade} /> → <GradeChip grade={a.new_grade} />
            </div>
          )}
          {a.previous_referral !== a.new_referral && (
            <div style={{ marginBottom: '3px' }}>
              Referral:{' '}
              <strong>{a.previous_referral}</strong> → <strong>{a.new_referral}</strong>
            </div>
          )}
          {a.change_reason && (
            <div style={{ color: 'var(--rs-text)', marginTop: '4px' }}>
              <em>Reason:</em> {a.change_reason}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Clinician decision card
// ---------------------------------------------------------------------------

interface DecisionFormState {
  confirmedGrade: number;
  macularEdema: boolean | null;
  referral: 'none' | 'routine' | 'priority' | 'urgent';
  followUpMonths: number | null;
  notes: string;
  status: 'draft' | 'final';
  isUngradeable: boolean;
  recaptureRequested: boolean;
  changeReason: string;
}

function DecisionCard({
  screeningId,
  existingReview,
  onReviewSaved,
  onReportGenerated,
}: {
  screeningId: string;
  existingReview: ClinicianReviewRead | null;
  onReviewSaved: (r: ClinicianReviewRead) => void;
  onReportGenerated: (r: ReportRead) => void;
}) {
  const isAmendment = Boolean(existingReview && existingReview.status !== 'draft');

  const [form, setForm] = useState<DecisionFormState>({
    confirmedGrade: existingReview?.confirmed_dr_grade ?? 0,
    macularEdema: existingReview?.macular_edema_present ?? null,
    referral: (existingReview?.referral_recommendation ?? 'routine') as DecisionFormState['referral'],
    followUpMonths: existingReview?.follow_up_months ?? null,
    notes: existingReview?.clinical_notes ?? '',
    status: 'final',
    isUngradeable: existingReview?.is_ungradeable ?? false,
    recaptureRequested: existingReview?.recapture_requested ?? false,
    changeReason: '',
  });

  const [submitting, setSubmitting] = useState(false);
  const [generateReportLoading, setGenerateReportLoading] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState<string | null>(null);

  // Sync form when existingReview changes
  useEffect(() => {
    if (existingReview) {
      setForm({
        confirmedGrade: existingReview.confirmed_dr_grade,
        macularEdema: existingReview.macular_edema_present,
        referral: existingReview.referral_recommendation as DecisionFormState['referral'],
        followUpMonths: existingReview.follow_up_months,
        notes: existingReview.clinical_notes,
        status: 'final',
        isUngradeable: existingReview.is_ungradeable,
        recaptureRequested: existingReview.recapture_requested,
        changeReason: '',
      });
    }
  }, [existingReview]);

  const handleSave = async (asDraft = false) => {
    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(null);
    try {
      if (isAmendment && !form.changeReason.trim()) {
        setSubmitError('A change reason is required when amending a previously-final review.');
        return;
      }
      const result = await reviewsApi.submit(screeningId, {
        confirmed_dr_grade: form.isUngradeable ? -1 : form.confirmedGrade,
        macular_edema_present: form.macularEdema,
        referral_recommendation: form.referral,
        follow_up_months: form.followUpMonths,
        clinical_notes: form.notes,
        status: asDraft ? 'draft' : 'final',
        is_ungradeable: form.isUngradeable,
        recapture_requested: form.recaptureRequested,
        expected_version: existingReview?.review_version ?? null,
        change_reason: isAmendment ? form.changeReason : null,
      });
      setSubmitSuccess(asDraft ? 'Draft saved.' : 'Review finalised and saved.');
      onReviewSaved(result);
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to save review.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleGenerateReport = async () => {
    setGenerateReportLoading(true);
    setSubmitError(null);
    try {
      const report = await reviewsApi.generateReport(screeningId, {
        report_type: 'teleophthalmology_report',
        include_ai_findings: true,
      });
      setSubmitSuccess('Report signed and generated.');
      onReportGenerated(report);
    } catch (err: unknown) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to generate report.');
    } finally {
      setGenerateReportLoading(false);
    }
  };

  const inp: React.CSSProperties = {
    width: '100%',
    padding: '8px 12px',
    borderRadius: '8px',
    border: '1px solid var(--rs-border)',
    background: 'var(--rs-bg)',
    color: 'var(--rs-text)',
    fontSize: '0.9rem',
    boxSizing: 'border-box',
  };

  const lbl: React.CSSProperties = {
    display: 'block',
    fontSize: '0.78rem',
    fontWeight: 600,
    color: 'var(--rs-text-muted)',
    marginBottom: '5px',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* Ungradeable toggle */}
      <label
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          cursor: 'pointer',
          padding: '10px 12px',
          borderRadius: '8px',
          background: form.isUngradeable ? 'rgba(239,68,68,0.07)' : 'var(--rs-bg-elevated)',
          border: `1px solid ${form.isUngradeable ? 'rgba(239,68,68,0.3)' : 'var(--rs-border)'}`,
        }}
      >
        <input
          type="checkbox"
          checked={form.isUngradeable}
          onChange={e => setForm(f => ({ ...f, isUngradeable: e.target.checked, confirmedGrade: e.target.checked ? -1 : 0 }))}
          style={{ width: '16px', height: '16px', cursor: 'pointer' }}
          id="ungradeable-checkbox"
        />
        <span style={{ fontSize: '0.88rem', fontWeight: 600, color: form.isUngradeable ? '#ef4444' : 'var(--rs-text)' }}>
          Mark as Ungradeable
        </span>
      </label>

      {/* Recapture toggle */}
      <label
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          cursor: 'pointer',
          padding: '10px 12px',
          borderRadius: '8px',
          background: form.recaptureRequested ? 'rgba(249,115,22,0.07)' : 'var(--rs-bg-elevated)',
          border: `1px solid ${form.recaptureRequested ? 'rgba(249,115,22,0.3)' : 'var(--rs-border)'}`,
        }}
      >
        <input
          type="checkbox"
          checked={form.recaptureRequested}
          onChange={e => setForm(f => ({ ...f, recaptureRequested: e.target.checked }))}
          style={{ width: '16px', height: '16px', cursor: 'pointer' }}
          id="recapture-checkbox"
        />
        <span style={{ fontSize: '0.88rem', fontWeight: 600, color: form.recaptureRequested ? '#f97316' : 'var(--rs-text)' }}>
          📷 Request Recapture
        </span>
      </label>

      {/* Confirmed grade */}
      {!form.isUngradeable && (
        <div>
          <label style={lbl}>Confirmed DR Grade</label>
          <select
            style={inp}
            value={form.confirmedGrade}
            onChange={e => setForm(f => ({ ...f, confirmedGrade: Number(e.target.value) }))}
            id="confirmed-grade-select"
          >
            <option value={0}>0 — No DR</option>
            <option value={1}>1 — Mild NPDR</option>
            <option value={2}>2 — Moderate NPDR</option>
            <option value={3}>3 — Severe NPDR</option>
            <option value={4}>4 — Proliferative DR (PDR)</option>
          </select>
        </div>
      )}

      {/* Macular edema */}
      <div>
        <label style={lbl}>Macular Oedema</label>
        <select
          style={inp}
          value={form.macularEdema === null ? '' : form.macularEdema ? 'yes' : 'no'}
          onChange={e =>
            setForm(f => ({
              ...f,
              macularEdema: e.target.value === '' ? null : e.target.value === 'yes',
            }))
          }
          id="macular-edema-select"
        >
          <option value="">Not assessed</option>
          <option value="yes">Present</option>
          <option value="no">Absent</option>
        </select>
      </div>

      {/* Referral */}
      <div>
        <label style={lbl}>Referral Recommendation</label>
        <select
          style={inp}
          value={form.referral}
          onChange={e => setForm(f => ({ ...f, referral: e.target.value as DecisionFormState['referral'] }))}
          id="referral-select"
        >
          <option value="none">None</option>
          <option value="routine">Routine (12 months)</option>
          <option value="priority">Priority (3 months)</option>
          <option value="urgent">Urgent (1 week)</option>
        </select>
      </div>

      {/* Follow-up months */}
      <div>
        <label style={lbl}>Follow-up Interval (months)</label>
        <input
          type="number"
          style={inp}
          min={1}
          max={24}
          value={form.followUpMonths ?? ''}
          onChange={e =>
            setForm(f => ({
              ...f,
              followUpMonths: e.target.value ? Number(e.target.value) : null,
            }))
          }
          placeholder="e.g. 6"
          id="follow-up-months"
        />
      </div>

      {/* Clinical notes */}
      <div>
        <label style={lbl}>Clinical Notes *</label>
        <textarea
          style={{ ...inp, height: '90px', resize: 'vertical' }}
          value={form.notes}
          onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
          placeholder="Document findings, reasons for grade, laterality-specific notes..."
          id="clinical-notes"
        />
      </div>

      {/* Change reason (only for amendments) */}
      {isAmendment && (
        <div>
          <label style={{ ...lbl, color: '#f59e0b' }}>
            Change Reason * (required when amending a final review)
          </label>
          <textarea
            style={{
              ...inp,
              height: '60px',
              resize: 'vertical',
              border: '1px solid rgba(245,158,11,0.4)',
              background: 'rgba(245,158,11,0.04)',
            }}
            value={form.changeReason}
            onChange={e => setForm(f => ({ ...f, changeReason: e.target.value }))}
            placeholder="Describe what changed and why..."
            id="change-reason"
          />
        </div>
      )}

      {/* Submit errors / success */}
      {submitError && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'rgba(239,68,68,0.07)',
            border: '1px solid rgba(239,68,68,0.3)',
            color: '#dc2626',
            fontSize: '0.85rem',
          }}
        >
          ⚠ {submitError}
        </div>
      )}
      {submitSuccess && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'rgba(34,197,94,0.07)',
            border: '1px solid rgba(34,197,94,0.3)',
            color: '#16a34a',
            fontSize: '0.85rem',
          }}
        >
          ✓ {submitSuccess}
        </div>
      )}

      {/* Buttons */}
      <div style={{ display: 'flex', gap: '8px' }}>
        <button
          onClick={() => handleSave(true)}
          disabled={submitting}
          id="save-draft-btn"
          style={{
            flex: 1,
            padding: '9px 0',
            borderRadius: '8px',
            border: '1px solid var(--rs-border)',
            background: 'var(--rs-bg-elevated)',
            color: 'var(--rs-text)',
            fontWeight: 600,
            fontSize: '0.88rem',
            cursor: submitting ? 'wait' : 'pointer',
          }}
        >
          Save Draft
        </button>
        <button
          onClick={() => handleSave(false)}
          disabled={submitting}
          id="finalize-review-btn"
          style={{
            flex: 2,
            padding: '9px 0',
            borderRadius: '8px',
            border: 'none',
            background: 'var(--rs-primary)',
            color: '#fff',
            fontWeight: 700,
            fontSize: '0.88rem',
            cursor: submitting ? 'wait' : 'pointer',
          }}
        >
          {submitting ? 'Saving…' : isAmendment ? '✏️ Amend Review' : '✓ Finalise Review'}
        </button>
      </div>

      {/* Generate report (only when final review exists) */}
      {existingReview && existingReview.status !== 'draft' && (
        <div style={{ borderTop: '1px solid var(--rs-border)', paddingTop: '14px' }}>
          <p
            style={{
              fontSize: '0.75rem',
              color: 'var(--rs-text-muted)',
              marginBottom: '8px',
              lineHeight: 1.5,
            }}
          >
            ⚠ Signing generates a clinical report attributed to your account. Individual sign-off does
            NOT imply the AI model has completed regulatory or clinical validation.
          </p>
          <button
            onClick={handleGenerateReport}
            disabled={generateReportLoading}
            id="generate-report-btn"
            style={{
              width: '100%',
              padding: '10px 0',
              borderRadius: '8px',
              border: 'none',
              background: 'linear-gradient(135deg, #1d4ed8, #4f46e5)',
              color: '#fff',
              fontWeight: 700,
              fontSize: '0.9rem',
              cursor: generateReportLoading ? 'wait' : 'pointer',
            }}
          >
            {generateReportLoading ? 'Generating…' : '📋 Approve & Sign Report'}
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quality findings panel
// ---------------------------------------------------------------------------

function QualityPanel({ analysis }: { analysis: AnalysisResult | null }) {
  const qa = analysis?.quality_assessment;
  if (!qa) return <p style={{ color: 'var(--rs-text-muted)', fontSize: '0.85rem' }}>No quality data.</p>;

  const verdictColor =
    qa.overall_quality === 'good'
      ? '#22c55e'
      : qa.overall_quality === 'acceptable'
      ? '#eab308'
      : '#ef4444';

  const row = (label: string, value: React.ReactNode) => (
    <div
      key={label}
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: '6px 0',
        borderBottom: '1px solid var(--rs-border)',
        fontSize: '0.85rem',
      }}
    >
      <span style={{ color: 'var(--rs-text-muted)' }}>{label}</span>
      <span style={{ fontWeight: 600 }}>{value}</span>
    </div>
  );

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '12px',
          padding: '8px 12px',
          borderRadius: '8px',
          background: `${verdictColor}12`,
          border: `1px solid ${verdictColor}33`,
        }}
      >
        <span style={{ fontWeight: 700, color: verdictColor, fontSize: '0.92rem', textTransform: 'capitalize' }}>
          {qa.overall_quality}
        </span>
      </div>
      {row('Sharpness', qa.sharpness_score != null ? qa.sharpness_score.toFixed(1) : '—')}
      {row('Illumination uniformity', qa.illumination_uniformity != null ? qa.illumination_uniformity.toFixed(2) : '—')}
      {row('FOV adequate', qa.field_of_view_adequate != null ? (qa.field_of_view_adequate ? '✓ Yes' : '✗ No') : '—')}
      {qa.artifacts_detected && qa.artifacts_detected.length > 0 && (
        <div style={{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '5px' }}>
          {qa.artifacts_detected.map(a => (
            <Pill key={a} label={a} color="#ef4444" />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lesion summary panel
// ---------------------------------------------------------------------------

const LESION_ICONS: Record<string, string> = {
  microaneurysm: '🔴',
  hemorrhage: '🟥',
  hard_exudate: '🟡',
  soft_exudate: '🟠',
  cotton_wool_spot: '⬜',
  neovascularization: '🟣',
};

function LesionPanel({ analysis }: { analysis: AnalysisResult | null }) {
  const ld = analysis?.lesion_detection;
  if (!ld) return <p style={{ color: 'var(--rs-text-muted)', fontSize: '0.85rem' }}>No lesion data.</p>;

  const isUnavailable = ld.status === 'unavailable';

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px' }}>
        <Pill
          label={isUnavailable ? 'Unavailable' : ld.status === 'heuristic_only' ? 'Heuristic' : 'Model'}
          color={isUnavailable ? '#6b7280' : ld.model_trained ? '#22c55e' : '#eab308'}
        />
        <span style={{ fontSize: '0.78rem', color: 'var(--rs-text-muted)' }}>{ld.model}</span>
      </div>

      {!ld.model_trained && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: '8px',
            background: 'rgba(245,158,11,0.06)',
            border: '1px solid rgba(245,158,11,0.25)',
            fontSize: '0.78rem',
            color: '#78716c',
            marginBottom: '10px',
          }}
        >
          ⚠ Lesion detector has not been trained on retinal data. Counts are heuristic estimates only.
        </div>
      )}

      {ld.model_estimated_count && Object.keys(ld.model_estimated_count).length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {Object.entries(ld.model_estimated_count).map(([type, count]) => (
            <div
              key={type}
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                padding: '6px 10px',
                borderRadius: '6px',
                background: 'var(--rs-bg-elevated)',
                fontSize: '0.85rem',
              }}
            >
              <span>
                {LESION_ICONS[type] ?? '⚫'}{' '}
                <span style={{ textTransform: 'capitalize' }}>{type.replace(/_/g, ' ')}</span>
              </span>
              <strong>{count}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p style={{ fontSize: '0.85rem', color: 'var(--rs-text-muted)' }}>No lesion counts available.</p>
      )}

      <p style={{ fontSize: '0.72rem', color: 'var(--rs-text-muted)', marginTop: '10px', lineHeight: 1.5 }}>
        Lesion estimates are RESEARCH outputs. They do not substitute for clinical judgment.
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Signed report viewer
// ---------------------------------------------------------------------------

function ReportViewer({ report }: { report: ReportRead }) {
  const s = report.summary_json as Record<string, unknown>;
  const clinician = s?.authoritative_clinician_diagnosis as Record<string, unknown> | undefined;
  const ai = s?.ai_research_screening_findings as Record<string, unknown> | undefined;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <div
        style={{
          padding: '12px 16px',
          borderRadius: '10px',
          background: 'rgba(34,197,94,0.05)',
          border: '1px solid rgba(34,197,94,0.25)',
        }}
      >
        <div style={{ fontWeight: 700, color: '#16a34a', marginBottom: '4px', fontSize: '0.88rem' }}>
          ✅ Signed by {(clinician?.clinician_name as string) ?? '—'}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--rs-text-muted)' }}>
          Report type: {report.report_type} · Status: {report.status}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--rs-text-muted)' }}>
          Generated: {new Date(report.created_at).toLocaleString()}
        </div>
      </div>

      {clinician && (
        <div style={{ fontSize: '0.85rem' }}>
          <strong>Clinician grade:</strong> {DR_LABELS[clinician.confirmed_dr_grade as number] ?? '—'}<br />
          <strong>Referral:</strong> {clinician.referral_recommendation as string}<br />
          {Boolean(clinician.clinical_notes) && (
            <div style={{ marginTop: '6px' }}>
              <strong>Notes:</strong> {String(clinician.clinical_notes)}
            </div>
          )}
        </div>
      )}

      {ai && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            background: 'rgba(129,140,248,0.05)',
            border: '1px solid rgba(129,140,248,0.2)',
            fontSize: '0.8rem',
            color: 'var(--rs-text-muted)',
          }}
        >
          <div style={{ fontWeight: 700, color: '#818cf8', marginBottom: '4px', fontSize: '0.78rem' }}>
            AI-GENERATED RESEARCH SCREENING RESULT
          </div>
          AI grade: {DR_LABELS[ai.predicted_dr_grade as number] ?? '—'} · Confidence:{' '}
          {ai.confidence != null ? `${((ai.confidence as number) * 100).toFixed(0)}%` : '—'}
        </div>
      )}

      <div
        style={{
          padding: '10px 14px',
          borderRadius: '8px',
          background: 'rgba(239,68,68,0.04)',
          border: '1px solid rgba(239,68,68,0.15)',
          fontSize: '0.75rem',
          color: '#78716c',
          lineHeight: 1.6,
          whiteSpace: 'pre-line',
        }}
      >
        {VALIDATION_DISCLAIMER}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function CaseReviewPage() {
  const params = useParams<{ id: string }>();
  const screeningId = params.id;

  const [screening, setScreening] = useState<Screening | null>(null);
  const [existingReview, setExistingReview] = useState<ClinicianReviewRead | null>(null);
  const [amendments, setAmendments] = useState<ReviewAmendmentRead[]>([]);
  const [report, setReport] = useState<ReportRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lockStatus, setLockStatus] = useState<{
    locked: boolean;
    mine: boolean;
    expiresAt: string | null;
  }>({ locked: false, mine: false, expiresAt: null });
  const [activeLayer, setActiveLayer] = useState<'original' | 'enhanced' | 'gradcam' | 'vessel'>('original');
  const [showHistory, setShowHistory] = useState(false);
  const [showReport, setShowReport] = useState(false);
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);

  // Load all data
  const load = useCallback(async () => {
    if (!screeningId) return;
    setLoading(true);
    setError(null);
    try {
      const s = await screeningsApi.get(screeningId);
      setScreening(s);

      // Try loading existing review
      try {
        const rev = await reviewsApi.get(screeningId);
        setExistingReview(rev);
        setAmendments(rev.amendments ?? []);
      } catch {
        // 404 = no review yet
      }

      // Try loading signed report
      try {
        const rpt = await reviewsApi.getReport(screeningId);
        setReport(rpt);
      } catch {
        // No report yet
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load case data.');
    } finally {
      setLoading(false);
    }
  }, [screeningId]);

  useEffect(() => {
    void load();
  }, [load]);

  const acquireLock = async () => {
    if (!screeningId) return;
    try {
      const lock = await reviewsApi.claimLock(screeningId);
      setLockStatus({ locked: true, mine: true, expiresAt: lock.lock_expires_at });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not acquire lock.');
    }
  };

  const releaseLock = async () => {
    if (!screeningId) return;
    try {
      await reviewsApi.releaseLock(screeningId);
      setLockStatus({ locked: false, mine: false, expiresAt: null });
    } catch {
      // Best-effort
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '60px', textAlign: 'center', color: 'var(--rs-text-muted)' }}>
        <div style={{ fontSize: '1.4rem', marginBottom: '10px' }}>⏳</div>
        Loading case…
      </div>
    );
  }

  if (error || !screening) {
    return (
      <div
        style={{
          padding: '30px',
          borderRadius: '12px',
          background: 'rgba(239,68,68,0.06)',
          border: '1px solid rgba(239,68,68,0.2)',
          color: '#dc2626',
        }}
      >
        ⚠ {error ?? 'Case not found.'}
      </div>
    );
  }

  const analysis: AnalysisResult | null = screening.analysis_result;
  const sc = analysis?.severity_classification;
  const gradcam: GradCAMExplanation | null = analysis?.gradcam_explanation ?? null;

  // Derive review state
  const reviewState: string = (() => {
    if (!existingReview) {
      return screening.status === 'completed' ? 'awaiting_review' : 'ai_generated';
    }
    if (existingReview.recapture_requested) return 'recapture_requested';
    if (existingReview.status === 'draft') return 'in_review';
    return 'clinician_reviewed';
  })();

  const isReviewLocked = Boolean(existingReview?.locked_by_id && existingReview.locked_by_id !== null);

  // Image URLs
  const imageUrl = screening.analysis_result
    ? `/api/screenings/${screeningId}/images/${screening.analysis_result.image_id}/view`
    : null;

  const gradcamUrl =
    activeLayer === 'gradcam'
      ? (gradcam?.gradcam_overlay_path ?? gradcam?.gradcam_heatmap_path ?? null)
      : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
            <Link
              href="/review"
              style={{
                fontSize: '0.82rem',
                color: 'var(--rs-text-muted)',
                textDecoration: 'none',
                padding: '3px 8px',
                borderRadius: '5px',
                border: '1px solid var(--rs-border)',
              }}
            >
              ← Queue
            </Link>
            <h1 style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--rs-primary-dark)', margin: 0 }}>
              Case Review
            </h1>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <StateBanner status={reviewState} />
            {!screening.model_trained && (
              <Pill label="⚠ Untrained model" color="#f59e0b" />
            )}
            {existingReview?.review_version != null && (
              <Pill label={`v${existingReview.review_version}`} color="#6b7280" />
            )}
          </div>
        </div>

        {/* Lock controls & Reports */}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            onClick={() => setIsReportModalOpen(true)}
            id="open-report-modal-btn"
            style={{
              padding: '7px 14px',
              borderRadius: '8px',
              border: '1px solid var(--rs-border)',
              backgroundColor: '#ffffff',
              color: '#0f172a',
              fontSize: '0.82rem',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            📄 Reports (PDF / Voice)
          </button>
          {isReviewLocked && !lockStatus.mine && (
            <Pill label="🔒 Locked by another reviewer" color="#6b7280" />
          )}
          {!lockStatus.mine ? (
            <button
              onClick={acquireLock}
              id="acquire-lock-btn"
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: '1px solid var(--rs-border)',
                background: 'var(--rs-bg-elevated)',
                color: 'var(--rs-text)',
                fontWeight: 600,
                fontSize: '0.82rem',
                cursor: 'pointer',
              }}
            >
              🔒 Claim Editing Lock
            </button>
          ) : (
            <button
              onClick={releaseLock}
              id="release-lock-btn"
              style={{
                padding: '7px 14px',
                borderRadius: '8px',
                border: '1px solid rgba(34,197,94,0.3)',
                background: 'rgba(34,197,94,0.07)',
                color: '#16a34a',
                fontWeight: 600,
                fontSize: '0.82rem',
                cursor: 'pointer',
              }}
            >
              🔓 Release Lock
            </button>
          )}
        </div>
      </div>

      {/* ── AI research disclaimer (always visible) ── */}
      <div
        style={{
          padding: '10px 16px',
          borderRadius: '10px',
          background: 'rgba(129,140,248,0.05)',
          border: '1px solid rgba(129,140,248,0.18)',
          fontSize: '0.78rem',
          color: 'var(--rs-text-muted)',
          lineHeight: 1.5,
        }}
      >
        <strong style={{ color: '#818cf8' }}>🤖 AI-Generated Research Screening Result</strong> — All model
        outputs shown below are AI-generated and must be independently reviewed by a qualified
        ophthalmologist. They do not constitute a clinical diagnosis.
      </div>

      {/* ── 2-column layout ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: '20px', alignItems: 'start' }}>
        {/* LEFT: Image viewer + panels */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* Layer selector */}
          <div
            style={{
              display: 'flex',
              gap: '6px',
              padding: '10px 14px',
              background: 'var(--rs-bg-elevated)',
              borderRadius: '10px',
              border: '1px solid var(--rs-border)',
            }}
          >
            {(
              [
                { key: 'original', label: '🔵 Original' },
                { key: 'enhanced', label: '🟢 Enhanced' },
                { key: 'gradcam', label: '🔥 Grad-CAM' },
                { key: 'vessel', label: '🩸 Vessel Mask' },
              ] as const
            ).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveLayer(key)}
                style={{
                  padding: '5px 12px',
                  borderRadius: '7px',
                  border: activeLayer === key ? 'none' : '1px solid var(--rs-border)',
                  background: activeLayer === key ? 'var(--rs-primary)' : 'transparent',
                  color: activeLayer === key ? '#fff' : 'var(--rs-text)',
                  fontWeight: activeLayer === key ? 700 : 400,
                  fontSize: '0.8rem',
                  cursor: 'pointer',
                }}
                id={`layer-btn-${key}`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Image viewer */}
          <SectionCard
            title="Fundus Image"
            badge={
              <span style={{ fontSize: '0.75rem', color: 'var(--rs-text-muted)' }}>
                {screening.eye === 'left' ? 'OS (Left)' : 'OD (Right)'} ·{' '}
                Smartphone + 20D condensing lens
              </span>
            }
          >
            {imageUrl ? (
              <ImageViewer
                originalPath={imageUrl}
                enhancedPath={
                  analysis?.enhancement?.enhanced_image_path
                    ? `/api/screenings/${screeningId}/images/${analysis.image_id}/view?type=enhanced`
                    : undefined
                }
                lesions={analysis?.lesion_detection?.detections}
                lesionDetectionResult={analysis?.lesion_detection ?? undefined}
                opticDisc={analysis?.structure_analysis?.optic_disc}
                fovea={analysis?.structure_analysis?.fovea}
                vasculature={analysis?.structure_analysis?.vasculature ?? undefined}
                gradcamExplanation={gradcam}
                isExperimental
              />
            ) : (
              <div
                style={{
                  padding: '40px',
                  textAlign: 'center',
                  color: 'var(--rs-text-muted)',
                  fontSize: '0.85rem',
                  background: 'var(--rs-bg-elevated)',
                  borderRadius: '10px',
                }}
              >
                📷 Image not yet available (analysis pending or failed)
              </div>
            )}
          </SectionCard>

          {/* Grad-CAM panel */}
          <SectionCard
            title="Grad-CAM Explainability"
            badge={
              <span
                style={{
                  fontSize: '0.72rem',
                  padding: '2px 7px',
                  borderRadius: '4px',
                  background: 'rgba(234,179,8,0.1)',
                  color: '#ca8a04',
                  fontWeight: 600,
                  border: '1px solid rgba(234,179,8,0.25)',
                }}
              >
                EXPERIMENTAL
              </span>
            }
          >
            <GradCAMOverlay
              explanation={gradcam}
              originalUrl={imageUrl ?? ''}
              predictedClass={sc?.grade_label ?? null}
              modelTrained={sc?.model_trained ?? false}
            />
          </SectionCard>

          {/* Consistency panel */}
          {analysis?.consistency_analysis && (
            <SectionCard title="AI Engine Consistency Analysis">
              <ConsistencyPanel
                consistency={analysis.consistency_analysis}
                calibration={analysis.confidence_calibration}
                classProbabilities={sc?.class_probabilities ?? null}
              />
            </SectionCard>
          )}
        </div>

        {/* RIGHT: AI findings + decision card */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* AI provisional grade */}
          <SectionCard
            title="AI Provisional Finding"
            badge={<Pill label="AI-Generated" color="#818cf8" />}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.82rem', color: 'var(--rs-text-muted)' }}>Predicted Grade</span>
                <GradeChip grade={screening.dr_grade} />
              </div>
              {screening.dr_confidence != null && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.82rem', color: 'var(--rs-text-muted)' }}>Confidence</span>
                  <span style={{ fontWeight: 700, fontSize: '0.88rem' }}>
                    {(screening.dr_confidence * 100).toFixed(1)}%
                    {!screening.model_trained && (
                      <span style={{ color: '#f59e0b', marginLeft: '6px', fontSize: '0.72rem' }}>⚠ untrained</span>
                    )}
                  </span>
                </div>
              )}
              {screening.referral_urgency && (
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.82rem', color: 'var(--rs-text-muted)' }}>AI Referral Urgency</span>
                  <Pill
                    label={(URGENCY_CFG[screening.referral_urgency] ?? URGENCY_CFG.none).label}
                    color={(URGENCY_CFG[screening.referral_urgency] ?? URGENCY_CFG.none).color}
                  />
                </div>
              )}

              {/* Probability bars */}
              {sc?.class_probabilities && sc.class_probabilities.length > 0 && (
                <div style={{ marginTop: '6px' }}>
                  <div style={{ fontSize: '0.75rem', color: 'var(--rs-text-muted)', marginBottom: '6px', fontWeight: 600 }}>
                    Class probabilities
                  </div>
                  <ProbabilityBar probs={sc.class_probabilities} />
                </div>
              )}

              {/* Model version */}
              <div
                style={{
                  marginTop: '4px',
                  padding: '8px 10px',
                  borderRadius: '7px',
                  background: 'var(--rs-bg-elevated)',
                  fontSize: '0.75rem',
                  color: 'var(--rs-text-muted)',
                }}
              >
                <div>Model: {sc?.model ?? 'RetinaShield-EfficientNetB0'}</div>
                <div>Trained: {sc?.model_trained ? '✓ Yes' : '✗ No (placeholder)'}</div>
                {analysis?.pipeline_version && <div>Pipeline: v{analysis.pipeline_version}</div>}
              </div>
            </div>
          </SectionCard>

          {/* Quality findings */}
          <SectionCard title="Image Quality Assessment">
            <QualityPanel analysis={analysis} />
          </SectionCard>

          {/* Lesion estimates */}
          <SectionCard title="Estimated Lesion Counts" badge={<Pill label="Research estimate" color="#6b7280" />}>
            <LesionPanel analysis={analysis} />
          </SectionCard>

          {/* Clinician decision card */}
          <SectionCard
            title="Clinician Review Decision"
            badge={
              existingReview ? (
                <StateBanner status={reviewState} />
              ) : (
                <Pill label="Not yet reviewed" color="#f59e0b" />
              )
            }
          >
            <DecisionCard
              screeningId={screeningId}
              existingReview={existingReview}
              onReviewSaved={r => {
                setExistingReview(r);
                setAmendments(r.amendments ?? []);
              }}
              onReportGenerated={r => {
                setReport(r);
                setShowReport(true);
              }}
            />
          </SectionCard>

          {/* Amendment history */}
          {amendments.length > 0 && (
            <SectionCard
              title={`Amendment History (${amendments.length})`}
              badge={
                <button
                  onClick={() => setShowHistory(h => !h)}
                  style={{
                    padding: '3px 10px',
                    borderRadius: '6px',
                    border: '1px solid var(--rs-border)',
                    background: 'transparent',
                    color: 'var(--rs-text-muted)',
                    fontSize: '0.78rem',
                    cursor: 'pointer',
                  }}
                >
                  {showHistory ? 'Hide' : 'Show'}
                </button>
              }
            >
              {showHistory ? (
                <AmendmentHistory amendments={amendments} />
              ) : (
                <p style={{ fontSize: '0.82rem', color: 'var(--rs-text-muted)' }}>
                  {amendments.length} amendment(s) recorded. Click Show to view.
                </p>
              )}
            </SectionCard>
          )}

          {/* Signed report */}
          {report && (
            <SectionCard
              title="Signed Clinical Report"
              badge={
                <button
                  onClick={() => setShowReport(h => !h)}
                  style={{
                    padding: '3px 10px',
                    borderRadius: '6px',
                    border: '1px solid rgba(34,197,94,0.3)',
                    background: 'rgba(34,197,94,0.07)',
                    color: '#16a34a',
                    fontSize: '0.78rem',
                    cursor: 'pointer',
                  }}
                >
                  {showReport ? 'Hide' : 'View'}
                </button>
              }
            >
              {showReport ? (
                <ReportViewer report={report} />
              ) : (
                <p style={{ fontSize: '0.82rem', color: '#16a34a' }}>
                  ✅ Report signed. Click View to review.
                </p>
              )}
            </SectionCard>
          )}
        </div>
      </div>

      {/* ── Full-width disclaimer footer ── */}
      <div
        style={{
          padding: '14px 18px',
          borderRadius: '10px',
          background: 'rgba(239,68,68,0.04)',
          border: '1px solid rgba(239,68,68,0.15)',
          fontSize: '0.77rem',
          color: '#78716c',
          lineHeight: 1.6,
        }}
      >
        <strong style={{ color: 'var(--rs-text)' }}>Research Screening Tool — Clinical Safety Notice.</strong>{' '}
        All AI outputs (grades, Grad-CAM, lesion counts) are provisional research findings from the
        RetinaShield screening pipeline. Grad-CAM shows model-influential regions, NOT confirmed lesions
        or proof of a correct prediction. Individual clinician sign-off does NOT imply the AI model has
        completed regulatory or clinical validation. Always apply independent clinical judgment.
      </div>

      {/* Dual Technical & Patient Summary Report Modal */}
      <ReportViewerModal
        screeningId={screeningId}
        isOpen={isReportModalOpen}
        onClose={() => setIsReportModalOpen(false)}
        canSign={existingReview?.status === 'final'}
      />
    </div>
  );
}
