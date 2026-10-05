import { ReactNode } from 'react';

interface BaseBadgeProps {
  children: ReactNode;
  variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'secondary' | 'outline';
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export default function BaseBadge({
  children,
  variant = 'default',
  size = 'md',
  className = '',
}: BaseBadgeProps) {
  const baseClasses = 'base-badge';
  const variantClasses = `base-badge-${variant}`;
  const sizeClasses = `base-badge-${size}`;

  return (
    <span className={`${baseClasses} ${variantClasses} ${sizeClasses} ${className}`}>
      {children}
    </span>
  );
}