import { ReactNode } from 'react';

interface Tab {
  id: string;
  label: string;
  icon?: ReactNode;
  disabled?: boolean;
}

interface BaseTabsProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (tabId: string) => void;
  variant?: 'default' | 'pills' | 'underline';
  size?: 'sm' | 'md' | 'lg';
}

export default function BaseTabs({
  tabs,
  activeTab,
  onTabChange,
  variant = 'default',
  size = 'md',
}: BaseTabsProps) {
  const baseClasses = 'base-tabs';
  const variantClasses = `base-tabs-${variant}`;
  const sizeClasses = `base-tabs-${size}`;

  return (
    <div className={`${baseClasses} ${variantClasses} ${sizeClasses}`}>
      {tabs.map((tab) => (
        <button
          key={tab.id}
          onClick={() => !tab.disabled && onTabChange(tab.id)}
          disabled={tab.disabled}
          className={`base-tab ${activeTab === tab.id ? 'base-tab-active' : ''} ${
            tab.disabled ? 'base-tab-disabled' : ''
          }`}
        >
          {tab.icon && <span className="base-tab-icon">{tab.icon}</span>}
          <span className="base-tab-label">{tab.label}</span>
        </button>
      ))}
    </div>
  );
}