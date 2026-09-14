import { ReactNode, ButtonHTMLAttributes } from 'react';

interface BaseButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'outline' | 'ghost' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  isLoading?: boolean;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
  fullWidth?: boolean;
}

export default function BaseButton({
  variant = 'primary',
  size = 'md',
  isLoading = false,
  leftIcon,
  rightIcon,
  fullWidth = false,
  children,
  disabled,
  className = '',
  ...props
}: BaseButtonProps) {
  const baseClasses = 'base-button';
  const variantClasses = `base-button-${variant}`;
  const sizeClasses = `base-button-${size}`;
  const widthClass = fullWidth ? 'base-button-full' : '';
  const disabledClass = disabled || isLoading ? 'base-button-disabled' : '';

  return (
    <button
      className={`${baseClasses} ${variantClasses} ${sizeClasses} ${widthClass} ${disabledClass} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <>
          <span className="base-button-spinner" />
          <span className="base-button-text">Loading...</span>
        </>
      ) : (
        <>
          {leftIcon && <span className="base-button-icon-left">{leftIcon}</span>}
          <span className="base-button-text">{children}</span>
          {rightIcon && <span className="base-button-icon-right">{rightIcon}</span>}
        </>
      )}
    </button>
  );
}