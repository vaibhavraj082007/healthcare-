'use client';
import { Card } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import { t } from '@/lib/i18n';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function Login() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  const handleLogin = (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    // Mock login delay
    setTimeout(() => {
      router.push('/');
    }, 800);
  };

  return (
    <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '70vh' }}>
      <Card style={{ maxWidth: '400px', width: '100%' }}>
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <span style={{ fontSize: '3rem' }}>🛡️</span>
          <h1 style={{ fontSize: '1.5rem', color: 'var(--rs-primary-dark)', marginTop: '8px' }}>{t.login.title}</h1>
          <p style={{ color: 'var(--rs-text-muted)', fontSize: '0.9rem', marginTop: '4px' }}>Sign in to RetinaShield</p>
        </div>

        <form onSubmit={handleLogin} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div>
            <label className="form-label">{t.login.username}</label>
            <input type="text" className="form-input" required placeholder="e.g. HW-1042" />
          </div>
          <div>
            <label className="form-label">{t.login.password}</label>
            <input type="password" className="form-input" required placeholder="••••••••" />
          </div>
          <Button type="submit" isLoading={loading} style={{ marginTop: '12px' }}>
            {t.login.submit}
          </Button>
        </form>
      </Card>
    </div>
  );
}
