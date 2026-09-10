/**
 * RetinaShield — Consistency Analysis Panel
 *
 * Renders the conservative dual-engine consistency badge, finding label,
 * uncertainty indicators, and per-reason review flags.
 *
 * Design invariants (match backend safety rules):
 *  - "Concordant AI findings" label, never "Confirmed diagnosis"
 *  - Discordant/review badges are visually prominent and always show reasons
 *  - Calibration status ("calibrated" / "uncalibrated_raw_softmax" / "fallback_uniform")
 *    and uncertainty flags are displayed with appropriate visual hierarchy
 *  - All outputs carry the research disclaimer
 */

'use client';
import React from 'react';
import {
  ConsistencyAnalysis,
  ConfidenceCalibration,
  ConsistencyStatus,
  ReferralUrgency,
} from '@/lib/types';

// ---------------------------------------------------------------------------
// Type helpers
// ---------------------------------------------------------------------------
interface ConsistencyPanelProps {
  consistency?: ConsistencyAnalysis | null;
  calibration?: ConfidenceCalibration | null;
  classProbabilities?: number[] | null;
}

const GRADE_LABELS = ['No DR', 'Mild NPDR', 'Moderate NPDR', 'Severe NPDR', 'Proliferative DR'];
const GRADE_COLORS = [
  'var(--rs-grade-0)',
  'var(--rs-grade-1)',
  'var(--rs-grade-2)',
  'var(--rs-grade-3)',
  'var(--rs-grade-4)',
];

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: ConsistencyStatus }) {
  const config: Record<ConsistencyStatus, { label: string; bg: string; fg: string; icon: string }> = {
    concordant: {
      label: 'Concordant AI findings',
      bg: 'rgba(34, 197, 94, 0.15)',
      fg: '#16a34a',
      icon: '✓',
    },
    discordant_classifier_high: {
      label: 'Discordant — Classifier High',
      bg: 'rgba(249, 115, 22, 0.15)',
      fg: '#ea580c',
      icon: '⚠',
    },
    discordant_lesions_high: {
      label: 'Discordant — Lesions High',
      bg: 'rgba(239, 68, 68, 0.15)',
      fg: '#dc2626',
      icon: '⚠',
    },
    uncertain_prediction: {
      label: 'Uncertain Prediction',
      bg: 'rgba(234, 179, 8, 0.15)',
      fg: '#ca8a04',
      icon: '?',
    },
    quality_compromised: {
      label: 'Ungradeable Image',
      bg: 'rgba(107, 114, 128, 0.15)',
      fg: '#6b7280',
      icon: '✗',
    },
    component_unavailable: {
      label: 'Component Unavailable',
      bg: 'rgba(107, 114, 128, 0.15)',
      fg: '#6b7280',
      icon: '✗',
    },
  };
  const cfg = config[status] ?? config.concordant;
  return (
    <div
      id={`consistency-badge-${status}`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '8px',
        padding: '6px 14px',
        borderRadius: '999px',
        background: cfg.bg,
        color: cfg.fg,
        fontWeight: 600,
        fontSize: '0.9rem',
        border: `1.5px solid ${cfg.fg}`,
        letterSpacing: '0.01em',
      }}
    >
      <span style={{ fontWeight: 800, fontSize: '1rem' }}>{cfg.icon}</span>
      {cfg.label}
    </div>
  );
}

function UrgencyTag({ urgency }: { urgency: ReferralUrgency }) {
  const map: Record<ReferralUrgency, { label: string; color: string }> = {
    none: { label: 'Annual Screening', color: 'var(--rs-grade-0)' },
    routine: { label: 'Routine Referral', color: 'var(--rs-grade-1)' },
    priority: { label: 'Priority Referral', color: 'var(--rs-grade-3)' },
    urgent: { label: 'URGENT Referral', color: 'var(--rs-grade-4)' },
  };
  const m = map[urgency] ?? map.none;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '3px 10px',
        borderRadius: '4px',
        background: `${m.color}22`,
        color: m.color,
        border: `1px solid ${m.color}`,
        fontWeight: 700,
        fontSize: '0.82rem',
      }}
    >
      {m.label}
    </span>
  );
}

function CalibrationChip({ status }: { status: string }) {
  const label =
    status === 'calibrated'
      ? 'Temperature-Calibrated'
      : status === 'uncalibrated_raw_softmax'
      ? 'Raw Softmax (Uncalibrated)'
      : 'Fallback Uniform';

  const color = status === 'calibrated' ? '#2563eb' : status === 'fallback_uniform' ? '#dc2626' : '#ca8a04';

  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '4px',
        background: `${color}18`,
        color,
        border: `1px solid ${color}55`,
        fontWeight: 600,
        fontSize: '0.75rem',
        fontFamily: 'monospace',
      }}
    >
      {label}
    </span>
  );
}

function ProbabilityBar({
  label,
  prob,
  gradeIndex,
  isTop,
}: {
  label: string;
  prob: number;
  gradeIndex: number;
  isTop: boolean;
}) {
  const color = GRADE_COLORS[gradeIndex] ?? '#6b7280';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
      <span
        style={{
          width: '110px',
          fontSize: '0.78rem',
          color: isTop ? color : 'var(--rs-text-muted)',
          fontWeight: isTop ? 700 : 400,
          flexShrink: 0,
        }}
      >
        {label}
      </span>
      <div
        style={{
          flex: 1,
          height: '10px',
          background: 'rgba(0,0,0,0.08)',
          borderRadius: '99px',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${(prob * 100).toFixed(1)}%`,
            height: '100%',
            background: isTop ? color : `${color}88`,
            borderRadius: '99px',
            transition: 'width 0.4s ease',
          }}
        />
      </div>
      <span
        style={{
          width: '44px',
          fontSize: '0.78rem',
          textAlign: 'right',
          color: isTop ? color : 'var(--rs-text-muted)',
          fontWeight: isTop ? 700 : 400,
        }}
      >
        {(prob * 100).toFixed(1)}%
      </span>
    </div>
  );
}

function UncertaintyMeter({ value, label, flagged }: { value: number; label: string; flagged: boolean }) {
  const color = flagged ? '#dc2626' : '#22c55e';
  return (
    <div style={{ marginBottom: '8px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '3px' }}>
        <span style={{ fontSize: '0.78rem', color: 'var(--rs-text-muted)' }}>{label}</span>
        <span style={{ fontSize: '0.78rem', fontWeight: 600, color }}>{(value * 100).toFixed(0)}%</span>
      </div>
      <div
        style={{
          height: '6px',
          background: 'rgba(0,0,0,0.08)',
          borderRadius: '99px',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${(value * 100).toFixed(1)}%`,
            height: '100%',
            background: color,
            borderRadius: '99px',
            transition: 'width 0.4s ease',
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function ConsistencyPanel({ consistency, calibration, classProbabilities }: ConsistencyPanelProps) {
  if (!consistency) {
    return (
      <div
        style={{
          padding: '16px',
          borderRadius: '10px',
          background: 'rgba(107,114,128,0.08)',
          color: 'var(--rs-text-muted)',
          fontSize: '0.9rem',
          fontStyle: 'italic',
        }}
      >
        Consistency analysis not available for this result.
      </div>
    );
  }

  const topGrade = consistency.recommended_grade ?? 0;
  const probs = classProbabilities ?? [];
  const topIdx = probs.length > 0 ? probs.indexOf(Math.max(...probs)) : topGrade;

  const needsReview =
    consistency.human_review_required ||
    consistency.consistency_status !== 'concordant';

  const isUncertain = calibration?.is_uncertain ?? false;

  return (
    <div
      id="consistency-analysis-panel"
      style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}
    >
      {/* ── Header badge + finding label ── */}
      <div
        style={{
          padding: '16px 18px',
          borderRadius: '12px',
          background: needsReview
            ? 'rgba(239, 68, 68, 0.06)'
            : 'rgba(34, 197, 94, 0.06)',
          border: `1px solid ${needsReview ? 'rgba(239,68,68,0.2)' : 'rgba(34,197,94,0.2)'}`,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '10px' }}>
          <StatusBadge status={consistency.consistency_status} />
          {calibration && <CalibrationChip status={calibration.status} />}
          <span
            style={{
              fontSize: '0.72rem',
              color: 'var(--rs-text-muted)',
              fontFamily: 'monospace',
            }}
          >
            Rules v{consistency.rules_version}
          </span>
        </div>

        <div
          style={{
            fontSize: '1rem',
            fontWeight: 600,
            color: needsReview ? 'var(--rs-grade-4)' : 'var(--rs-grade-0-dark, #15803d)',
            marginBottom: '8px',
          }}
        >
          {consistency.finding_label}
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          {consistency.recommended_grade !== null && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ fontSize: '0.82rem', color: 'var(--rs-text-muted)' }}>Conservative Grade:</span>
              <span
                style={{
                  fontWeight: 700,
                  fontSize: '0.88rem',
                  color: GRADE_COLORS[consistency.recommended_grade] ?? '#6b7280',
                }}
              >
                {GRADE_LABELS[consistency.recommended_grade] ?? 'Unknown'}
              </span>
            </div>
          )}
          <UrgencyTag urgency={consistency.recommended_urgency} />
        </div>
      </div>

      {/* ── Human review reasons ── */}
      {consistency.human_review_required && consistency.review_reasons.length > 0 && (
        <div
          id="review-reasons-panel"
          style={{
            padding: '14px 16px',
            borderRadius: '10px',
            background: 'rgba(239, 68, 68, 0.06)',
            border: '1px solid rgba(239,68,68,0.25)',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              fontWeight: 700,
              fontSize: '0.88rem',
              color: '#dc2626',
              marginBottom: '10px',
            }}
          >
            <span>⚑</span> Human Review Required
          </div>
          <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {consistency.review_reasons.map((reason, i) => (
              <li key={i} style={{ fontSize: '0.82rem', color: 'var(--rs-text-primary)', lineHeight: 1.5 }}>
                {reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ── Calibrated probability bars ── */}
      {probs.length > 0 && (
        <div
          id="calibrated-probability-bars"
          style={{
            padding: '14px 16px',
            borderRadius: '10px',
            background: 'rgba(0,0,0,0.03)',
            border: '1px solid rgba(0,0,0,0.07)',
          }}
        >
          <div
            style={{
              fontSize: '0.82rem',
              fontWeight: 600,
              color: 'var(--rs-text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              marginBottom: '12px',
            }}
          >
            {calibration?.status === 'calibrated'
              ? 'Calibrated Class Probabilities'
              : 'Raw Softmax Probabilities (Uncalibrated)'}
          </div>
          {GRADE_LABELS.map((label, i) => (
            <ProbabilityBar
              key={i}
              label={label}
              prob={probs[i] ?? 0}
              gradeIndex={i}
              isTop={i === topIdx}
            />
          ))}
        </div>
      )}

      {/* ── Uncertainty indicators ── */}
      {calibration && (
        <div
          id="uncertainty-indicators-panel"
          style={{
            padding: '14px 16px',
            borderRadius: '10px',
            background: isUncertain ? 'rgba(234,179,8,0.06)' : 'rgba(0,0,0,0.03)',
            border: `1px solid ${isUncertain ? 'rgba(234,179,8,0.3)' : 'rgba(0,0,0,0.07)'}`,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              marginBottom: '12px',
            }}
          >
            <span
              style={{
                fontSize: '0.82rem',
                fontWeight: 600,
                color: 'var(--rs-text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}
            >
              Predictive Uncertainty
            </span>
            {isUncertain && (
              <span
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 700,
                  color: '#ca8a04',
                  background: 'rgba(234,179,8,0.12)',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  border: '1px solid rgba(234,179,8,0.3)',
                }}
              >
                ⚠ UNCERTAIN — Expert Review Advised
              </span>
            )}
          </div>
          {calibration.max_calibrated_probability !== null && (
            <UncertaintyMeter
              label="Max Probability"
              value={calibration.max_calibrated_probability}
              flagged={calibration.max_calibrated_probability < 0.65}
            />
          )}
          {calibration.confidence_margin !== null && (
            <UncertaintyMeter
              label="Margin (Top-1 vs Top-2)"
              value={Math.min(1, calibration.confidence_margin)}
              flagged={calibration.confidence_margin < 0.15}
            />
          )}
          {calibration.shannon_entropy !== null && (
            <UncertaintyMeter
              label="Norm. Entropy (↓ better)"
              value={calibration.shannon_entropy}
              flagged={calibration.shannon_entropy > 0.60}
            />
          )}
          {calibration.temperature !== null && (
            <div style={{ marginTop: '8px', fontSize: '0.75rem', color: 'var(--rs-text-muted)' }}>
              Temperature scaling applied: T = {calibration.temperature.toFixed(3)}
            </div>
          )}
        </div>
      )}

      {/* ── Mandatory disclaimer ── */}
      <div
        style={{
          padding: '10px 14px',
          borderRadius: '8px',
          background: 'rgba(239,68,68,0.05)',
          border: '1px solid rgba(239,68,68,0.15)',
          fontSize: '0.75rem',
          color: 'var(--rs-text-muted)',
          lineHeight: 1.5,
          fontStyle: 'italic',
        }}
      >
        ⚠ RESEARCH SCREENING RESULT — Not a clinical diagnosis. A softmax score alone is not clinical certainty.
        All AI findings must be reviewed by a qualified ophthalmologist before any clinical decision.
      </div>
    </div>
  );
}
