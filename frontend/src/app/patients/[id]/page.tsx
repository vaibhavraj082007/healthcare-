'use client';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { t } from '@/lib/i18n';
import React from 'react';
import { useRouter } from 'next/navigation';

export default function PatientHistory({ params }: { params: { id: string } }) {
  const router = useRouter();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '1.8rem', color: 'var(--rs-primary-dark)' }}>Patient History</h1>
          <p style={{ color: 'var(--rs-text-muted)' }}>ID: {params.id} • Ramesh K. • 58 yrs • Male</p>
        </div>
        <Button onClick={() => router.push('/screening/new')}>New Screening</Button>
      </div>

      <Card>
        <h2 style={{ fontSize: '1.2rem', marginBottom: '16px', color: 'var(--rs-text)' }}>Past Screenings</h2>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--rs-border)', color: 'var(--rs-text-muted)' }}>
              <th style={{ padding: '12px' }}>Date</th>
              <th style={{ padding: '12px' }}>Eye</th>
              <th style={{ padding: '12px' }}>Severity</th>
              <th style={{ padding: '12px' }}>Quality</th>
              <th style={{ padding: '12px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
              <td style={{ padding: '12px' }}>Oct 14, 2026</td>
              <td style={{ padding: '12px' }}>Right (OD)</td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-2">Moderate NPDR</span></td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-0">Acceptable</span></td>
              <td style={{ padding: '12px' }}><a href="/screening/results/123" style={{ color: 'var(--rs-primary)', fontWeight: 600 }}>View Details</a></td>
            </tr>
            <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
              <td style={{ padding: '12px' }}>Oct 14, 2026</td>
              <td style={{ padding: '12px' }}>Left (OS)</td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-1">Mild NPDR</span></td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-0">Acceptable</span></td>
              <td style={{ padding: '12px' }}><a href="/screening/results/124" style={{ color: 'var(--rs-primary)', fontWeight: 600 }}>View Details</a></td>
            </tr>
            <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
              <td style={{ padding: '12px' }}>Jan 05, 2025</td>
              <td style={{ padding: '12px' }}>Right (OD)</td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-1">Mild NPDR</span></td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-0">Acceptable</span></td>
              <td style={{ padding: '12px' }}><a href="/screening/results/10" style={{ color: 'var(--rs-primary)', fontWeight: 600 }}>View Details</a></td>
            </tr>
          </tbody>
        </table>
      </Card>
    </div>
  );
}
