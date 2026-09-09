'use client';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ImageViewer } from '@/components/ImageViewer';
import { t } from '@/lib/i18n';
import React from 'react';

export default function ScreeningResults({ params }: { params: { id: string } }) {
  // Mock data for the shell
  const result = {
    patientId: 'PAT-9821',
    date: 'Oct 14, 2026',
    quality: 'acceptable',
    severity: 2, // Moderate NPDR
    severityLabel: 'Moderate NPDR',
    urgency: 'priority',
    imageOriginal: 'https://via.placeholder.com/600x400/000000/ffffff?text=Fundus+Image',
    imageEnhanced: 'https://via.placeholder.com/600x400/14b8a6/ffffff?text=CLAHE+Enhanced',
    lesions: [
      { lesion_type: 'microaneurysm', bbox: { x_min: 200, y_min: 150, x_max: 220, y_max: 170 }, confidence: 0.95 }
    ]
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '1.8rem', color: 'var(--rs-primary-dark)' }}>{t.results.title}</h1>
          <p style={{ color: 'var(--rs-text-muted)' }}>Patient: {result.patientId} • Screened: {result.date}</p>
        </div>
        <Button onClick={() => window.print()}>Print Report</Button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '20px' }}>
        <Card style={{ borderTop: '4px solid var(--rs-grade-2)' }}>
          <h3 style={{ color: 'var(--rs-text-muted)', fontSize: '0.9rem' }}>{t.results.severity}</h3>
          <div style={{ fontSize: '1.8rem', fontWeight: 700, color: 'var(--rs-grade-2)' }}>{result.severityLabel}</div>
        </Card>
        <Card style={{ borderTop: '4px solid var(--rs-grade-2)' }}>
          <h3 style={{ color: 'var(--rs-text-muted)', fontSize: '0.9rem' }}>{t.results.urgency}</h3>
          <div style={{ marginTop: '8px' }}>
            <span className="urgency-tag priority">Priority Referral (3 Months)</span>
          </div>
        </Card>
        <Card style={{ borderTop: '4px solid var(--rs-grade-0)' }}>
          <h3 style={{ color: 'var(--rs-text-muted)', fontSize: '0.9rem' }}>{t.results.quality}</h3>
          <div style={{ marginTop: '8px' }}>
            <span className="severity-badge grade-0">Acceptable</span>
          </div>
        </Card>
      </div>

      <Card>
        <ImageViewer 
          originalPath={result.imageOriginal} 
          enhancedPath={result.imageEnhanced}
          lesions={result.lesions as any}
        />
      </Card>
    </div>
  );
}
