import React from 'react';

export function ChartSkeleton() {
  return (
    <div className="skeleton chart-skeleton">
      <div className="skeleton-header">
        <div className="skeleton-title" />
        <div className="skeleton-controls">
          <div className="skeleton-select" />
          <div className="skeleton-badge" />
        </div>
      </div>
      <div className="skeleton-chart" />
      <div className="skeleton-overlays">
        <div className="skeleton-checkbox" />
        <div className="skeleton-checkbox" />
        <div className="skeleton-checkbox" />
      </div>
    </div>
  );
}

export function CardSkeleton() {
  return (
    <div className="skeleton card-skeleton">
      <div className="skeleton-label" />
      <div className="skeleton-value" />
      <div className="skeleton-sub" />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="skeleton table-skeleton">
      <div className="skeleton-header-row">
        <div className="skeleton-cell" />
        <div className="skeleton-cell" />
        <div className="skeleton-cell" />
        <div className="skeleton-cell" />
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="skeleton-row">
          <div className="skeleton-cell" />
          <div className="skeleton-cell" />
          <div className="skeleton-cell" />
          <div className="skeleton-cell" />
        </div>
      ))}
    </div>
  );
}

export function ProfileSkeleton() {
  return (
    <div className="skeleton profile-skeleton">
      <div className="skeleton-profile-header">
        <div className="skeleton-title" />
        <div className="skeleton-meta" />
      </div>
      <div className="skeleton-summary" />
    </div>
  );
}

export function LoadingSpinner({ size = 'medium' }: { size?: 'small' | 'medium' | 'large' }) {
  const sizeClasses = {
    small: 'w-4 h-4',
    medium: 'w-8 h-8',
    large: 'w-12 h-12',
  };

  return (
    <div className={`loading-spinner ${sizeClasses[size]}`}>
      <div className="spinner-ring" />
    </div>
  );
}