import { ReactNode } from 'react';
import { AlertCircle, Inbox, Search } from 'lucide-react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  variant?: 'default' | 'search' | 'error';
}

export default function EmptyState({
  icon,
  title,
  description,
  action,
  variant = 'default',
}: EmptyStateProps) {
  const getDefaultIcon = () => {
    switch (variant) {
      case 'search':
        return <Search size={48} />;
      case 'error':
        return <AlertCircle size={48} />;
      default:
        return <Inbox size={48} />;
    }
  };

  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon || getDefaultIcon()}</div>
      <h3 className="empty-state-title">{title}</h3>
      {description && <p className="empty-state-description">{description}</p>}
      {action && <div className="empty-state-action">{action}</div>}
    </div>
  );
}