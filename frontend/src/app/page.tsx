import { Card, StatCard } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { t } from '@/lib/i18n';

export default function Dashboard() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '2rem', color: 'var(--rs-primary-dark)', fontWeight: 700 }}>{t.dashboard.title}</h1>
          <p style={{ color: 'var(--rs-text-muted)' }}>Welcome back, hw-anita. Primary Health Centre: Rural-04</p>
        </div>
        <a href="/screening/new" style={{ textDecoration: 'none' }}>
          <Button style={{ padding: '16px 32px' }}>
            <span style={{ fontSize: '1.2rem', marginRight: '8px' }}>+</span> 
            {t.dashboard.newScreening}
          </Button>
        </a>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '20px' }}>
        <StatCard value={12} label="Screenings Today" />
        <StatCard value={4} label="Referrals Needed" />
        <StatCard value={28} label="Sync Pending" />
      </div>

      <Card>
        <h2 style={{ fontSize: '1.2rem', marginBottom: '16px', color: 'var(--rs-text)' }}>{t.dashboard.recentScreenings}</h2>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '2px solid var(--rs-border)', color: 'var(--rs-text-muted)' }}>
                <th style={{ padding: '12px' }}>Patient</th>
                <th style={{ padding: '12px' }}>Time</th>
                <th style={{ padding: '12px' }}>Quality</th>
                <th style={{ padding: '12px' }}>Status</th>
                <th style={{ padding: '12px' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
                <td style={{ padding: '12px', fontWeight: 600 }}>Ramesh K.</td>
                <td style={{ padding: '12px', color: 'var(--rs-text-muted)' }}>10:42 AM</td>
                <td style={{ padding: '12px' }}><span className="severity-badge grade-0">Acceptable</span></td>
                <td style={{ padding: '12px' }}><span className="urgency-tag priority">Requires Review</span></td>
                <td style={{ padding: '12px' }}><a href="/screening/results/123" style={{ color: 'var(--rs-primary)', fontWeight: 600 }}>View Result</a></td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
                <td style={{ padding: '12px', fontWeight: 600 }}>Sita D.</td>
                <td style={{ padding: '12px', color: 'var(--rs-text-muted)' }}>09:15 AM</td>
                <td style={{ padding: '12px' }}><span className="severity-badge grade-3">Ungradeable</span></td>
                <td style={{ padding: '12px' }}><span className="urgency-tag urgent">Recapture Needed</span></td>
                <td style={{ padding: '12px' }}><a href="/screening/results/124" style={{ color: 'var(--rs-primary)', fontWeight: 600 }}>View Result</a></td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
