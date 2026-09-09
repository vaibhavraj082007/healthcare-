import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';

export default function PatientsList() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: '2rem', color: 'var(--rs-primary-dark)', fontWeight: 700 }}>Patient Directory</h1>
          <p style={{ color: 'var(--rs-text-muted)' }}>Manage registered patients and view histories.</p>
        </div>
        <Button>Register New Patient</Button>
      </div>

      <Card>
        <div style={{ display: 'flex', gap: '12px', marginBottom: '20px' }}>
          <input type="text" className="form-input" placeholder="Search by Name or ID..." style={{ maxWidth: '400px' }} />
          <Button variant="secondary">Search</Button>
        </div>
        
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid var(--rs-border)', color: 'var(--rs-text-muted)' }}>
              <th style={{ padding: '12px' }}>ID</th>
              <th style={{ padding: '12px' }}>Name</th>
              <th style={{ padding: '12px' }}>Last Screening</th>
              <th style={{ padding: '12px' }}>Action</th>
            </tr>
          </thead>
          <tbody>
            <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
              <td style={{ padding: '12px' }}>PAT-9821</td>
              <td style={{ padding: '12px', fontWeight: 600 }}>Ramesh K.</td>
              <td style={{ padding: '12px' }}>Oct 14, 2026</td>
              <td style={{ padding: '12px' }}><a href="/patients/PAT-9821" style={{ color: 'var(--rs-primary)', fontWeight: 600 }}>View History</a></td>
            </tr>
            <tr style={{ borderBottom: '1px solid var(--rs-border)' }}>
              <td style={{ padding: '12px' }}>PAT-9824</td>
              <td style={{ padding: '12px', fontWeight: 600 }}>Sita D.</td>
              <td style={{ padding: '12px' }}>Oct 14, 2026</td>
              <td style={{ padding: '12px' }}><a href="/patients/PAT-9824" style={{ color: 'var(--rs-primary)', fontWeight: 600 }}>View History</a></td>
            </tr>
          </tbody>
        </table>
      </Card>
    </div>
  );
}
