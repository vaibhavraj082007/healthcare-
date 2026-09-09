import { Card } from '@/components/ui/Card';
import { t } from '@/lib/i18n';

export default function ReviewQueue() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div>
        <h1 style={{ fontSize: '2rem', color: 'var(--rs-primary-dark)', fontWeight: 700 }}>Ophthalmologist Review Queue</h1>
        <p style={{ color: 'var(--rs-text-muted)' }}>Cases pending specialist validation from PHCs.</p>
      </div>

      <Card>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--rs-border)', color: 'var(--rs-text-muted)' }}>
              <th style={{ padding: '12px' }}>Urgency</th>
              <th style={{ padding: '12px' }}>Patient / ID</th>
              <th style={{ padding: '12px' }}>Predicted Grade</th>
              <th style={{ padding: '12px' }}>Date Submitted</th>
              <th style={{ padding: '12px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ borderBottom: '1px solid var(--rs-border)', background: 'var(--rs-bg-elevated)' }}>
              <td style={{ padding: '12px' }}><span className="urgency-tag urgent">Urgent (1 Week)</span></td>
              <td style={{ padding: '12px', fontWeight: 600 }}>Sita D. (PAT-9824)</td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-4">Proliferative DR</span></td>
              <td style={{ padding: '12px' }}>Today, 09:15 AM</td>
              <td style={{ padding: '12px' }}><a href="/review/124" className="btn-primary" style={{ padding: '8px 16px', fontSize: '0.9rem', textDecoration: 'none' }}>Review Case</a></td>
            </tr>
            <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
              <td style={{ padding: '12px' }}><span className="urgency-tag priority">Priority (3 Months)</span></td>
              <td style={{ padding: '12px', fontWeight: 600 }}>Ramesh K. (PAT-9821)</td>
              <td style={{ padding: '12px' }}><span className="severity-badge grade-2">Moderate NPDR</span></td>
              <td style={{ padding: '12px' }}>Today, 10:42 AM</td>
              <td style={{ padding: '12px' }}><a href="/review/123" className="btn-secondary" style={{ padding: '8px 16px', fontSize: '0.9rem', textDecoration: 'none' }}>Review Case</a></td>
            </tr>
          </tbody>
        </table>
      </Card>
    </div>
  );
}
