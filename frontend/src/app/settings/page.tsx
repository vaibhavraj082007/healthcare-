import { Card } from '@/components/ui/Card';

export default function SettingsPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '800px', margin: '0 auto' }}>
      <div>
        <h1 style={{ fontSize: '2rem', color: 'var(--rs-primary-dark)', fontWeight: 700 }}>System Settings & Evaluation</h1>
        <p style={{ color: 'var(--rs-text-muted)' }}>Configure AI pipelines and view model metrics.</p>
      </div>

      <Card>
        <h2 style={{ fontSize: '1.2rem', marginBottom: '16px' }}>Current Model Pipeline</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          
          <div style={{ padding: '16px', background: 'var(--rs-bg-elevated)', borderRadius: '8px', borderLeft: '4px solid var(--rs-primary)' }}>
            <h4 style={{ fontWeight: 600 }}>Image Quality Assessment (MATLAB)</h4>
            <p style={{ fontSize: '0.9rem', color: 'var(--rs-text-muted)', marginTop: '4px' }}>Version: v1.0 (Heuristic)</p>
            <p style={{ fontSize: '0.9rem', marginTop: '4px' }}>Status: <span style={{ color: 'var(--rs-success)', fontWeight: 600 }}>Active</span></p>
          </div>

          <div style={{ padding: '16px', background: 'var(--rs-bg-elevated)', borderRadius: '8px', borderLeft: '4px solid var(--rs-primary)' }}>
            <h4 style={{ fontWeight: 600 }}>Severity Classification</h4>
            <p style={{ fontSize: '0.9rem', color: 'var(--rs-text-muted)', marginTop: '4px' }}>Model: EfficientNet-B0 (PyTorch)</p>
            <p style={{ fontSize: '0.9rem', marginTop: '4px' }}>Status: <span style={{ color: 'var(--rs-warning)', fontWeight: 600 }}>Training Required</span></p>
          </div>

          <div style={{ padding: '16px', background: 'var(--rs-bg-elevated)', borderRadius: '8px', borderLeft: '4px solid var(--rs-primary)' }}>
            <h4 style={{ fontWeight: 600 }}>Lesion Detection</h4>
            <p style={{ fontSize: '0.9rem', color: 'var(--rs-text-muted)', marginTop: '4px' }}>Model: YOLOv8</p>
            <p style={{ fontSize: '0.9rem', marginTop: '4px' }}>Status: <span style={{ color: 'var(--rs-warning)', fontWeight: 600 }}>Training Required</span></p>
          </div>

        </div>
      </Card>
      
      <Card>
        <h2 style={{ fontSize: '1.2rem', marginBottom: '16px' }}>Device Configuration</h2>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid var(--rs-border)' }}>
            <span>Hardware Acceleration</span>
            <strong>Enabled (CoreML)</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', paddingBottom: '8px', borderBottom: '1px solid var(--rs-border)' }}>
            <span>Offline Cache Size</span>
            <strong>1.2 GB / 10 GB</strong>
          </div>
        </div>
      </Card>
    </div>
  );
}
