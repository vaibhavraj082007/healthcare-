'use client';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { ImageViewer } from '@/components/ImageViewer';
import React from 'react';

export default function CaseReview({ params }: { params: { id: string } }) {
  const result = {
    patientId: 'PAT-9824',
    date: 'Today, 09:15 AM',
    quality: 'acceptable',
    severity: 4, 
    severityLabel: 'Proliferative DR',
    urgency: 'urgent',
    imageOriginal: 'https://via.placeholder.com/600x400/000000/ffffff?text=Fundus+Image',
    imageEnhanced: 'https://via.placeholder.com/600x400/14b8a6/ffffff?text=CLAHE+Enhanced',
    lesions: [
      { lesion_type: 'neovascularization', bbox: { x_min: 250, y_min: 200, x_max: 300, y_max: 250 }, confidence: 0.98 }
    ]
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '1.8rem', color: 'var(--rs-primary-dark)' }}>Detailed Case Review</h1>
          <p style={{ color: 'var(--rs-text-muted)' }}>Patient: {result.patientId} • Screened: {result.date}</p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '24px' }}>
        <Card>
          <ImageViewer 
            originalPath={result.imageOriginal} 
            enhancedPath={result.imageEnhanced}
            lesions={result.lesions as any}
          />
        </Card>
        
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <Card>
            <h3 style={{ fontSize: '1.1rem', marginBottom: '12px' }}>AI Prediction</h3>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
              <span>Severity:</span>
              <span className="severity-badge grade-4">{result.severityLabel}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Urgency:</span>
              <span className="urgency-tag urgent">Urgent</span>
            </div>
          </Card>
          
          <Card>
            <h3 style={{ fontSize: '1.1rem', marginBottom: '12px' }}>Ophthalmologist Validation</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label className="form-label">Confirmed Grade</label>
                <select className="form-input" defaultValue="4">
                  <option value="0">No DR</option>
                  <option value="1">Mild NPDR</option>
                  <option value="2">Moderate NPDR</option>
                  <option value="3">Severe NPDR</option>
                  <option value="4">Proliferative DR</option>
                </select>
              </div>
              <div>
                <label className="form-label">Clinical Notes</label>
                <textarea className="form-input" rows={4} placeholder="Add findings here..."></textarea>
              </div>
              <Button style={{ marginTop: '8px' }}>Save Validation</Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
