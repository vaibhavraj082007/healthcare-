'use client';

import React from 'react';
import { QualityAssessmentDetail } from '@/lib/types';
import { Button } from './ui/Button';

interface RecaptureGuidanceProps {
  quality: QualityAssessmentDetail;
  eyeLabel: string;
  onAcknowledgeRecapture: () => void;
  onProceedAnyway?: () => void;
}

export const RecaptureGuidance: React.FC<RecaptureGuidanceProps> = ({
  quality,
  eyeLabel,
  onAcknowledgeRecapture,
  onProceedAnyway,
}) => {
  const isRejected = quality.overall_quality === 'rejected' || !quality.is_acceptable;
  const bgColor = isRejected ? '#fef2f2' : '#fffbeb';
  const borderColor = isRejected ? '#fecaca' : '#fde68a';
  const textColor = isRejected ? '#991b1b' : '#92400e';
  const titleColor = isRejected ? 'var(--rs-urgent, #dc2626)' : '#d97706';

  return (
    <div
      style={{
        background: bgColor,
        border: `1px solid ${borderColor}`,
        borderRadius: '12px',
        padding: '20px',
        marginBottom: '20px',
        boxShadow: '0 2px 6px rgba(0, 0, 0, 0.04)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '1.6rem' }}>{isRejected ? '⚠️' : 'ℹ️'}</span>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.1rem', color: titleColor, fontWeight: 700 }}>
              {isRejected
                ? `Image Quality Rejected (${eyeLabel}) — Recapture Required`
                : `Quality Warning (${eyeLabel})`}
            </h3>
            <p style={{ margin: '2px 0 0', fontSize: '0.85rem', color: textColor }}>
              Optical assessment for Smartphone + 20D Ophthalmic Condensing Lens
            </p>
          </div>
        </div>
        <span
          style={{
            background: isRejected ? '#fee2e2' : '#fef3c7',
            color: textColor,
            padding: '4px 10px',
            borderRadius: '999px',
            fontSize: '0.75rem',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
            border: `1px solid ${borderColor}`,
          }}
        >
          {quality.overall_quality}
        </span>
      </div>

      {/* Numerical Optical Measurements */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: '10px',
          background: 'rgba(255, 255, 255, 0.7)',
          padding: '12px',
          borderRadius: '8px',
          marginBottom: '16px',
          border: `1px solid ${borderColor}`,
        }}
      >
        <div>
          <span style={{ fontSize: '0.75rem', color: '#6b7280', display: 'block' }}>Sharpness Score</span>
          <strong style={{ fontSize: '0.95rem', color: quality.sharpness_score >= 100 ? '#15803d' : '#b91c1c' }}>
            {quality.sharpness_score} {quality.sharpness_score >= 100 ? '✓' : '⚠️'}
          </strong>
        </div>
        <div>
          <span style={{ fontSize: '0.75rem', color: '#6b7280', display: 'block' }}>Uniformity</span>
          <strong style={{ fontSize: '0.95rem', color: quality.illumination_uniformity >= 0.5 ? '#15803d' : '#b91c1c' }}>
            {Math.round(quality.illumination_uniformity * 100)}% {quality.illumination_uniformity >= 0.5 ? '✓' : '⚠️'}
          </strong>
        </div>
        <div>
          <span style={{ fontSize: '0.75rem', color: '#6b7280', display: 'block' }}>20D Lens FOV</span>
          <strong style={{ fontSize: '0.95rem', color: quality.field_of_view_adequate ? '#15803d' : '#b91c1c' }}>
            {quality.field_of_view_adequate ? 'Adequate ✓' : 'Decentered ⚠️'}
          </strong>
        </div>
        <div>
          <span style={{ fontSize: '0.75rem', color: '#6b7280', display: 'block' }}>Artifacts</span>
          <span style={{ fontSize: '0.85rem', color: textColor, fontWeight: 600 }}>
            {quality.artifacts_detected.length > 0 ? quality.artifacts_detected.join(', ') : 'None'}
          </span>
        </div>
      </div>

      {/* Actionable Recapture Checklist */}
      <div style={{ marginBottom: '16px' }}>
        <h4 style={{ margin: '0 0 8px', fontSize: '0.9rem', color: textColor, fontWeight: 700 }}>
          Actionable 20D Optical Adjustment Checklist:
        </h4>
        <ul style={{ margin: 0, paddingLeft: '20px', color: textColor, fontSize: '0.88rem', lineHeight: '1.5' }}>
          {quality.recapture_guidance.map((tip, idx) => (
            <li key={idx} style={{ marginBottom: '6px' }}>
              {tip}
            </li>
          ))}
        </ul>
      </div>

      {/* Action Buttons */}
      <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', alignItems: 'center' }}>
        {onProceedAnyway && !isRejected && (
          <Button variant="secondary" onClick={onProceedAnyway} style={{ fontSize: '0.85rem' }}>
            Proceed Anyway
          </Button>
        )}
        <Button onClick={onAcknowledgeRecapture} style={{ fontSize: '0.85rem' }}>
          📸 Recapture {eyeLabel} (Preserves History)
        </Button>
      </div>
    </div>
  );
};
