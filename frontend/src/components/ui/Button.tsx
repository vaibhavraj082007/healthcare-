import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary';
  isLoading?: boolean;
}

export function Button({ children, variant = 'primary', isLoading, className = '', disabled, ...props }: ButtonProps) {
  const baseClass = variant === 'primary' ? 'btn-primary' : 'btn-secondary';
  return (
    <button className={`${baseClass} ${className}`} disabled={isLoading || disabled} {...props}>
      {isLoading && <div className="spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }}></div>}
      {children}
    </button>
  );
}
