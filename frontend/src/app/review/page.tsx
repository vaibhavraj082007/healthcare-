'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { reviewsApi, ReviewQueueItem } from '@/lib/api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const DR_LABELS: Record<number, { label: string; color: string; bg: string }> = {
  0: { label: 'No DR', color: '#22c55e', bg: 'rgba(34,197,94,0.12)' },
  1: { label: 'Mild NPDR', color: '#eab308', bg: 'rgba(234,179,8,0.12)' },
  2: { label: 'Moderate NPDR', color: '#f97316', bg: 'rgba(249,115,22,0.12)' },
  3: { label: 'Severe NPDR', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  4: { label: 'Proliferative DR', color: '#dc2626', bg: 'rgba(220,38,38,0.14)' },
  [-1]: { label: 'Ungradeable', color: '#6b7280', bg: 'rgba(107,114,128,0.12)' },
};

const URGENCY_COLORS: Record<string, { color: string; bg: string }> = {
  urgent: { color: '#dc2626', bg: 'rgba(220,38,38,0.1)' },
  priority: { color: '#f97316', bg: 'rgba(249,115,22,0.1)' },
  routine: { color: '#eab308', bg: 'rgba(234,179,8,0.1)' },
  none: { color: '#6b7280', bg: 'rgba(107,114,128,0.1)' },
};

const STATUS_BADGES: Record<string, { label: string; color: string; bg: string; border: string }> = {
  ai_generated: {
    label: 'AI-Generated',
    color: '#818cf8',
    bg: 'rgba(129,140,248,0.1)',
    border: 'rgba(129,140,248,0.25)',
  },
  awaiting_review: {
    label: 'Awaiting Review',
    color: '#f59e0b',
    bg: 'rgba(245,158,11,0.1)',
    border: 'rgba(245,158,11,0.25)',
  },
  in_review: {
    label: 'In Review',
    color: '#06b6d4',
    bg: 'rgba(6,182,212,0.1)',
    border: 'rgba(6,182,212,0.25)',
  },
  clinician_reviewed: {
    label: 'Clinician-Reviewed',
    color: '#22c55e',
    bg: 'rgba(34,197,94,0.1)',
    border: 'rgba(34,197,94,0.25)',
  },
  recapture_requested: {
    label: 'Recapture Requested',
    color: '#f97316',
    bg: 'rgba(249,115,22,0.1)',
    border: 'rgba(249,115,22,0.25)',
  },
};

const PRIORITY_RULES = [
  { value: 'clinical_urgency', label: 'Clinical Urgency First' },
  { value: 'oldest_first', label: 'Oldest Submission First' },
  { value: 'disagreement_first', label: 'Disagreement/Uncertainty First' },
  { value: 'highest_grade_first', label: 'Highest Predicted Severity First' },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function GradeBadge({ grade }: { grade: number | null }) {
  if (grade === null) return <span style={{ color: 'var(--rs-text-muted)', fontSize: '0.85rem' }}>—</span>;
  const info = DR_LABELS[grade] ?? { label: `Grade ${grade}`, color: '#6b7280', bg: 'rgba(107,114,128,0.12)' };
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '3px 10px',
        borderRadius: '6px',
        background: info.bg,
        color: info.color,
        fontWeight: 700,
        fontSize: '0.82rem',
        border: `1px solid ${info.color}33`,
      }}
    >
      {info.label}
    </span>
  );
}

function UrgencyBadge({ urgency }: { urgency: string | null }) {
  if (!urgency || urgency === 'none') return null;
  const c = URGENCY_COLORS[urgency] ?? URGENCY_COLORS.none;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '5px',
        background: c.bg,
        color: c.color,
        fontWeight: 600,
        fontSize: '0.75rem',
        textTransform: 'uppercase',
        letterSpacing: '0.04em',
      }}
    >
      {urgency}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_BADGES[status] ?? { label: status, color: '#6b7280', bg: 'rgba(107,114,128,0.1)', border: 'rgba(107,114,128,0.2)' };
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '3px 9px',
        borderRadius: '6px',
        background: cfg.bg,
        color: cfg.color,
        border: `1px solid ${cfg.border}`,
        fontWeight: 600,
        fontSize: '0.78rem',
      }}
    >
      {cfg.label}
    </span>
  );
}

function FlagChip({ label, color }: { label: string; color: string }) {
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 7px',
        borderRadius: '4px',
        background: `${color}18`,
        color,
        border: `1px solid ${color}33`,
        fontSize: '0.72rem',
        fontWeight: 600,
        marginRight: '4px',
      }}
    >
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Filter / sort bar
// ---------------------------------------------------------------------------

interface Filters {
  quality: string;
  reviewStatus: string;
  uncertainty: string; // 'any' | 'true' | 'false'
  disagreement: string;
  provisionalSeverity: string;
  prioritySort: string;
}

function FilterBar({
  filters,
  onChange,
  onReset,
}: {
  filters: Filters;
  onChange: (f: Filters) => void;
  onReset: () => void;
}) {
  const update = (key: keyof Filters, value: string) => onChange({ ...filters, [key]: value });

  const sel: React.CSSProperties = {
    padding: '6px 10px',
    borderRadius: '8px',
    border: '1px solid var(--rs-border)',
    background: 'var(--rs-bg-elevated)',
    color: 'var(--rs-text)',
    fontSize: '0.85rem',
    cursor: 'pointer',
    minWidth: '140px',
  };

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '10px',
        alignItems: 'center',
        padding: '14px 18px',
        background: 'var(--rs-bg-elevated)',
        borderRadius: '12px',
        border: '1px solid var(--rs-border)',
      }}
    >
      <span style={{ fontWeight: 700, fontSize: '0.85rem', color: 'var(--rs-text-muted)', marginRight: '4px' }}>
        Filters:
      </span>

      <select style={sel} value={filters.reviewStatus} onChange={e => update('reviewStatus', e.target.value)}>
        <option value="">All Statuses</option>
        <option value="ai_generated">AI-Generated</option>
        <option value="awaiting_review">Awaiting Review</option>
        <option value="in_review">In Review</option>
        <option value="clinician_reviewed">Clinician-Reviewed</option>
        <option value="recapture_requested">Recapture Requested</option>
      </select>

      <select style={sel} value={filters.quality} onChange={e => update('quality', e.target.value)}>
        <option value="">All Quality</option>
        <option value="good">Good</option>
        <option value="acceptable">Acceptable</option>
        <option value="poor">Poor</option>
        <option value="rejected">Rejected</option>
        <option value="ungradeable">Ungradeable</option>
      </select>

      <select
        style={sel}
        value={filters.provisionalSeverity}
        onChange={e => update('provisionalSeverity', e.target.value)}
      >
        <option value="">All Grades</option>
        <option value="0">0 — No DR</option>
        <option value="1">1 — Mild NPDR</option>
        <option value="2">2 — Moderate NPDR</option>
        <option value="3">3 — Severe NPDR</option>
        <option value="4">4 — Proliferative DR</option>
        <option value="-1">−1 Ungradeable</option>
      </select>

      <select style={sel} value={filters.uncertainty} onChange={e => update('uncertainty', e.target.value)}>
        <option value="">Uncertainty: Any</option>
        <option value="true">Uncertain only</option>
        <option value="false">Confident only</option>
      </select>

      <select style={sel} value={filters.disagreement} onChange={e => update('disagreement', e.target.value)}>
        <option value="">Disagreement: Any</option>
        <option value="true">Disagreements only</option>
        <option value="false">Concordant only</option>
      </select>

      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginLeft: 'auto' }}>
        <span style={{ fontSize: '0.82rem', color: 'var(--rs-text-muted)' }}>Sort:</span>
        <select style={sel} value={filters.prioritySort} onChange={e => update('prioritySort', e.target.value)}>
          {PRIORITY_RULES.map(r => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>

      <button
        onClick={onReset}
        style={{
          padding: '6px 12px',
          borderRadius: '8px',
          border: '1px solid var(--rs-border)',
          background: 'transparent',
          color: 'var(--rs-text-muted)',
          fontSize: '0.82rem',
          cursor: 'pointer',
        }}
      >
        Reset
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const DEFAULT_FILTERS: Filters = {
  quality: '',
  reviewStatus: '',
  uncertainty: '',
  disagreement: '',
  provisionalSeverity: '',
  prioritySort: 'clinical_urgency',
};

export default function ReviewQueuePage() {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [items, setItems] = useState<ReviewQueueItem[]>([]);
  const [meta, setMeta] = useState<{
    total: number;
    priority_rule: string;
    priority_rule_requires_clinical_approval: boolean;
    priority_rule_approval_note: string;
  } | null>(null);

  const load = useCallback(async (f: Filters) => {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string | number | boolean> = {
        priority_sort: f.prioritySort,
        limit: 100,
      };
      if (f.quality) params.quality = f.quality;
      if (f.reviewStatus) params.review_status = f.reviewStatus;
      if (f.uncertainty) params.uncertainty = f.uncertainty === 'true';
      if (f.disagreement) params.disagreement = f.disagreement === 'true';
      if (f.provisionalSeverity !== '') params.provisional_severity = Number(f.provisionalSeverity);

      const data = await reviewsApi.getQueue(params as Parameters<typeof reviewsApi.getQueue>[0]);
      setItems(data.items);
      setMeta({
        total: data.total,
        priority_rule: data.priority_rule,
        priority_rule_requires_clinical_approval: data.priority_rule_requires_clinical_approval,
        priority_rule_approval_note: data.priority_rule_approval_note,
      });
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to load review queue';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(filters);
  }, [filters, load]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <h1 style={{ fontSize: '1.9rem', fontWeight: 800, color: 'var(--rs-primary-dark)', marginBottom: '6px' }}>
            Ophthalmologist Review Queue
          </h1>
          <p style={{ color: 'var(--rs-text-muted)', fontSize: '0.92rem' }}>
            Cases pending specialist validation from Primary Health Centres.
          </p>
        </div>
        {meta && (
          <div
            style={{
              textAlign: 'right',
              padding: '10px 16px',
              borderRadius: '10px',
              background: 'var(--rs-bg-elevated)',
              border: '1px solid var(--rs-border)',
              minWidth: '220px',
            }}
          >
            <div style={{ fontSize: '0.75rem', color: 'var(--rs-text-muted)', marginBottom: '3px' }}>
              Total cases
            </div>
            <div style={{ fontSize: '1.6rem', fontWeight: 800, color: 'var(--rs-primary-dark)' }}>
              {meta.total}
            </div>
          </div>
        )}
      </div>

      {/* Prioritization notice */}
      {meta?.priority_rule_requires_clinical_approval && (
        <div
          style={{
            display: 'flex',
            gap: '12px',
            padding: '12px 16px',
            borderRadius: '10px',
            background: 'rgba(245,158,11,0.07)',
            border: '1px solid rgba(245,158,11,0.25)',
            alignItems: 'flex-start',
          }}
        >
          <span style={{ fontSize: '1.2rem', flexShrink: 0 }}>⚠</span>
          <div>
            <div style={{ fontWeight: 700, color: '#d97706', fontSize: '0.88rem', marginBottom: '3px' }}>
              Priority Rule: {meta.priority_rule} — Requires Clinical Approval
            </div>
            <div style={{ color: '#78716c', fontSize: '0.81rem', lineHeight: 1.5 }}>
              {meta.priority_rule_approval_note}
            </div>
          </div>
        </div>
      )}

      {/* Filters */}
      <FilterBar
        filters={filters}
        onChange={setFilters}
        onReset={() => setFilters(DEFAULT_FILTERS)}
      />

      {/* State badges legend */}
      <div
        style={{
          display: 'flex',
          gap: '10px',
          alignItems: 'center',
          flexWrap: 'wrap',
          padding: '10px 16px',
          background: 'var(--rs-bg-elevated)',
          borderRadius: '10px',
          border: '1px solid var(--rs-border)',
        }}
      >
        <span style={{ fontSize: '0.78rem', color: 'var(--rs-text-muted)', marginRight: '6px', fontWeight: 600 }}>
          State:
        </span>
        {Object.entries(STATUS_BADGES).map(([key, cfg]) => (
          <StatusBadge key={key} status={key} />
        ))}
      </div>

      {/* Error */}
      {error && (
        <div
          style={{
            padding: '14px 18px',
            borderRadius: '10px',
            background: 'rgba(239,68,68,0.07)',
            border: '1px solid rgba(239,68,68,0.25)',
            color: '#dc2626',
            fontSize: '0.9rem',
          }}
        >
          ⚠ {error}
        </div>
      )}

      {/* Queue table */}
      <div
        style={{
          background: 'var(--rs-bg-card)',
          borderRadius: '14px',
          border: '1px solid var(--rs-border)',
          overflow: 'hidden',
          boxShadow: '0 2px 16px rgba(0,0,0,0.08)',
        }}
      >
        {loading ? (
          <div
            style={{
              padding: '60px',
              textAlign: 'center',
              color: 'var(--rs-text-muted)',
              fontSize: '0.95rem',
            }}
          >
            <div style={{ fontSize: '1.4rem', marginBottom: '10px' }}>⏳</div>
            Loading review queue…
          </div>
        ) : items.length === 0 ? (
          <div
            style={{
              padding: '60px',
              textAlign: 'center',
              color: 'var(--rs-text-muted)',
              fontSize: '0.95rem',
            }}
          >
            <div style={{ fontSize: '2rem', marginBottom: '10px' }}>✓</div>
            No cases match the current filters.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr
                style={{
                  borderBottom: '2px solid var(--rs-border)',
                  background: 'var(--rs-bg-elevated)',
                }}
              >
                {[
                  'Urgency',
                  'Patient',
                  'Eye',
                  'Date',
                  'AI Grade',
                  'Quality',
                  'Flags',
                  'State',
                  'Confirmed Grade',
                  '',
                ].map(h => (
                  <th
                    key={h}
                    style={{
                      padding: '12px 14px',
                      fontSize: '0.78rem',
                      fontWeight: 700,
                      color: 'var(--rs-text-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((item, idx) => (
                <QueueRow key={item.screening_id} item={item} idx={idx} />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Disclaimer footer */}
      <div
        style={{
          padding: '12px 16px',
          borderRadius: '10px',
          background: 'rgba(99,102,241,0.05)',
          border: '1px solid rgba(99,102,241,0.15)',
          fontSize: '0.78rem',
          color: 'var(--rs-text-muted)',
          lineHeight: 1.6,
        }}
      >
        <strong style={{ color: 'var(--rs-text)' }}>Research Screening Tool.</strong> All AI findings
        shown are provisional outputs from the RetinaShield research pipeline. They are NOT autonomous
        clinical diagnoses. The reviewing ophthalmologist is responsible for all clinical conclusions.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Queue Row
// ---------------------------------------------------------------------------

function QueueRow({ item, idx }: { item: ReviewQueueItem; idx: number }) {
  const isLocked = Boolean(item.locked_by_id);
  const screened = new Date(item.screened_at);
  const now = Date.now();
  const ageHours = Math.floor((now - screened.getTime()) / 3_600_000);
  const ageLabel =
    ageHours < 1 ? 'Just now' : ageHours < 24 ? `${ageHours}h ago` : `${Math.floor(ageHours / 24)}d ago`;

  const baseRow: React.CSSProperties = {
    borderBottom: '1px solid var(--rs-border)',
    background: idx % 2 === 0 ? 'var(--rs-bg-card)' : 'var(--rs-bg-elevated)',
    transition: 'background 0.15s',
  };

  return (
    <tr style={baseRow}>
      {/* Urgency */}
      <td style={{ padding: '12px 14px' }}>
        <UrgencyBadge urgency={item.ai_referral_urgency} />
      </td>

      {/* Patient */}
      <td style={{ padding: '12px 14px' }}>
        <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>
          {item.patient_name ?? 'Unknown patient'}
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--rs-text-muted)', marginTop: '2px' }}>
          {item.facility_id ?? '—'}
        </div>
      </td>

      {/* Eye */}
      <td style={{ padding: '12px 14px' }}>
        <span
          style={{
            display: 'inline-block',
            padding: '2px 8px',
            borderRadius: '5px',
            background: 'rgba(99,102,241,0.1)',
            color: '#818cf8',
            fontWeight: 700,
            fontSize: '0.8rem',
          }}
        >
          {item.eye === 'left' ? 'OS (L)' : item.eye === 'right' ? 'OD (R)' : item.eye}
        </span>
      </td>

      {/* Date */}
      <td style={{ padding: '12px 14px' }}>
        <div style={{ fontSize: '0.85rem' }}>{screened.toLocaleDateString()}</div>
        <div style={{ fontSize: '0.75rem', color: 'var(--rs-text-muted)' }}>{ageLabel}</div>
      </td>

      {/* AI Grade */}
      <td style={{ padding: '12px 14px' }}>
        <GradeBadge grade={item.ai_dr_grade} />
        {item.ai_confidence != null && (
          <div style={{ fontSize: '0.72rem', color: 'var(--rs-text-muted)', marginTop: '3px' }}>
            {(item.ai_confidence * 100).toFixed(0)}% conf
            {!item.ai_model_trained && ' ⚠ untrained'}
          </div>
        )}
      </td>

      {/* Quality */}
      <td style={{ padding: '12px 14px' }}>
        <span
          style={{
            fontSize: '0.8rem',
            color:
              item.quality_verdict === 'good'
                ? '#22c55e'
                : item.quality_verdict === 'acceptable'
                ? '#eab308'
                : '#ef4444',
          }}
        >
          {item.quality_verdict ?? '—'}
        </span>
      </td>

      {/* Flags */}
      <td style={{ padding: '12px 14px', whiteSpace: 'nowrap' }}>
        {item.is_uncertain && <FlagChip label="Uncertain" color="#f59e0b" />}
        {item.has_disagreement && <FlagChip label="Disagreement" color="#ef4444" />}
        {isLocked && <FlagChip label="🔒 Locked" color="#6b7280" />}
      </td>

      {/* Status */}
      <td style={{ padding: '12px 14px' }}>
        <StatusBadge status={item.review_status} />
      </td>

      {/* Confirmed grade */}
      <td style={{ padding: '12px 14px' }}>
        {item.confirmed_grade_label ? (
          <GradeBadge grade={item.confirmed_dr_grade!} />
        ) : (
          <span style={{ color: 'var(--rs-text-muted)', fontSize: '0.82rem' }}>—</span>
        )}
      </td>

      {/* Action */}
      <td style={{ padding: '12px 14px' }}>
        <Link
          href={`/review/${item.screening_id}`}
          style={{
            display: 'inline-block',
            padding: '7px 16px',
            borderRadius: '8px',
            background: 'var(--rs-primary)',
            color: '#fff',
            fontWeight: 700,
            fontSize: '0.82rem',
            textDecoration: 'none',
            whiteSpace: 'nowrap',
            opacity: isLocked ? 0.65 : 1,
          }}
        >
          {isLocked ? 'View (Locked)' : 'Review Case'}
        </Link>
      </td>
    </tr>
  );
}
