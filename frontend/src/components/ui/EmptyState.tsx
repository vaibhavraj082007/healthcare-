import React from 'react';

export function EmptyState({ title, message, icon = 'ℹ️' }: { title: string, message: string, icon?: string }) {
  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '48px 24px',
      textAlign: 'center',
      background: '#f8fafc',
      border: '1px dashed #cbd5e1',
      borderRadius: '12px',
      color: '#64748b'
    }}>
      <div style={{ fontSize: '3rem', marginBottom: '16px', opacity: 0.8 }}>{icon}</div>
      <h3 style={{ fontSize: '1.2rem', fontWeight: 600, color: '#334155', marginBottom: '8px' }}>{title}</h3>
      <p style={{ maxWidth: '400px', lineHeight: 1.5 }}>{message}</p>
    </div>
  );
}
