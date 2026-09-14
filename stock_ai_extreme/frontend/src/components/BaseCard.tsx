import { ReactNode } from 'react';

interface BaseCardProps {
  children: ReactNode;
  className?: string;
  hoverable?: boolean;
  clickable?: boolean;
  onClick?: () => void;
  variant?: 'default' | 'bordered' | 'elevated';
  padding?: 'sm' | 'md' | 'lg';
}

export default function BaseCard({
  children,
  className = '',
  hoverable = false,
  clickable = false,
  onClick,
  variant = 'default',
  padding = 'md',
}: BaseCardProps) {
  const baseClasses = 'base-card';
  const variantClasses = `base-card-${variant}`;
  const paddingClasses = `base-card-padding-${padding}`;
  const hoverClass = hoverable ? 'base-card-hoverable' : '';
  const clickClass = clickable ? 'base-card-clickable' : '';

  return (
    <div
      className={`${baseClasses} ${variantClasses} ${paddingClasses} ${hoverClass} ${clickClass} ${className}`}
      onClick={clickable ? onClick : undefined}
    >
      {children}
    </div>
  );
}