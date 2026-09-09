'use client';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { t } from '@/lib/i18n';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function NewScreening() {
  const router = useRouter();
  const [analyzing, setAnalyzing] = useState(false);
  const [fileUploaded, setFileUploaded] = useState(false);
  const [showError, setShowError] = useState(false);

  const handleSimulateCapture = () => {
    setFileUploaded(true);
  };

  const handleAnalyze = () => {
    setAnalyzing(true);
    // Simulate hitting the MATLAB backend
    setTimeout(() => {
      // randomly show an error 1/3 of the time to demonstrate image recapture guidance
      if (Math.random() > 0.6) {
        setShowError(true);
        setAnalyzing(false);
      } else {
        router.push('/screening/results/new_123');
      }
    }, 1500);
  };

  return (
    <div>
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ fontSize: '1.8rem', color: 'var(--rs-primary-dark)' }}>{t.screening.newTitle}</h1>
        <p style={{ color: 'var(--rs-text-muted)' }}>Follow on-screen guidance to capture a high-quality fundus image.</p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '24px' }}>
        <Card>
          <h2 style={{ fontSize: '1.2rem', marginBottom: '16px' }}>1. Patient Details</h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <label className="form-label">Patient ID</label>
              <input type="text" className="form-input" placeholder="e.g. PAT-9821" defaultValue="PAT-9821" />
            </div>
            <div>
              <label className="form-label">Eye</label>
              <select className="form-input">
                <option>Left Eye (OS)</option>
                <option>Right Eye (OD)</option>
              </select>
            </div>
          </div>
        </Card>

        <Card>
          <h2 style={{ fontSize: '1.2rem', marginBottom: '16px' }}>2. Image Capture</h2>
          
          {showError ? (
            <div style={{ background: '#fee2e2', border: '1px solid #fecaca', borderRadius: '8px', padding: '16px', marginBottom: '20px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '1.5rem' }}>⚠️</span>
                <h3 style={{ color: 'var(--rs-urgent)', fontWeight: 600 }}>Image Quality Check Failed</h3>
              </div>
              <p style={{ marginTop: '8px', color: '#991b1b' }}>The image is <strong>UNGRADEABLE</strong> due to severe underexposure and poor focus.</p>
              <ul style={{ marginTop: '12px', marginLeft: '24px', color: '#991b1b' }}>
                <li>Increase camera flash intensity.</li>
                <li>Reduce ambient room lighting.</li>
                <li>Ensure the patient is still and refocus the lens.</li>
              </ul>
              <Button onClick={() => setShowError(false)} style={{ marginTop: '16px' }}>Acknowledge & Recapture</Button>
            </div>
          ) : (
            <div style={{ 
              border: '2px dashed var(--rs-border)', 
              borderRadius: '12px', 
              height: '300px', 
              display: 'flex', 
              flexDirection: 'column',
              alignItems: 'center', 
              justifyContent: 'center',
              background: fileUploaded ? '#f0fdfa' : 'transparent',
              marginBottom: '20px'
            }}>
              {fileUploaded ? (
                <>
                  <span style={{ fontSize: '3rem' }}>📸</span>
                  <p style={{ marginTop: '16px', fontWeight: 600, color: 'var(--rs-primary-dark)' }}>Image captured successfully.</p>
                </>
              ) : (
                <>
                  <span style={{ fontSize: '3rem', opacity: 0.5 }}>📱</span>
                  <p style={{ marginTop: '16px', color: 'var(--rs-text-muted)' }}>Connect camera or select image file</p>
                  <Button variant="secondary" onClick={handleSimulateCapture} style={{ marginTop: '16px' }}>Select from device</Button>
                </>
              )}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
            <Button variant="secondary" onClick={() => router.push('/')}>{t.common.cancel}</Button>
            <Button onClick={handleAnalyze} isLoading={analyzing} disabled={!fileUploaded || showError}>
              {t.screening.analyze}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}
