import { Card, StatCard } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';

export default function ReportsPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '2rem', color: 'var(--rs-primary-dark)', fontWeight: 700 }}>Screening Reports</h1>
          <p style={{ color: 'var(--rs-text-muted)' }}>Export aggregate data and clinical validation status.</p>
        </div>
        <Button>Export PDF</Button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '20px' }}>
        <StatCard value="240" label="Total Screenings This Month" />
        <StatCard value="85" label="Referred for Specialist Review" />
        <StatCard value="98%" label="AI-Clinician Agreement" />
      </div>

      <Card>
        <h2 style={{ fontSize: '1.2rem', marginBottom: '16px' }}>Monthly Breakdown</h2>
        <div style={{ padding: '60px', textAlign: 'center', background: 'var(--rs-bg-elevated)', borderRadius: '8px', color: 'var(--rs-text-muted)' }}>
          <p style={{ fontSize: '2rem' }}>📈</p>
          <p style={{ marginTop: '8px' }}>Chart visualization will appear here.</p>
        </div>
      </Card>
    </div>
  );
}
