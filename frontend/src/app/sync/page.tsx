'use client';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import React, { useState } from 'react';

export default function SyncPage() {
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState('Today, 08:00 AM');

  const handleSync = () => {
    setSyncing(true);
    setTimeout(() => {
      setSyncing(false);
      setLastSync('Just now');
    }, 2000);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', maxWidth: '800px', margin: '0 auto' }}>
      <div>
        <h1 style={{ fontSize: '2rem', color: 'var(--rs-primary-dark)', fontWeight: 700 }}>Data Synchronization</h1>
        <p style={{ color: 'var(--rs-text-muted)' }}>Manage offline data sync with central clinical servers.</p>
      </div>

      <Card>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
          <div>
            <h3 style={{ fontSize: '1.2rem', color: 'var(--rs-text)' }}>Cloud Sync Status</h3>
            <p style={{ color: 'var(--rs-text-muted)', marginTop: '4px' }}>Last synced: {lastSync}</p>
          </div>
          <Button onClick={handleSync} isLoading={syncing}>
            {syncing ? 'Syncing...' : 'Sync Now'}
          </Button>
        </div>

        <div style={{ background: 'var(--rs-bg-elevated)', borderRadius: '8px', padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--rs-border)' }}>
            <span>Pending Screenings Uploads</span>
            <strong>28 records</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid var(--rs-border)' }}>
            <span>Pending Ophthalmologist Validations</span>
            <strong>5 records</strong>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
            <span>Model Updates Available</span>
            <strong style={{ color: 'var(--rs-success)' }}>Up to date</strong>
          </div>
        </div>
      </Card>
    </div>
  );
}
